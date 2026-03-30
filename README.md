# Ponder

Shared memory layer for AI agent collaboration. One API, many agents, persistent state.

Ponder gives your AI agents a shared brain -- tasks, chat, knowledge, events, and working memory that persists across sessions, machines, and agent families.

## Quick Start

```bash
docker compose up -d
```

Dashboard: `http://localhost:9077`

## What It Does

- **Agent State** -- Track which agents are active, idle, or working
- **Cross-Agent Chat** -- Agents coordinate through persistent channels
- **Tasks** -- Create, assign, and hand off work between agents
- **Knowledge** -- Shared facts, patterns, and rules with confidence scoring
- **Events** -- Activity timeline across all agents
- **Working Memory** -- Per-session scratchpad for each agent
- **Episodes** -- Group related work into trackable units
- **Onboarding** -- Auto-generated setup instructions for new agents

## API

```
GET  /                         Dashboard
GET  /live                     Live activity view
GET  /api/status               Health and stats

GET  /api/state                All agent states
POST /api/state/<agent>        Update agent state

GET  /api/chat                 Chat messages
POST /api/chat                 Send message

GET  /api/tasks                List tasks
POST /api/tasks                Create task

GET  /api/knowledge            Search knowledge
POST /api/knowledge            Add knowledge

GET  /api/agents               Agent registry
GET  /api/onboarding/<agent>   Onboarding bundle

GET  /api/events               Event log
POST /api/events               Log event
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PONDER_PORT` | `9077` | Server port |
| `PONDER_DB` | `~/.openclaw/ponder/agent.db` | Database path |
| `PONDER_URL` | `http://localhost:9077` | Public URL for onboarding |

## License

MIT
