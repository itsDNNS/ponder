#!/usr/bin/env python3
"""Agent Memory Daemon -- REST API for shared agent state.

Runs on localhost:9077 (mnemonic: 90 = memory, 77 = lucky).
Used by Nova (Python), Claude (CLI/curl), and Dennis (browser).

Start:  python daemon.py
Stop:   kill $(cat ~/.openclaw/agent-memory/daemon.pid)

API:
  GET  /                         Dashboard (HTML)
  GET  /api/status               Stats and health
  GET  /api/agents              Agent registry
  GET  /api/agents/<agent_id>   Single agent profile
  POST /api/agents/<agent_id>   Upsert agent profile
  GET  /api/onboarding/<agent>  Canonical onboarding bundle
  GET  /api/chat                Agent chat messages
  POST /api/chat                Append agent chat message
  GET  /api/state                All agent states
  GET  /api/state/<agent_id>     Single agent state
  POST /api/state/<agent_id>     Update agent state
  GET  /api/tasks                List tasks
  POST /api/tasks                Create task
  POST /api/tasks/<id>/claim     Claim task
  POST /api/tasks/<id>/complete  Complete task
  POST /api/tasks/<id>/fail      Fail task
  GET  /api/events               List events
  POST /api/events               Append event
  POST /api/handoff              Create handoff

  POST /api/sessions             Start session
  GET  /api/sessions             List sessions
  POST /api/sessions/<id>/end    End session -> Episode
  GET  /api/wm/<agent_id>        Get working memory
  POST /api/wm/<agent_id>        Set working memory key
  DELETE /api/wm/<agent_id>/<key> Delete working memory key
  GET  /api/episodes              Search episodes
  POST /api/episodes              Create episode
  GET  /api/episodes/<id>         Get episode detail
  POST /api/episodes/<id>/complete  Complete episode
  POST /api/episodes/<id>/link      Link event to episode
  GET  /api/knowledge             Search knowledge
  POST /api/knowledge             Learn (add knowledge)
  POST /api/knowledge/<id>/validate Validate knowledge
  POST /api/knowledge/<id>/forget   Forget knowledge
  POST /api/maintenance            Run cleanup + decay
  GET  /api/context/<topic>       Cross-tier context
"""

import json
import logging
import os
import re
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, request, render_template_string

from memory import AgentMemory

log = logging.getLogger("agent-memory")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

PORT = int(os.environ.get("AGENT_MEMORY_PORT", 9077))
DOCKER = os.environ.get("DOCKER", "").strip() == "1"
PID_FILE = Path.home() / ".openclaw" / "agent-memory" / "daemon.pid"

app = Flask(__name__)
mem = AgentMemory()

# ── Dashboard ────────────────────────────────────────────────

DASHBOARD_HTML = """<!doctype html>
<html><head>
<title>Agent Memory</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: monospace; background: #1a1a2e; color: #e0e0e0; margin: 2em; }
  h1 { color: #e94560; margin-bottom: 0.4em; }
  h2 { color: #e0e0e0; border-bottom: 1px solid #333; padding-bottom: 4px; margin-top: 1.4em; }
  h3 { color: #22d3ee; margin: 1em 0 0.5em 0; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 2em; }
  th, td { text-align: left; padding: 6px 12px; border-bottom: 1px solid #333; vertical-align: top; }
  th { color: #e94560; }
  input, textarea, button, select { font: inherit; }
  input, textarea, select { width: 100%; background: #16213e; color: #e0e0e0; border: 1px solid #333; border-radius: 6px; padding: 8px 10px; }
  textarea { min-height: 100px; resize: vertical; }
  button { background: #e94560; color: #fff; border: none; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
  button:hover { background: #c73650; }
  .status-idle { color: #888; }
  .status-active, .status-working { color: #4ade80; }
  .status-waiting { color: #facc15; }
  .pending { color: #facc15; }
  .claimed { color: #60a5fa; }
  .done, .success { color: #4ade80; }
  .failed, .failure { color: #f87171; }
  .event-type { color: #c084fc; }
  .agent { color: #22d3ee; }
  .stats { display: flex; gap: 1em; margin-bottom: 2em; flex-wrap: wrap; }
  .stat { background: #16213e; padding: 12px 20px; border-radius: 8px; min-width: 140px; }
  .stat-value { font-size: 1.5em; color: #e94560; }
  .stat-label { font-size: 0.85em; color: #888; }
  .tabs { display: flex; gap: 0; margin: 2em 0 1.5em 0; border-bottom: 2px solid #333; flex-wrap: wrap; }
  .tab { padding: 10px 16px; cursor: pointer; color: #888; border-bottom: 2px solid transparent; margin-bottom: -2px; }
  .tab:hover { color: #e0e0e0; }
  .tab.active { color: #e94560; border-bottom-color: #e94560; }
  .tab-content { display: none; }
  .tab-content.active { display: block; }
  .confidence { display: inline-block; background: #333; border-radius: 4px; width: 60px; height: 8px; overflow: hidden; vertical-align: middle; }
  .confidence-fill { height: 100%; background: #4ade80; }
  .tag { display: inline-block; background: #0f3460; color: #60a5fa; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; margin: 1px; }
  .session-active { color: #4ade80; }
  .session-ended { color: #888; }
  .wm-key { color: #c084fc; }
  .pinned { border: 1px solid #e94560; border-radius: 8px; padding: 16px 20px; margin-bottom: 1em; background: #16213e; position: relative; }
  .pinned h3 { color: #e94560; margin: 0 0 8px 0; font-size: 1.05em; }
  .copy-btn { position: absolute; top: 12px; right: 12px; background: #e94560; color: #fff; border: none; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 0.85em; }
  .copy-btn.copied { background: #4ade80; color: #1a1a2e; }
  .panel { background: #16213e; border-radius: 8px; padding: 16px 18px; margin-bottom: 1em; }
  .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-bottom: 10px; }
  .muted { color: #888; }
  .prompt-box, pre { background: #0f172a; padding: 10px 12px; border-radius: 6px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }
  .chat-body { min-width: 360px; }
  .chat-target { color: #facc15; }
  .api-status { margin-top: 0.6em; color: #888; }
  .chat-shell { display: grid; grid-template-columns: minmax(220px, 280px) minmax(0, 1fr); gap: 16px; align-items: start; }
  .chat-sidebar { position: sticky; top: 1em; }
  .chat-main { min-width: 0; }
  .chat-sidebar h2, .chat-main h2 { margin-top: 0; }
  .chat-channel-tabs { display: flex; flex-direction: column; gap: 8px; margin: 12px 0 16px 0; }
  .chat-channel-tab { display: flex; justify-content: space-between; align-items: center; gap: 12px; width: 100%; padding: 10px 12px; border: 1px solid #23314f; border-radius: 8px; background: #0f172a; color: #dbe4ff; cursor: pointer; text-align: left; }
  .chat-channel-tab:hover { border-color: #37507e; background: #13203a; }
  .chat-channel-tab.active { border-color: #e94560; background: #1b223f; }
  .chat-channel-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chat-channel-count { font-size: 0.82em; color: #8aa3d1; }
  .chat-header-row { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
  .chat-toolbar { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 12px; }
  .chat-feed { background: #0f172a; border: 1px solid #23314f; border-radius: 8px; max-height: 58vh; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
  .chat-message { border: 1px solid #23314f; border-radius: 8px; padding: 10px 12px; background: #111b2f; }
  .chat-message.self { border-color: #295d5a; background: #102326; }
  .chat-message.remote { border-color: #2b395d; background: #111b2f; }
  .chat-meta { display: flex; gap: 12px; flex-wrap: wrap; color: #8aa3d1; font-size: 0.9em; margin-bottom: 6px; }
  .chat-channel-chip { border: 1px solid #37507e; border-radius: 999px; background: #13203a; color: #8aa3d1; padding: 2px 8px; cursor: pointer; }
  .chat-channel-chip:hover { color: #fff; border-color: #5c7db6; }
  .chat-text { white-space: pre-wrap; word-break: break-word; line-height: 1.45; }
  .chat-status-row { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin: 10px 0 6px 0; flex-wrap: wrap; }
  .chat-follow { color: #8aa3d1; font-size: 0.9em; }
  @media (max-width: 760px) {
    body { margin: 1em; }
    th, td { padding: 6px 8px; }
    .chat-shell { grid-template-columns: 1fr; }
    .chat-sidebar { position: static; }
    .chat-feed { max-height: 50vh; }
  }
</style>
</head><body>
<h1>Agent Memory</h1>
<div class="muted">Shared state, agent registry, onboarding bundle, and cross-agent chat.</div>

<div class="stats">
  <div class="stat"><div class="stat-value">{{ stats.agents }}</div><div class="stat-label">Active States</div></div>
  <div class="stat"><div class="stat-value">{{ agent_profiles|length }}</div><div class="stat-label">Known Agents</div></div>
  <div class="stat"><div class="stat-value">{{ stats.tasks_pending }}</div><div class="stat-label">Pending Tasks</div></div>
  <div class="stat"><div class="stat-value">{{ stats.events_total }}</div><div class="stat-label">Events</div></div>
  <div class="stat"><div class="stat-value">{{ stats.chat_total }}</div><div class="stat-label">Chat Messages</div></div>
  <div class="stat"><div class="stat-value">{{ stats.knowledge_active }}</div><div class="stat-label">Knowledge</div></div>
  <div class="stat"><div class="stat-value">{{ "%.1f KB"|format(stats.db_size_bytes / 1024) }}</div><div class="stat-label">DB Size</div></div>
</div>

{% for note in pinned_notes %}
<div class="pinned">
  <h3>{{ note.subject }}</h3>
  <button class="copy-btn" onclick="copyText(this, 'note-{{ note.id }}')">Copy</button>
  <pre id="note-{{ note.id }}">{{ note.object }}</pre>
</div>
{% endfor %}

<div class="tabs">
  <div class="tab active" data-tab="overview" onclick="showTab('overview', this)">Overview</div>
  <div class="tab" data-tab="chat" onclick="showTab('chat', this)">Chat</div>
  <div class="tab" data-tab="agents" onclick="showTab('agents', this)">Agents</div>
  <div class="tab" data-tab="working" onclick="showTab('working', this)">Working Memory</div>
  <div class="tab" data-tab="episodes" onclick="showTab('episodes', this)">Episodes</div>
  <div class="tab" data-tab="knowledge" onclick="showTab('knowledge', this)">Knowledge</div>
  <div class="tab" data-tab="onboarding" onclick="showTab('onboarding', this)">Onboarding</div>
</div>

<div id="tab-overview" class="tab-content active">
  <h2>Agent State</h2>
  <table>
    <tr><th>Agent</th><th>Status</th><th>Current Task</th><th>Updated</th></tr>
    {% for s in states %}
    <tr>
      <td class="agent">{{ s.agent_id }}</td>
      <td class="status-{{ s.status }}">{{ s.status }}</td>
      <td>{{ s.current_task or '-' }}</td>
      <td>{{ s.updated_at }}</td>
    </tr>
    {% endfor %}
    {% if not states %}<tr><td colspan="4" class="muted">No agents registered yet</td></tr>{% endif %}
  </table>

  <h2>Tasks</h2>
  <table>
    <tr><th>#</th><th>Title</th><th>Status</th><th>Assigned</th><th>Created By</th><th>Created</th></tr>
    {% for t in tasks %}
    <tr>
      <td>{{ t.id }}</td>
      <td>{{ t.title }}</td>
      <td class="{{ t.status }}">{{ t.status }}</td>
      <td class="agent">{{ t.assigned_to or '-' }}</td>
      <td class="agent">{{ t.created_by }}</td>
      <td>{{ t.created_at }}</td>
    </tr>
    {% endfor %}
    {% if not tasks %}<tr><td colspan="6" class="muted">No tasks yet</td></tr>{% endif %}
  </table>

  <h2>Recent Events</h2>
  <table>
    <tr><th>#</th><th>Type</th><th>Source</th><th>Target</th><th>Data</th><th>Time</th></tr>
    {% for e in events %}
    <tr>
      <td>{{ e.id }}</td>
      <td class="event-type">{{ e.event_type }}</td>
      <td class="agent">{{ e.source_agent }}</td>
      <td class="agent">{{ e.target_agent or '*' }}</td>
      <td><pre>{{ e.data or '-' }}</pre></td>
      <td>{{ e.created_at }}</td>
    </tr>
    {% endfor %}
    {% if not events %}<tr><td colspan="6" class="muted">No events yet</td></tr>{% endif %}
  </table>
</div>

<div id="tab-chat" class="tab-content">
  <div class="chat-shell">
    <aside class="panel chat-sidebar">
      <h2>Channels</h2>
      <div class="muted">Switch channels like an IRC client. The active channel is reflected in the URL.</div>
      <div id="chat-channel-tabs" class="chat-channel-tabs"></div>
      <div class="form-grid" style="margin-bottom:0;">
        <div>
          <label for="chat-quick-channel">Open Channel</label>
          <input id="chat-quick-channel" placeholder="general">
        </div>
      </div>
      <div style="margin-top:10px;">
        <button onclick="jumpToChatChannel()">Open</button>
      </div>
    </aside>
    <section class="chat-main">
      <div class="panel">
        <div class="chat-header-row">
          <div>
            <h2 id="chat-active-title">#all</h2>
            <div id="chat-feed-status" class="api-status">Watching chat feed.</div>
          </div>
          <span id="chat-follow-state" class="chat-follow">Follow mode: on</span>
        </div>
        <div class="chat-toolbar">
          <div>
            <label for="chat-watch-agent">Highlight Agent</label>
            <input id="chat-watch-agent" list="agent-ids" value="{{ default_onboarding_agent }}" placeholder="optional">
          </div>
          <div>
            <label for="chat-channel">Post Channel</label>
            <input id="chat-channel" value="{{ default_chat_channel if default_chat_channel != 'all' else 'general' }}">
          </div>
          <div>
            <label for="chat-target">Target</label>
            <input id="chat-target" list="agent-ids" placeholder="optional">
          </div>
          <div>
            <label for="chat-sender">Sender</label>
            <input id="chat-sender" list="agent-ids" value="{{ default_onboarding_agent }}">
          </div>
        </div>
        <label for="chat-body">Message</label>
        <textarea id="chat-body" placeholder="Write a handoff, coordination note, or question."></textarea>
        <div style="margin-top:10px;">
          <button onclick="sendChatMessage()">Send Message</button>
          <span id="chat-status" class="api-status"></span>
        </div>
      </div>
      <div id="chat-feed" class="chat-feed"></div>
    </section>
  </div>
</div>

<div id="tab-agents" class="tab-content">
  <h2>Agent Registry</h2>
  <table>
    <tr><th>Agent</th><th>Display Name</th><th>Status</th><th>Integration Mode</th><th>Integration Target</th><th>Native Feature</th><th>Onboarding Note</th></tr>
    {% for profile in agent_profiles %}
    <tr>
      <td class="agent">{{ profile.agent_id }}</td>
      <td>{{ profile.display_name }}</td>
      <td class="status-{{ profile.state.status if profile.state else 'idle' }}">{{ profile.state.status if profile.state else 'idle' }}</td>
      <td>{{ profile.integration_mode }}</td>
      <td>{{ profile.integration_target }}</td>
      <td>{{ profile.native_feature }}</td>
      <td>{{ profile.onboarding_note }}</td>
    </tr>
    {% endfor %}
  </table>
</div>

<div id="tab-working" class="tab-content">
  <h2>Active Sessions</h2>
  <table>
    <tr><th>Session</th><th>Agent</th><th>Started</th><th>Status</th></tr>
    {% for s in sessions %}
    <tr>
      <td>{{ s.id }}</td>
      <td class="agent">{{ s.agent_id }}</td>
      <td>{{ s.started_at }}</td>
      <td class="{{ 'session-active' if not s.ended_at else 'session-ended' }}">{{ 'active' if not s.ended_at else 'ended' }}</td>
    </tr>
    {% endfor %}
    {% if not sessions %}<tr><td colspan="4" class="muted">No sessions</td></tr>{% endif %}
  </table>

  <h2>Working Memory</h2>
  {% for agent_id, wm_data in wm_by_agent.items() %}
  <h3>{{ agent_id }} ({{ wm_data.session_id }})</h3>
  <table>
    <tr><th>Key</th><th>Value</th></tr>
    {% for k, v in wm_data.items.items() %}
    <tr><td class="wm-key">{{ k }}</td><td>{{ v }}</td></tr>
    {% endfor %}
    {% if not wm_data.items %}<tr><td colspan="2" class="muted">(empty)</td></tr>{% endif %}
  </table>
  {% endfor %}
  {% if not wm_by_agent %}<p class="muted">No active working memory.</p>{% endif %}
</div>

<div id="tab-episodes" class="tab-content">
  <h2>Episodes</h2>
  <table>
    <tr><th>#</th><th>Title</th><th>Agent</th><th>Category</th><th>Outcome</th><th>Tags</th><th>Started</th></tr>
    {% for ep in all_episodes %}
    <tr>
      <td>{{ ep.id }}</td>
      <td>{{ ep.title }}</td>
      <td class="agent">{{ ep.agent_id }}</td>
      <td>{{ ep.category }}</td>
      <td class="{{ ep.outcome or '' }}">{{ ep.outcome or '...' }}</td>
      <td>{% if ep.tags %}{% for tag in ep.tags_list %}<span class="tag">{{ tag }}</span>{% endfor %}{% endif %}</td>
      <td>{{ ep.started_at }}</td>
    </tr>
    {% endfor %}
    {% if not all_episodes %}<tr><td colspan="7" class="muted">No episodes yet</td></tr>{% endif %}
  </table>
</div>

<div id="tab-knowledge" class="tab-content">
  <h2>Knowledge Base</h2>
  <table>
    <tr><th>#</th><th>Category</th><th>Subject</th><th>Predicate</th><th>Object</th><th>Confidence</th><th>Source</th><th>Validated</th></tr>
    {% for k in all_knowledge %}
    <tr>
      <td>{{ k.id }}</td>
      <td>{{ k.category }}</td>
      <td><strong>{{ k.subject }}</strong></td>
      <td>{{ k.predicate }}</td>
      <td>{{ k.object }}</td>
      <td><div class="confidence"><div class="confidence-fill" style="width:{{ (k.confidence * 100)|int }}%"></div></div> {{ "%.0f"|format(k.confidence * 100) }}%</td>
      <td>{{ k.source or '-' }}</td>
      <td>{{ k.validated_by or '-' }}</td>
    </tr>
    {% endfor %}
    {% if not all_knowledge %}<tr><td colspan="8" class="muted">No knowledge yet</td></tr>{% endif %}
  </table>
</div>

<div id="tab-onboarding" class="tab-content">
  <div class="panel">
    <h2>Universal Onboarding</h2>
    <div class="form-grid">
      <div>
        <label for="onboarding-agent">Agent</label>
        <input id="onboarding-agent" list="agent-ids" value="{{ default_onboarding_agent }}">
      </div>
      <div style="display:flex; align-items:end; gap:10px;">
        <button onclick="loadOnboardingPrompt()">Load Onboarding</button>
        <button onclick="copyText(this, 'onboarding-prompt')">Copy Prompt</button>
      </div>
    </div>
    <div id="onboarding-status" class="api-status">Canonical onboarding bundle for current and future agents.</div>
    <pre id="onboarding-prompt" class="prompt-box">{{ onboarding_bundle.prompt }}</pre>
  </div>
</div>

<datalist id="agent-ids">
  {% for profile in agent_profiles %}
  <option value="{{ profile.agent_id }}">{{ profile.display_name }}</option>
  {% endfor %}
</datalist>

<script>
const INITIAL_CHAT_MESSAGES = {{ chat_messages|tojson }};
const INITIAL_CHAT_CHANNELS = {{ chat_channels|tojson }};
const CHAT_POLL_INTERVAL_MS = 3000;
const TAB_NAMES = ['overview', 'chat', 'agents', 'working', 'episodes', 'knowledge', 'onboarding'];
const chatState = {
  activeChannel: '{{ default_chat_channel|replace("'", "\\'") }}',
  channelSummaries: INITIAL_CHAT_CHANNELS,
  follow: true,
  hasOlder: INITIAL_CHAT_MESSAGES.length >= 100,
  latestId: INITIAL_CHAT_MESSAGES.length ? INITIAL_CHAT_MESSAGES[INITIAL_CHAT_MESSAGES.length - 1].id : 0,
  loadingOlder: false,
  messages: INITIAL_CHAT_MESSAGES,
  oldestId: INITIAL_CHAT_MESSAGES.length ? INITIAL_CHAT_MESSAGES[0].id : 0,
  pageSize: 100,
  pollHandle: null,
};

function getHashState() {
  const hash = window.location.hash.replace(/^#/, '').trim();
  if (!hash) {
    return { tab: 'overview', chatChannel: null };
  }
  const [rawTab, ...rest] = hash.split('/');
  const tab = rawTab.toLowerCase();
  if (!TAB_NAMES.includes(tab)) {
    return { tab: 'overview', chatChannel: null };
  }
  return {
    tab: tab,
    chatChannel: tab === 'chat' && rest.length ? decodeURIComponent(rest.join('/')) : null
  };
}

function findTabButton(name) {
  return document.querySelector(`.tab[data-tab="${name}"]`);
}

function buildHash(name) {
  if (name === 'chat' && chatState.activeChannel && chatState.activeChannel !== 'all') {
    return 'chat/' + encodeURIComponent(chatState.activeChannel);
  }
  return name;
}

function showTab(name, el, options) {
  const setHash = !options || options.setHash !== false;
  document.querySelectorAll('.tab-content').forEach(node => node.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(node => node.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  if (el) el.classList.add('active');
  if (setHash) {
    window.location.hash = buildHash(name);
  }
  if (name === 'chat') {
    refreshChatFeed({ forceScroll: true });
    refreshChatChannels();
  }
}

async function postJson(url, payload) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {})
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || ('HTTP ' + res.status));
  }
  return data;
}

function copyText(btn, id) {
  const text = document.getElementById(id).textContent;
  navigator.clipboard.writeText(text).then(() => {
    const original = btn.textContent;
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.textContent = original;
      btn.classList.remove('copied');
    }, 1600);
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function getChatFeed() {
  return document.getElementById('chat-feed');
}

function isChatTabActive() {
  const tab = document.getElementById('tab-chat');
  return tab && tab.classList.contains('active');
}

function isNearBottom(element) {
  return (element.scrollHeight - element.scrollTop - element.clientHeight) < 24;
}

function updateFollowStateLabel() {
  document.getElementById('chat-follow-state').textContent = 'Follow mode: ' + (chatState.follow ? 'on' : 'paused');
}

function setActiveChatChannel(channel, options) {
  const nextChannel = (channel || 'all').trim() || 'all';
  chatState.activeChannel = nextChannel;
  document.getElementById('chat-quick-channel').value = nextChannel === 'all' ? '' : nextChannel;
  document.getElementById('chat-channel').value = nextChannel === 'all' ? 'general' : nextChannel;
  document.getElementById('chat-active-title').textContent = nextChannel === 'all' ? '#all channels' : ('#' + nextChannel);
  resetChatStateForChannel();
  renderChatChannelTabs();
  if (!options || options.syncHash !== false) {
    window.location.hash = buildHash('chat');
  }
  if (!options || options.refresh !== false) {
    chatState.follow = true;
    updateFollowStateLabel();
    refreshChatFeed({ forceScroll: true });
  }
}

function renderChatChannelTabs() {
  const host = document.getElementById('chat-channel-tabs');
  const totalMessages = chatState.channelSummaries.reduce((sum, item) => sum + (item.message_count || 0), 0);
  const allTab = `
    <button class="chat-channel-tab ${chatState.activeChannel === 'all' ? 'active' : ''}" type="button" data-channel="all">
      <span class="chat-channel-name">#all</span>
      <span class="chat-channel-count">${totalMessages}</span>
    </button>
  `;
  const channelTabs = chatState.channelSummaries.map((item) => {
    const channel = escapeHtml(item.channel);
    const activeClass = item.channel === chatState.activeChannel ? 'active' : '';
    return `
      <button class="chat-channel-tab ${activeClass}" type="button" data-channel="${channel}">
        <span class="chat-channel-name">#${channel}</span>
        <span class="chat-channel-count">${item.message_count}</span>
      </button>
    `;
  }).join('');
  host.innerHTML = allTab + channelTabs;
}

function renderChatMessages(messages) {
  const feed = getChatFeed();
  const watchAgent = document.getElementById('chat-watch-agent').value.trim().toLowerCase();
  if (!messages.length) {
    feed.innerHTML = '<div class="muted">No chat messages yet.</div>';
    return;
  }

  feed.innerHTML = messages.map((msg) => {
    const sender = escapeHtml(msg.sender_agent);
    const target = escapeHtml(msg.target_agent || '*');
    const body = escapeHtml(msg.body);
    const channel = escapeHtml(msg.channel);
    const created = escapeHtml(msg.created_at);
    const isSelf = watchAgent && sender.toLowerCase() === watchAgent;
    const cardClass = isSelf ? 'chat-message self' : 'chat-message remote';
    const channelMeta = chatState.activeChannel === 'all'
      ? `<button type="button" class="chat-channel-chip" data-channel="${channel}">${channel}</button>`
      : `<span>${channel}</span>`;
    return `
      <article class="${cardClass}" data-message-id="${msg.id}">
        <div class="chat-meta">
          <strong class="agent">${sender}</strong>
          <span class="chat-target">to ${target}</span>
          <span>#${msg.id}</span>
          ${channelMeta}
          <span>${created}</span>
        </div>
        <div class="chat-text">${body}</div>
      </article>
    `;
  }).join('');
}

function updateChatCursorState(messages) {
  chatState.messages = messages;
  chatState.latestId = messages.length ? messages[messages.length - 1].id : 0;
  chatState.oldestId = messages.length ? messages[0].id : 0;
}

function bindChatChannelClicks() {
  document.getElementById('chat-channel-tabs').addEventListener('click', (event) => {
    const target = event.target.closest('[data-channel]');
    if (!target) {
      return;
    }
    setActiveChatChannel(target.dataset.channel || 'all');
  });

  getChatFeed().addEventListener('click', (event) => {
    const target = event.target.closest('.chat-channel-chip[data-channel]');
    if (!target) {
      return;
    }
    setActiveChatChannel(target.dataset.channel || 'all');
  });
}

function resetChatStateForChannel() {
  chatState.messages = [];
  chatState.latestId = 0;
  chatState.oldestId = 0;
  chatState.hasOlder = true;
  chatState.loadingOlder = false;
  const feed = getChatFeed();
  delete feed.dataset.initialized;
}

async function fetchChatMessages(params) {
  const query = new URLSearchParams();
  query.set('limit', String(params && params.limit ? params.limit : chatState.pageSize));
  const channel = chatState.activeChannel || 'all';
  if (channel && channel.toLowerCase() !== 'all') {
    query.set('channel', channel);
  }
  if (params && params.since) {
    query.set('since', String(params.since));
  }
  if (params && params.before) {
    query.set('before', String(params.before));
  }
  const res = await fetch('/api/chat?' + query.toString());
  const payload = await res.json();
  if (!res.ok) {
    throw new Error(payload.error || ('HTTP ' + res.status));
  }
  return payload;
}

async function refreshChatChannels() {
  try {
    const res = await fetch('/api/chat/channels?limit=30');
    const payload = await res.json();
    if (!res.ok) throw new Error(payload.error || ('HTTP ' + res.status));
    chatState.channelSummaries = payload;
    renderChatChannelTabs();
  } catch (_err) {
    renderChatChannelTabs();
  }
}

async function refreshChatFeed(options) {
  const forceScroll = options && options.forceScroll;
  const feed = getChatFeed();
  const status = document.getElementById('chat-feed-status');
  const previousScrollBottomOffset = feed.scrollHeight - feed.scrollTop;
  const wasNearBottom = forceScroll || isNearBottom(feed) || feed.dataset.initialized !== 'true';
  const channel = chatState.activeChannel || 'all';

  try {
    const messages = await fetchChatMessages({ limit: chatState.pageSize });
    updateChatCursorState(messages);
    chatState.hasOlder = messages.length >= chatState.pageSize;
    renderChatMessages(chatState.messages);
    feed.dataset.initialized = 'true';
    if (chatState.follow && wasNearBottom) {
      feed.scrollTop = feed.scrollHeight;
    } else if (!chatState.follow) {
      feed.scrollTop = Math.max(0, feed.scrollHeight - previousScrollBottomOffset);
    }
    status.textContent = `Watching ${channel && channel.toLowerCase() !== 'all' ? ('channel ' + channel) : 'all channels'} | ${chatState.messages.length} message(s) loaded.`;
  } catch (err) {
    status.textContent = 'Chat refresh failed: ' + err.message;
  }
}

async function loadOlderChatMessages() {
  if (chatState.loadingOlder || !chatState.hasOlder || !chatState.oldestId) {
    return;
  }
  const feed = getChatFeed();
  const previousHeight = feed.scrollHeight;
  const previousTop = feed.scrollTop;
  chatState.loadingOlder = true;
  try {
    const older = await fetchChatMessages({ before: chatState.oldestId, limit: chatState.pageSize });
    if (!older.length) {
      chatState.hasOlder = false;
      return;
    }
    updateChatCursorState(older.concat(chatState.messages));
    chatState.hasOlder = older.length >= chatState.pageSize;
    renderChatMessages(chatState.messages);
    feed.scrollTop = feed.scrollHeight - previousHeight + previousTop;
  } finally {
    chatState.loadingOlder = false;
  }
}

async function refreshLatestChatMessages() {
  const feed = getChatFeed();
  const status = document.getElementById('chat-feed-status');
  const channel = chatState.activeChannel || 'all';
  const previousScrollBottomOffset = feed.scrollHeight - feed.scrollTop;
  const wasNearBottom = isNearBottom(feed) || feed.dataset.initialized !== 'true';
  try {
    const newer = await fetchChatMessages({ since: chatState.latestId, limit: chatState.pageSize });
    if (newer.length) {
      updateChatCursorState(chatState.messages.concat(newer));
      renderChatMessages(chatState.messages);
    }
    feed.dataset.initialized = 'true';
    if (chatState.follow && wasNearBottom) {
      feed.scrollTop = feed.scrollHeight;
    } else if (!chatState.follow) {
      feed.scrollTop = Math.max(0, feed.scrollHeight - previousScrollBottomOffset);
    }
    status.textContent = `Watching ${channel && channel.toLowerCase() !== 'all' ? ('channel ' + channel) : 'all channels'} | ${chatState.messages.length} message(s) loaded.`;
  } catch (err) {
    status.textContent = 'Chat refresh failed: ' + err.message;
  }
}

function onChatFeedScroll() {
  const feed = getChatFeed();
  chatState.follow = isNearBottom(feed);
  updateFollowStateLabel();
  if (feed.scrollTop < 24) {
    loadOlderChatMessages();
  }
}

function startChatPolling() {
  if (chatState.pollHandle) {
    clearInterval(chatState.pollHandle);
  }
  chatState.pollHandle = setInterval(() => {
    if (!document.hidden && isChatTabActive()) {
      refreshLatestChatMessages();
    }
  }, CHAT_POLL_INTERVAL_MS);
}

async function sendChatMessage() {
  const sender = document.getElementById('chat-sender').value.trim();
  const target = document.getElementById('chat-target').value.trim();
  const channel = document.getElementById('chat-channel').value.trim() || (chatState.activeChannel !== 'all' ? chatState.activeChannel : 'general');
  const body = document.getElementById('chat-body').value.trim();
  const status = document.getElementById('chat-status');
  if (!sender || !body) {
    status.textContent = 'Sender and message are required.';
    return;
  }
  status.textContent = 'Sending...';
  try {
    await postJson('/api/chat', {
      sender_agent: sender,
      target_agent: target || null,
      channel: channel,
      body: body
    });
    status.textContent = 'Message stored.';
    document.getElementById('chat-body').value = '';
    setActiveChatChannel(channel, { refresh: false });
    chatState.follow = true;
    updateFollowStateLabel();
    await Promise.all([
      refreshChatChannels(),
      refreshChatFeed({ forceScroll: true })
    ]);
  } catch (err) {
    status.textContent = err.message;
  }
}

function jumpToChatChannel() {
  const value = document.getElementById('chat-quick-channel').value.trim() || 'all';
  setActiveChatChannel(value);
}

function syncTabFromHash() {
  const hashState = getHashState();
  if (hashState.tab === 'chat' && hashState.chatChannel) {
    setActiveChatChannel(hashState.chatChannel, { refresh: false, syncHash: false });
  }
  showTab(hashState.tab, findTabButton(hashState.tab), { setHash: false });
}

async function loadOnboardingPrompt() {
  const agent = document.getElementById('onboarding-agent').value.trim() || 'agent';
  const status = document.getElementById('onboarding-status');
  status.textContent = 'Loading...';
  try {
    const res = await fetch('/api/onboarding/' + encodeURIComponent(agent));
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
    document.getElementById('onboarding-prompt').textContent = data.prompt;
    status.textContent = 'Loaded canonical onboarding for ' + data.profile.agent_id + '.';
  } catch (err) {
    status.textContent = err.message;
  }
}

document.getElementById('chat-watch-agent').addEventListener('change', () => {
  renderChatMessages(chatState.messages);
});
getChatFeed().addEventListener('scroll', onChatFeedScroll);
window.addEventListener('hashchange', syncTabFromHash);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && isChatTabActive()) {
    refreshLatestChatMessages();
  }
});

renderChatChannelTabs();
renderChatMessages(chatState.messages);
bindChatChannelClicks();
refreshChatChannels();
refreshChatFeed({ forceScroll: true });
startChatPolling();
updateFollowStateLabel();
syncTabFromHash();
</script>
</body></html>
"""


@app.route("/")
def dashboard():
    # Gather working memory for all active sessions
    wm_by_agent = {}
    sessions = mem.list_sessions(limit=50)
    active_sessions = [s for s in sessions if not s.get("ended_at")]
    for s in active_sessions:
        wm_data = mem.wm_get_all(s["agent_id"], s["id"])
        wm_by_agent[s["agent_id"]] = type("WM", (), {
            "session_id": s["id"],
            "items": wm_data,
        })()

    # Parse tags for episodes
    all_episodes = mem.search_episodes(limit=50)
    for ep in all_episodes:
        ep["tags_list"] = []
        if ep.get("tags"):
            try:
                t = json.loads(ep["tags"]) if isinstance(ep["tags"], str) else ep["tags"]
                ep["tags_list"] = t if isinstance(t, list) else []
            except (json.JSONDecodeError, TypeError):
                pass

    all_knowledge = mem.recall(limit=100)
    pinned_notes = [k for k in all_knowledge if k.get("category") == "pinned"]
    agent_profiles = mem.list_agent_profiles()
    default_onboarding_agent = request.args.get("agent_id") or (
        agent_profiles[0]["agent_id"] if agent_profiles else "codex"
    )
    default_chat_channel = request.args.get("chat_channel", "all")
    onboarding_bundle = mem.get_onboarding_bundle(default_onboarding_agent)

    return render_template_string(
        DASHBOARD_HTML,
        stats=mem.stats(),
        states=mem.get_all_states(),
        tasks=mem.list_tasks(include_done=False, limit=20),
        events=mem.get_latest_events(limit=30),
        chat_messages=mem.get_chat_messages(limit=50),
        chat_channels=mem.list_chat_channels(limit=20),
        agent_profiles=agent_profiles,
        sessions=sessions[:20],
        wm_by_agent=wm_by_agent,
        all_episodes=all_episodes,
        all_knowledge=all_knowledge,
        pinned_notes=pinned_notes,
        default_onboarding_agent=default_onboarding_agent,
        default_chat_channel=default_chat_channel,
        onboarding_bundle=onboarding_bundle,
    )


# ── API: Status ──────────────────────────────────────────────

# -- API: Agent Registry --------------------------------------------------

@app.route("/api/agents", methods=["GET"])
def api_agents_list():
    return jsonify(mem.list_agent_profiles())


@app.route("/api/agents/<agent_id>", methods=["GET"])
def api_agents_get(agent_id):
    return jsonify(mem.get_agent_profile(agent_id))


@app.route("/api/agents/<agent_id>", methods=["POST"])
def api_agents_upsert(agent_id):
    data = request.get_json(force=True) if request.data else {}
    profile = mem.upsert_agent_profile(
        agent_id,
        display_name=data.get("display_name"),
        integration_mode=data.get("integration_mode"),
        integration_target=data.get("integration_target"),
        native_feature=data.get("native_feature"),
        onboarding_note=data.get("onboarding_note"),
        metadata=data.get("metadata"),
    )
    return jsonify({"ok": True, "profile": profile})


# -- API: Canonical Onboarding -------------------------------------------

@app.route("/api/onboarding", methods=["GET"])
@app.route("/api/onboarding/<agent_id>", methods=["GET"])
def api_onboarding(agent_id=None):
    return jsonify(mem.get_onboarding_bundle(agent_id or request.args.get("agent_id")))


# -- API: Agent Chat ------------------------------------------------------

@app.route("/api/chat", methods=["GET"])
def api_chat_list():
    since = request.args.get("since", "0")
    before = request.args.get("before", "0")
    try:
        since_id = int(since)
    except ValueError:
        since_id = 0
    try:
        before_id = int(before)
    except ValueError:
        before_id = 0
    return jsonify(mem.get_chat_messages(
        channel=request.args.get("channel"),
        agent_id=request.args.get("agent_id"),
        since_id=since_id,
        before_id=before_id,
        limit=_parse_int_arg("limit", 100),
    ))


@app.route("/api/chat/channels", methods=["GET"])
def api_chat_channels():
    return jsonify(mem.list_chat_channels(limit=_parse_int_arg("limit", 30)))


@app.route("/api/chat", methods=["POST"])
def api_chat_create():
    data = request.get_json(force=True)
    if not data.get("sender_agent") or not data.get("body"):
        return jsonify({"error": "sender_agent and body required"}), 400
    message_id = mem.append_chat_message(
        sender_agent=data["sender_agent"],
        body=data["body"],
        channel=data.get("channel", "general"),
        target_agent=data.get("target_agent"),
        metadata=data.get("metadata"),
    )
    return jsonify({"ok": True, "id": message_id})


@app.route("/api/status")
def api_status():
    return jsonify({"ok": True, **mem.stats()})


# ── API: Agent State ─────────────────────────────────────────

@app.route("/api/state")
def api_state_all():
    return jsonify(mem.get_all_states())


@app.route("/api/state/<agent_id>", methods=["GET"])
def api_state_get(agent_id):
    state = mem.get_state(agent_id)
    if not state:
        return jsonify({"error": f"Agent '{agent_id}' not found"}), 404
    return jsonify(state)


@app.route("/api/state/<agent_id>", methods=["POST"])
def api_state_update(agent_id):
    data = request.get_json(force=True)
    mem.update_state(
        agent_id,
        status=data.get("status", "idle"),
        current_task=data.get("current_task"),
        context=data.get("context"),
    )
    return jsonify({"ok": True})


# ── API: Tasks ───────────────────────────────────────────────

@app.route("/api/tasks", methods=["GET"])
def api_tasks_list():
    return jsonify(mem.list_tasks(
        status=request.args.get("status"),
        assigned_to=request.args.get("assigned_to"),
        include_done=request.args.get("all", "").lower() in ("1", "true", "yes"),
        limit=_parse_int_arg("limit", 50),
    ))


@app.route("/api/tasks", methods=["POST"])
def api_tasks_create():
    data = request.get_json(force=True)
    if not data.get("title") or not data.get("created_by"):
        return jsonify({"error": "title and created_by required"}), 400
    task_id = mem.create_task(
        title=data["title"],
        created_by=data["created_by"],
        description=data.get("description"),
        assigned_to=data.get("assigned_to"),
        priority=data.get("priority", 0),
        payload=data.get("payload"),
    )
    return jsonify({"ok": True, "id": task_id})


@app.route("/api/tasks/<int:task_id>/claim", methods=["POST"])
def api_tasks_claim(task_id):
    data = request.get_json(force=True)
    agent = data.get("agent")
    if not agent:
        return jsonify({"error": "agent required"}), 400
    try:
        task = mem.claim_task(agent, task_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if not task:
        return jsonify({"error": "Task not available"}), 409
    return jsonify({"ok": True, "task": task})


@app.route("/api/tasks/<int:task_id>/complete", methods=["POST"])
def api_tasks_complete(task_id):
    data = request.get_json(force=True) if request.data else {}
    mem.complete_task(task_id, result=data.get("result"))
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:task_id>/fail", methods=["POST"])
def api_tasks_fail(task_id):
    data = request.get_json(force=True) if request.data else {}
    mem.fail_task(task_id, error=data.get("error"))
    return jsonify({"ok": True})


# ── API: Events ──────────────────────────────────────────────

def _parse_since(value):
    """Parse 'since' param: integer (event ID) or duration like 24h, 7d, 1w."""
    if not value:
        return 0, None
    m = re.fullmatch(r"(\d+)\s*([hdwm])", value.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"h": timedelta(hours=n), "d": timedelta(days=n),
                 "w": timedelta(weeks=n), "m": timedelta(days=n * 30)}[unit]
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - delta
        return 0, cutoff.strftime("%Y-%m-%d %H:%M:%S")
    try:
        return int(value), None
    except ValueError:
        return 0, None


def _parse_int_arg(name, default):
    """Parse an integer query arg and fall back to default on invalid input."""
    value = request.args.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@app.route("/api/events", methods=["GET"])
def api_events_list():
    since_id, since_time = _parse_since(request.args.get("since"))
    return jsonify(mem.get_events(
        since_id=since_id,
        since_time=since_time,
        event_type=request.args.get("type"),
        source_agent=request.args.get("source"),
        target_agent=request.args.get("target"),
        limit=_parse_int_arg("limit", 100),
    ))


@app.route("/api/events", methods=["POST"])
def api_events_append():
    data = request.get_json(force=True)
    if not data.get("event_type") or not data.get("source_agent"):
        return jsonify({"error": "event_type and source_agent required"}), 400
    event_id = mem.append_event(
        event_type=data["event_type"],
        source_agent=data["source_agent"],
        target_agent=data.get("target_agent"),
        data=data.get("data"),
    )
    return jsonify({"ok": True, "id": event_id})


# ── API: Handoff ─────────────────────────────────────────────

@app.route("/api/handoff", methods=["POST"])
def api_handoff():
    data = request.get_json(force=True)
    required = ["from_agent", "to_agent", "title"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} required"}), 400
    task_id = mem.handoff(
        from_agent=data["from_agent"],
        to_agent=data["to_agent"],
        title=data["title"],
        description=data.get("description"),
        payload=data.get("payload"),
    )
    return jsonify({"ok": True, "task_id": task_id})


# ── API: Sessions ────────────────────────────────────────────

@app.route("/api/sessions", methods=["POST"])
def api_sessions_start():
    data = request.get_json(force=True)
    agent_id = data.get("agent_id")
    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400
    session_id = mem.begin_session(agent_id)
    return jsonify({"ok": True, "session_id": session_id})


@app.route("/api/sessions", methods=["GET"])
def api_sessions_list():
    return jsonify(mem.list_sessions(
        agent_id=request.args.get("agent_id"),
        limit=_parse_int_arg("limit", 20),
    ))


@app.route("/api/sessions/<session_id>/end", methods=["POST"])
def api_sessions_end(session_id):
    data = request.get_json(force=True)
    agent_id = data.get("agent_id")
    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400
    episode_id = mem.end_session(
        agent_id, session_id,
        title=data.get("title"),
        outcome=data.get("outcome"),
        lessons=data.get("lessons"),
    )
    if episode_id is None:
        return jsonify({"error": "Session not found"}), 404
    return jsonify({"ok": True, "episode_id": episode_id})


# ── API: Working Memory ──────────────────────────────────────

@app.route("/api/wm/<agent_id>", methods=["GET"])
def api_wm_get(agent_id):
    session_id = request.args.get("session_id")
    if not session_id:
        session = mem.get_active_session(agent_id)
        if not session:
            return jsonify({"error": "No active session"}), 404
        session_id = session["id"]
    return jsonify({"session_id": session_id, "data": mem.wm_get_all(agent_id, session_id)})


@app.route("/api/wm/<agent_id>", methods=["POST"])
def api_wm_set(agent_id):
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    if not session_id:
        session = mem.get_active_session(agent_id)
        if not session:
            return jsonify({"error": "No active session"}), 404
        session_id = session["id"]
    key = data.get("key")
    value = data.get("value")
    if not key:
        return jsonify({"error": "key required"}), 400
    mem.wm_set(agent_id, session_id, key, value, ttl_minutes=data.get("ttl_minutes"))
    return jsonify({"ok": True})


@app.route("/api/wm/<agent_id>/<key>", methods=["DELETE"])
def api_wm_delete(agent_id, key):
    session_id = request.args.get("session_id")
    if not session_id:
        session = mem.get_active_session(agent_id)
        if not session:
            return jsonify({"error": "No active session"}), 404
        session_id = session["id"]
    mem.wm_delete(agent_id, session_id, key)
    return jsonify({"ok": True})


# ── API: Episodes ────────────────────────────────────────────

@app.route("/api/episodes", methods=["GET"])
def api_episodes_list():
    return jsonify(mem.search_episodes(
        agent_id=request.args.get("agent_id"),
        category=request.args.get("category"),
        outcome=request.args.get("outcome"),
        tag=request.args.get("tag"),
        query=request.args.get("q"),
        limit=_parse_int_arg("limit", 20),
    ))


@app.route("/api/episodes", methods=["POST"])
def api_episodes_create():
    data = request.get_json(force=True)
    if not data.get("agent_id") or not data.get("title"):
        return jsonify({"error": "agent_id and title required"}), 400
    episode_id = mem.create_episode(
        agent_id=data["agent_id"],
        title=data["title"],
        category=data.get("category", "general"),
        tags=data.get("tags"),
        description=data.get("description"),
        session_id=data.get("session_id"),
    )
    return jsonify({"ok": True, "id": episode_id})


@app.route("/api/episodes/<int:episode_id>", methods=["GET"])
def api_episodes_get(episode_id):
    ep = mem.get_episode(episode_id)
    if not ep:
        return jsonify({"error": "Episode not found"}), 404
    return jsonify(ep)


@app.route("/api/episodes/<int:episode_id>/complete", methods=["POST"])
def api_episodes_complete(episode_id):
    data = request.get_json(force=True)
    outcome = data.get("outcome")
    if not outcome:
        return jsonify({"error": "outcome required"}), 400
    mem.complete_episode(episode_id, outcome, lessons=data.get("lessons"))
    return jsonify({"ok": True})


@app.route("/api/episodes/<int:episode_id>/link", methods=["POST"])
def api_episodes_link(episode_id):
    data = request.get_json(force=True)
    event_id = data.get("event_id")
    if not event_id:
        return jsonify({"error": "event_id required"}), 400
    mem.link_event_to_episode(episode_id, event_id)
    return jsonify({"ok": True})


@app.route("/api/episodes/<int:episode_id>/promote", methods=["POST"])
def api_episodes_promote(episode_id):
    ids = mem.promote_lesson(episode_id)
    return jsonify({"ok": True, "knowledge_ids": ids})


# ── API: Knowledge ───────────────────────────────────────────

@app.route("/api/knowledge", methods=["GET"])
def api_knowledge_list():
    return jsonify(mem.recall(
        subject=request.args.get("subject"),
        predicate=request.args.get("predicate"),
        category=request.args.get("category"),
        tag=request.args.get("tag"),
        query=request.args.get("q"),
        limit=_parse_int_arg("limit", 50),
    ))


@app.route("/api/knowledge", methods=["POST"])
def api_knowledge_create():
    data = request.get_json(force=True)
    for field in ("subject", "predicate", "object"):
        if not data.get(field):
            return jsonify({"error": f"{field} required"}), 400
    kwargs = dict(
        subject=data["subject"],
        predicate=data["predicate"],
        object=data["object"],
        category=data.get("category", "fact"),
        source=data.get("source"),
        confidence=data.get("confidence", 1.0),
        tags=data.get("tags"),
        source_episode_id=data.get("source_episode_id"),
    )
    if data.get("update", False):
        kid = mem.learn_or_update(**kwargs)
    else:
        kid = mem.learn(**kwargs)
    return jsonify({"ok": True, "id": kid})


@app.route("/api/knowledge/<int:kid>/validate", methods=["POST"])
def api_knowledge_validate(kid):
    data = request.get_json(force=True)
    validated_by = data.get("validated_by")
    if not validated_by:
        return jsonify({"error": "validated_by required"}), 400
    mem.validate_knowledge(kid, validated_by)
    return jsonify({"ok": True})


@app.route("/api/knowledge/<int:kid>/forget", methods=["POST"])
def api_knowledge_forget(kid):
    mem.forget(kid)
    return jsonify({"ok": True})


# ── API: Maintenance ─────────────────────────────────────────

@app.route("/api/maintenance", methods=["POST"])
def api_maintenance():
    cleaned_wm = mem.cleanup_expired_wm()
    cleaned_tasks = mem.cleanup_done_tasks(days=7)
    decayed = mem.decay_knowledge(days_threshold=30, decay_rate=0.05)
    return jsonify({
        "ok": True,
        "cleaned_wm": cleaned_wm,
        "cleaned_tasks": cleaned_tasks,
        "decayed_knowledge": decayed,
    })


# ── API: Cross-Tier Context ─────────────────────────────────

@app.route("/api/context/<topic>")
def api_context(topic):
    if topic == "onboarding":
        return jsonify(mem.onboarding_context(agent_id=request.args.get("agent_id")))
    return jsonify(mem.context_for(topic))


# ── Daemon Lifecycle ─────────────────────────────────────────

def write_pid():
    PID_FILE.write_text(str(os.getpid()))


def remove_pid(*_):
    PID_FILE.unlink(missing_ok=True)
    sys.exit(0)


if __name__ == "__main__":
    if not DOCKER:
        write_pid()
    signal.signal(signal.SIGTERM, remove_pid)
    signal.signal(signal.SIGINT, remove_pid)

    host = "0.0.0.0" if DOCKER else "127.0.0.1"

    log.info("Agent Memory daemon starting on %s:%d", host, PORT)
    log.info("Dashboard: http://localhost:%d", PORT)
    if not DOCKER:
        log.info("PID file: %s", PID_FILE)
    log.info("Database: %s", mem.db_path)

    # Auto-cleanup on startup
    cleaned_tasks = mem.cleanup_done_tasks(days=7)
    cleaned_wm = mem.cleanup_expired_wm()
    decayed = mem.decay_knowledge(days_threshold=30, decay_rate=0.05)
    if cleaned_tasks:
        log.info("Cleaned up %d old done/failed tasks", cleaned_tasks)
    if cleaned_wm:
        log.info("Cleaned up %d expired working memory entries", cleaned_wm)
    if decayed:
        log.info("Decayed confidence of %d unvalidated knowledge entries", decayed)

    try:
        from waitress import serve
        serve(app, host=host, port=PORT, threads=2, _quiet=True)
    except ImportError:
        log.warning("waitress not found, using Flask dev server")
        app.run(host=host, port=PORT, debug=False)
    finally:
        if not DOCKER:
            remove_pid()
