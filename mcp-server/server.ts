#!/usr/bin/env bun
/**
 * Ponder MCP Server -- Shared memory channel for Claude Code.
 *
 * Connects to a Ponder instance and provides:
 * - Chat notifications (agent-to-agent and human-to-agent)
 * - Tools for replying, updating state, managing tasks
 * - Live polling for new messages with push notifications
 *
 * Config via env:
 *   PONDER_URL        Base URL of the Ponder server (default: http://localhost:9077)
 *   PONDER_AGENT_ID   This agent's ID (default: claude)
 *   PONDER_POLL_MS    Poll interval in ms (default: 3000)
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from '@modelcontextprotocol/sdk/types.js'

import { appendFileSync } from 'node:fs'

const PONDER_URL = process.env.PONDER_URL || 'http://localhost:9077'
const AGENT_ID = process.env.PONDER_AGENT_ID || 'claude'
const POLL_MS = parseInt(process.env.PONDER_POLL_MS || '3000', 10)
const DEBUG_LOG = `${process.env.HOME}/.claude/channels/ponder/debug.log`

function debugLog(msg: string) {
  const ts = new Date().toISOString()
  try { appendFileSync(DEBUG_LOG, `${ts} ${msg}\n`) } catch {}
}

process.on('unhandledRejection', err => {
  process.stderr.write(`ponder mcp: unhandled rejection: ${err}\n`)
})
process.on('uncaughtException', err => {
  process.stderr.write(`ponder mcp: uncaught exception: ${err}\n`)
})

// ── Shared state ─────────────────────────────────────────

let lastSeenMessageId = 0
const agentIdLower = AGENT_ID.toLowerCase()

type ChatMessage = {
  id: number
  sender_agent: string
  target_agent: string | null
  channel: string
  body: string
  created_at: string
}

// ── HTTP helpers ──────────────────────────────────────────

async function api(method: string, path: string, body?: unknown): Promise<unknown> {
  const url = `${PONDER_URL}${path}`
  const opts: RequestInit = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const res = await fetch(url, opts)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Ponder API ${method} ${path}: ${res.status} ${text}`)
  }
  return res.json()
}

// ── MCP Server ───────────────────────────────────────────

const mcp = new Server(
  { name: 'ponder', version: '0.3.0' },
  {
    capabilities: {
      tools: {},
      experimental: {
        'claude/channel': {},
      },
    },
    instructions: [
      'Messages from Ponder arrive as <channel source="ponder" chat_id="..." message_id="..." user="..." ts="...">.',
      'chat_id is the Ponder channel name (e.g. "general"). Reply with the reply tool, passing the channel name back.',
      'user is the sender\'s agent ID (e.g. "Human", "claude-win"). Respond to messages directed at you or mentioning you.',
    ].join('\n'),
  },
)

// ── Tools ────────────────────────────────────────────────

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'reply',
      description: 'Send a chat message to a Ponder channel. Use to communicate with other agents or the human.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          channel: { type: 'string', description: 'Channel to post to (e.g. "general", "hydra")' },
          body: { type: 'string', description: 'Message content (supports markdown)' },
          target_agent: { type: 'string', description: 'Optional: direct message to a specific agent' },
        },
        required: ['channel', 'body'],
      },
    },
    {
      name: 'update_state',
      description: 'Update this agent\'s state in Ponder (status, current task).',
      inputSchema: {
        type: 'object' as const,
        properties: {
          status: { type: 'string', enum: ['active', 'working', 'idle', 'waiting'], description: 'Agent status' },
          current_task: { type: 'string', description: 'What the agent is currently doing' },
        },
        required: ['status'],
      },
    },
    {
      name: 'create_task',
      description: 'Create a new task in Ponder.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          title: { type: 'string', description: 'Task title' },
          description: { type: 'string', description: 'Task description' },
          assigned_to: { type: 'string', description: 'Agent to assign to' },
          priority: { type: 'string', description: 'Priority level' },
        },
        required: ['title'],
      },
    },
    {
      name: 'complete_task',
      description: 'Mark a task as completed.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          task_id: { type: 'number', description: 'Task ID to complete' },
          result: { type: 'string', description: 'Completion summary' },
        },
        required: ['task_id'],
      },
    },
    {
      name: 'add_knowledge',
      description: 'Add a knowledge entry to Ponder.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          subject: { type: 'string', description: 'Subject/topic' },
          predicate: { type: 'string', description: 'Relationship type' },
          object: { type: 'string', description: 'The knowledge content' },
          category: { type: 'string', description: 'Category (fact, pattern, rule, workflow, decision)' },
          confidence: { type: 'number', description: 'Confidence 0.0-1.0 (default: 0.8)' },
        },
        required: ['subject', 'predicate', 'object'],
      },
    },
    {
      name: 'log_event',
      description: 'Log an event to the Ponder activity timeline.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          event_type: { type: 'string', description: 'Event type (commit, push, deploy, session_start, etc.)' },
          data: { type: 'string', description: 'Event data as JSON string' },
          target_agent: { type: 'string', description: 'Optional target agent' },
        },
        required: ['event_type'],
      },
    },
    {
      name: 'handoff',
      description: 'Hand off work to another agent via Ponder.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          to_agent: { type: 'string', description: 'Agent to hand off to' },
          title: { type: 'string', description: 'Handoff title/summary' },
          description: { type: 'string', description: 'Detailed handoff instructions' },
          channel: { type: 'string', description: 'Channel for the handoff chat message (default: general)' },
        },
        required: ['to_agent', 'title'],
      },
    },
    {
      name: 'get_messages',
      description: 'Fetch chat messages from Ponder. Without since_id, returns the latest messages. Use as fallback if push notifications are not arriving.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          channel: { type: 'string', description: 'Optional: filter by channel' },
          since_id: { type: 'integer', description: 'Optional: only return messages after this ID' },
          limit: { type: 'integer', description: 'Max messages to return (default: 50, max: 200)' },
        },
      },
    },
    {
      name: 'get_context',
      description: 'Get cross-tier context from Ponder for a topic.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          topic: { type: 'string', description: 'Topic to get context for' },
        },
        required: ['topic'],
      },
    },
  ],
}))

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params
  try {
    switch (name) {
      case 'reply': {
        await api('POST', '/api/chat', {
          sender_agent: AGENT_ID,
          channel: args!.channel,
          body: args!.body,
          target_agent: args!.target_agent || null,
        })
        return { content: [{ type: 'text', text: `Message sent to #${args!.channel}` }] }
      }

      case 'update_state': {
        await api('POST', `/api/state/${AGENT_ID}`, {
          status: args!.status,
          current_task: args!.current_task || null,
        })
        return { content: [{ type: 'text', text: `State updated: ${args!.status}` }] }
      }

      case 'create_task': {
        const result = await api('POST', '/api/tasks', {
          title: args!.title,
          description: args!.description || null,
          created_by: AGENT_ID,
          assigned_to: args!.assigned_to || null,
          priority: args!.priority || null,
        }) as { id: number }
        return { content: [{ type: 'text', text: `Task #${result.id} created: ${args!.title}` }] }
      }

      case 'complete_task': {
        await api('POST', `/api/tasks/${args!.task_id}/complete`, {
          result: args!.result || null,
        })
        return { content: [{ type: 'text', text: `Task #${args!.task_id} completed` }] }
      }

      case 'add_knowledge': {
        const result = await api('POST', '/api/knowledge', {
          subject: args!.subject,
          predicate: args!.predicate,
          object: args!.object,
          category: args!.category || 'fact',
          confidence: args!.confidence ?? 0.8,
          source: AGENT_ID,
        }) as { id: number }
        return { content: [{ type: 'text', text: `Knowledge #${result.id} added: ${args!.subject}` }] }
      }

      case 'log_event': {
        await api('POST', '/api/events', {
          event_type: args!.event_type,
          source_agent: AGENT_ID,
          target_agent: args!.target_agent || null,
          data: args!.data || null,
        })
        return { content: [{ type: 'text', text: `Event logged: ${args!.event_type}` }] }
      }

      case 'handoff': {
        const result = await api('POST', '/api/handoff', {
          from_agent: AGENT_ID,
          to_agent: args!.to_agent,
          title: args!.title,
          description: args!.description || null,
        }) as { task_id: number }
        const channel = args!.channel || 'general'
        void api('POST', '/api/chat', {
          sender_agent: AGENT_ID,
          target_agent: args!.to_agent,
          channel,
          body: `Handoff: ${args!.title}${args!.description ? '\n\n' + args!.description : ''}`,
        }).catch(err => process.stderr.write(`ponder: handoff chat post failed: ${err}\n`))
        return { content: [{ type: 'text', text: `Handoff to ${args!.to_agent}: task #${result.task_id} created, chat notification queued for #${channel}` }] }
      }

      case 'get_messages': {
        const sinceId = Math.max(0, Math.floor(Number(args?.since_id) || 0))
        const limit = Math.min(200, Math.max(1, Math.floor(Number(args?.limit) || 50)))
        const sinceParam = sinceId > 0 ? `&since=${sinceId}` : ''
        const channelParam = args?.channel ? `&channel=${encodeURIComponent(args.channel as string)}` : ''
        const messages = await api('GET', `/api/chat?agent_id=${encodeURIComponent(AGENT_ID)}&limit=${limit}${sinceParam}${channelParam}`) as ChatMessage[]

        const incoming = messages.filter(m => m.sender_agent.toLowerCase() !== agentIdLower)

        // Only advance shared cursor when caller provided since_id (incremental read)
        if (sinceId > 0 && messages.length > 0) {
          lastSeenMessageId = Math.max(lastSeenMessageId, ...messages.map(m => m.id))
        }

        if (incoming.length === 0) {
          return { content: [{ type: 'text', text: 'No new messages.' }] }
        }

        const formatted = incoming.map(m =>
          `[${m.created_at}] #${m.channel} (id:${m.id}) ${m.sender_agent}${m.target_agent ? ` -> ${m.target_agent}` : ''}: ${m.body}`
        ).join('\n')
        return { content: [{ type: 'text', text: formatted }] }
      }

      case 'get_context': {
        const result = await api('GET', `/api/context/${encodeURIComponent(args!.topic as string)}`)
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] }
      }

      default:
        return { content: [{ type: 'text', text: `Unknown tool: ${name}` }], isError: true }
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return { content: [{ type: 'text', text: `Error: ${msg}` }], isError: true }
  }
})

// ── Chat Polling (Push Notifications) ────────────────────

async function pollChat(): Promise<void> {
  try {
    const sinceParam = lastSeenMessageId > 0 ? `&since=${lastSeenMessageId}` : ''
    const url = `/api/chat?agent_id=${encodeURIComponent(AGENT_ID)}&limit=100${sinceParam}`
    debugLog(`POLL cursor=${lastSeenMessageId} url=${url}`)
    const messages = await api('GET', url) as ChatMessage[]
    debugLog(`POLL got ${messages.length} messages`)

    for (const m of messages) {
      lastSeenMessageId = Math.max(lastSeenMessageId, m.id)

      if (m.sender_agent.toLowerCase() === agentIdLower) {
        debugLog(`SKIP own message #${m.id}`)
        continue
      }

      const payload = {
        method: 'notifications/claude/channel' as const,
        params: {
          content: m.body,
          meta: {
            chat_id: m.channel,
            message_id: String(m.id),
            user: m.sender_agent,
            ts: m.created_at,
            ...(m.target_agent ? { target_agent: m.target_agent } : {}),
          },
        },
      }
      debugLog(`NOTIFY #${m.id} payload=${JSON.stringify(payload)}`)
      mcp.notification(payload).then(() => {
        debugLog(`NOTIFY #${m.id} SUCCESS`)
      }).catch(err => {
        debugLog(`NOTIFY #${m.id} FAILED: ${err}`)
        process.stderr.write(`ponder: notification delivery failed for #${m.id}: ${err}\n`)
      })
      process.stderr.write(`ponder: forwarded #${m.id} from ${m.sender_agent} in #${m.channel}\n`)
    }
  } catch (err) {
    debugLog(`POLL ERROR: ${err}`)
    process.stderr.write(`ponder: poll error: ${err}\n`)
  }
}

// ── Startup ──────────────────────────────────────────────

async function main() {
  // Set agent state to active
  try {
    await api('POST', `/api/state/${AGENT_ID}`, {
      status: 'active',
      current_task: 'Connected via MCP',
    })
  } catch {
    process.stderr.write(`ponder: warning: could not set initial state (server unreachable?)\n`)
  }

  // Seed lastSeenMessageId before connecting so no messages are missed
  try {
    const recent = await api('GET', `/api/chat?agent_id=${encodeURIComponent(AGENT_ID)}&limit=1`) as ChatMessage[]
    if (recent.length > 0) {
      lastSeenMessageId = recent[recent.length - 1].id
    }
  } catch {
    process.stderr.write(`ponder: warning: could not seed message cursor\n`)
  }

  // Connect MCP, then start polling
  const transport = new StdioServerTransport()
  await mcp.connect(transport)
  process.stderr.write(`ponder mcp: connected as ${AGENT_ID} to ${PONDER_URL}\n`)
  debugLog(`STARTUP connected as ${AGENT_ID} to ${PONDER_URL}, cursor=#${lastSeenMessageId}, poll=${POLL_MS}ms`)

  // Start polling loop after connection is established
  process.stderr.write(`ponder mcp: polling every ${POLL_MS}ms, cursor seeded at #${lastSeenMessageId}\n`)
  void (async () => {
    while (true) {
      await new Promise(r => setTimeout(r, POLL_MS))
      await pollChat()
    }
  })()
}

main().catch(err => {
  process.stderr.write(`ponder mcp: fatal: ${err}\n`)
  process.exit(1)
})
