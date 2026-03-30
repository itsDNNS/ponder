#!/usr/bin/env python3
"""Ponder Daemon -- REST API for shared agent state.

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
<title>Ponder</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700;800;900&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Figtree', sans-serif;
    background: #f5f3ef;
    color: #1a1a1a;
    min-height: 100vh;
  }

  .page { max-width: 1100px; margin: 0 auto; padding: 16px 32px; }

  /* === HERO === */
  .hero {
    position: relative;
    margin-bottom: 0;
    padding: 16px 0 0;
  }
  .hero-mark {
    position: absolute;
    top: 16px; right: 0;
    pointer-events: none;
    user-select: none;
    z-index: 0;
    color: rgba(0,0,0,0.06);
  }
  .hero-mark svg { width: 140px; height: 158px; }
  .hero-content { position: relative; z-index: 1; }
  .hero-label { display: none; }
  .hero-title {
    font-size: 52px;
    font-weight: 900;
    letter-spacing: -2px;
    line-height: 1.05;
    margin-bottom: 20px;
  }
  .hero-title .count {
    display: inline-block;
    position: relative;
  }
  .hero-title .count::after {
    content: '';
    position: absolute;
    bottom: 6px; left: 0; right: 0;
    height: 12px;
    background: #c45a3c;
    opacity: 0.15;
    border-radius: 2px;
    z-index: -1;
  }

  .hero-agents {
    display: flex;
    gap: 24px;
    margin: 24px 0 12px;
    flex-wrap: wrap;
  }
  .hero-agent {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .hero-agent-ring {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 2px solid #1a1a1a;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    font-weight: 600;
    position: relative;
  }
  .hero-agent-ring.active::after {
    content: '';
    position: absolute;
    bottom: -1px; right: -1px;
    width: 10px; height: 10px;
    border-radius: 50%;
    background: #2ecc71;
    border: 2px solid #f5f3ef;
  }
  .hero-agent-ring.idle { border-color: #d0ccc4; color: #bbb; }
  .hero-agent-info { font-size: 13px; }
  .hero-agent-name {
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    font-size: 12px;
  }
  .hero-agent-name.idle { color: #bbb; }
  .hero-agent-task { color: #888; font-size: 12px; }

  /* === TABS === */
  .tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 36px;
    background: #eae7e0;
    padding: 4px;
    border-radius: 8px;
    width: fit-content;
  }
  .tab {
    font-size: 13px;
    font-weight: 500;
    padding: 8px 18px;
    color: #888;
    cursor: pointer;
    border-radius: 6px;
    transition: all 0.15s;
  }
  .tab:hover { color: #1a1a1a; }
  .tab.active {
    color: #1a1a1a;
    background: #fff;
    font-weight: 600;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }

  /* === TAB CONTENT === */
  .tab-content { display: none; }
  .tab-content.active { display: block; }

  /* === SECTIONS === */
  .section { margin-bottom: 40px; }
  .section-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 14px;
  }
  .section-title {
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #aaa;
  }
  .section-link {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #c45a3c;
    text-decoration: none;
    cursor: pointer;
  }
  .section-link:hover { text-decoration: underline; }

  /* === HEADINGS === */
  h2 { color: #1a1a1a; border-bottom: 1px solid #e0ddd6; padding-bottom: 4px; margin-top: 1.4em; font-size: 16px; }
  h3 { color: #c45a3c; margin: 1em 0 0.5em 0; font-size: 14px; }

  /* === TASKS === */
  .task {
    background: #fff;
    border: 1px solid #e0ddd6;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 8px;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 12px;
    align-items: center;
    transition: border-color 0.12s, box-shadow 0.12s;
    cursor: pointer;
  }
  .task:hover {
    border-color: #c4c0b8;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  }
  .task.done { opacity: 0.45; }
  .task-row { display: flex; align-items: center; gap: 10px; }
  .task-num {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #ccc;
  }
  .task-title { font-size: 14px; font-weight: 600; }
  .task-sub {
    font-size: 12px;
    color: #999;
    margin-top: 3px;
    padding-left: 36px;
  }
  .task-sub strong { color: #c45a3c; font-weight: 500; }

  /* === PILLS === */
  .pill {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    padding: 4px 10px;
    border-radius: 5px;
    font-weight: 500;
  }
  .pill-active, .pill-in_progress { background: #e6f5ec; color: #1a6b3a; }
  .pill-pending { background: #fef4e0; color: #8a6d2b; }
  .pill-done, .pill-completed { background: #eae7e0; color: #aaa; }
  .pill-success { background: #e6f5ec; color: #1a6b3a; }
  .pill-failed, .pill-failure { background: #fde8e8; color: #b33a3a; }

  /* === TIMELINE === */
  .tl-item {
    display: grid;
    grid-template-columns: 40px 80px 1fr;
    gap: 8px;
    padding: 10px 0;
    font-size: 13px;
    border-bottom: 1px solid #eae7e0;
    align-items: baseline;
  }
  .tl-item:last-child { border-bottom: none; }
  .tl-time {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #ccc;
  }
  .tl-who {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    font-weight: 600;
  }
  .tl-text { color: #777; }
  .tl-text strong { color: #1a1a1a; font-weight: 500; }

  /* === CHAT FULL VIEW === */
  .chat-shell { display: grid; grid-template-columns: minmax(220px, 280px) minmax(0, 1fr); gap: 16px; align-items: start; }
  .chat-sidebar { position: sticky; top: 1em; }
  .chat-main { min-width: 0; }
  .chat-sidebar h2, .chat-main h2 { margin-top: 0; }
  .chat-channel-tabs { display: flex; flex-direction: column; gap: 8px; margin: 12px 0 16px 0; }
  .chat-channel-tab {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    width: 100%;
    padding: 10px 12px;
    border: 1px solid #e0ddd6;
    border-radius: 8px;
    background: #fff;
    color: #1a1a1a;
    cursor: pointer;
    text-align: left;
  }
  .chat-channel-tab:hover { border-color: #c4c0b8; background: #faf8f5; }
  .chat-channel-tab.active { border-color: #c45a3c; background: #fdf9f7; }
  .chat-channel-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chat-channel-count { font-size: 0.82em; color: #999; }
  .chat-feed {
    background: #fff;
    border: 1px solid #e0ddd6;
    border-radius: 8px;
    max-height: 58vh;
    overflow-y: auto;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .chat-toolbar {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 10px;
    margin-bottom: 12px;
  }
  .chat-header-row { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }

  /* === MESSAGES === */
  .msg {
    padding: 12px 0;
    border-bottom: 1px solid #eae7e0;
  }
  .msg:last-child { border-bottom: none; }
  .msg.self .msg-body { color: #444; }
  .msg-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 5px;
  }
  .msg-from {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    font-weight: 600;
  }
  .msg-arrow { color: #ccc; font-size: 10px; }
  .msg-to {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: #999;
  }
  .msg-time {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    color: #ccc;
    margin-left: auto;
  }
  .msg-body { font-size: 13px; color: #555; line-height: 1.55; }

  /* === CHAT MESSAGE CARDS (feed) === */
  .chat-message { border: 1px solid #e0ddd6; border-radius: 8px; padding: 10px 12px; background: #fff; }
  .chat-message.self { border-color: #c4c0b8; background: #faf8f5; }
  .chat-message.remote { border-color: #e0ddd6; background: #fff; }
  .chat-meta { display: flex; gap: 12px; flex-wrap: wrap; color: #999; font-size: 0.9em; margin-bottom: 6px; }
  .chat-channel-chip { border: 1px solid #e0ddd6; border-radius: 999px; background: #faf8f5; color: #999; padding: 2px 8px; cursor: pointer; }
  .chat-channel-chip:hover { color: #1a1a1a; border-color: #c4c0b8; }
  .chat-text { white-space: pre-wrap; word-break: break-word; line-height: 1.45; }

  /* === CHAT STATUS === */
  .chat-status-row { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin: 10px 0 6px 0; flex-wrap: wrap; }
  .chat-follow { color: #999; font-size: 0.9em; }
  .chat-body { min-width: 360px; }
  .chat-target { color: #c45a3c; }
  .api-status { margin-top: 0.6em; color: #999; }

  /* === CHAT PREVIEW === */
  .chat-preview {
    background: #fff;
    border: 1px solid #e0ddd6;
    border-radius: 10px;
    overflow: hidden;
  }
  .chat-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 20px;
    border-bottom: 1px solid #eae7e0;
  }
  .chat-channel {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
    font-weight: 600;
  }
  .chat-channel-list {
    display: flex;
    gap: 12px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #bbb;
  }
  .chat-channel-list span.active { color: #c45a3c; font-weight: 500; }
  .chat-channel-list span:hover { color: #888; cursor: pointer; }
  .chat-messages { padding: 16px 20px; }

  /* === FORM ELEMENTS === */
  input, textarea, button, select { font: inherit; }
  input, textarea, select {
    width: 100%;
    background: #fff;
    color: #1a1a1a;
    border: 1px solid #e0ddd6;
    border-radius: 6px;
    padding: 8px 10px;
  }
  input:focus, textarea:focus, select:focus {
    outline: none;
    border-color: #c45a3c;
    box-shadow: 0 0 0 2px rgba(196,90,60,0.12);
  }
  textarea { min-height: 100px; resize: vertical; }
  label { font-size: 12px; font-weight: 600; color: #888; display: block; margin-bottom: 4px; }
  button {
    background: #c45a3c;
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    cursor: pointer;
    font-weight: 600;
  }
  button:hover { background: #a94a30; }

  /* === AGENT CARDS === */
  .agent-card {
    background: #fff;
    border: 1px solid #e0ddd6;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 8px;
  }
  .agent-card-name {
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    font-size: 13px;
  }
  .agent-card-meta { font-size: 12px; color: #999; margin-top: 4px; }

  /* === KNOWLEDGE === */
  .confidence { display: inline-block; background: #eae7e0; border-radius: 4px; width: 60px; height: 8px; overflow: hidden; vertical-align: middle; }
  .confidence-fill { height: 100%; background: #2ecc71; }

  /* === SYSTEM TAB === */
  .panel { background: #fff; border: 1px solid #e0ddd6; border-radius: 8px; padding: 16px 18px; margin-bottom: 1em; }
  .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-bottom: 10px; }
  .muted { color: #999; }
  .tag { display: inline-block; background: #eae7e0; color: #888; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; margin: 1px; }
  .wm-key { font-family: 'IBM Plex Mono', monospace; color: #c45a3c; }
  .copy-btn {
    position: absolute;
    top: 12px; right: 12px;
    background: #c45a3c;
    color: #fff;
    border: none;
    padding: 6px 14px;
    border-radius: 4px;
    cursor: pointer;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.85em;
  }
  .copy-btn.copied { background: #2ecc71; color: #fff; }
  .prompt-box, pre {
    background: #faf8f5;
    border: 1px solid #eae7e0;
    padding: 10px 12px;
    border-radius: 6px;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
  }

  /* === TABLES === */
  table { border-collapse: collapse; width: 100%; margin-bottom: 2em; }
  th, td { text-align: left; padding: 6px 12px; border-bottom: 1px solid #eae7e0; vertical-align: top; font-size: 13px; }
  th { color: #aaa; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }

  /* === STATUS COLORS === */
  .status-idle { color: #999; }
  .status-active, .status-working { color: #1a6b3a; }
  .status-waiting { color: #8a6d2b; }
  .session-active { color: #1a6b3a; }
  .session-ended { color: #999; }
  .event-type { font-family: 'IBM Plex Mono', monospace; color: #c45a3c; font-size: 12px; }
  .agent { font-family: 'IBM Plex Mono', monospace; color: #1a1a1a; font-weight: 500; font-size: 12px; }
  .pending { color: #8a6d2b; }
  .claimed { color: #1a6b3a; }
  .done, .success { color: #1a6b3a; }
  .failed, .failure { color: #b33a3a; }

  /* === PINNED === */
  .pinned { border: 1px solid #c45a3c; border-radius: 8px; padding: 16px 20px; margin-bottom: 1em; background: #fdf9f7; position: relative; }
  .pinned h3 { color: #c45a3c; margin: 0 0 8px 0; font-size: 1.05em; }

  /* === RESPONSIVE === */
  @media (max-width: 760px) {
    .page { padding: 12px 16px; }
    .hero-title { font-size: 32px; }
    .hero-agents { gap: 16px; }
    th, td { padding: 6px 8px; }
    .chat-shell { grid-template-columns: 1fr; }
    .chat-sidebar { position: static; }
    .chat-feed { max-height: 50vh; }
    .tabs { width: 100%; overflow-x: auto; }
  }
</style>
</head><body>
<div class="page">

  <!-- Hero -->
  <div class="hero">
    <div class="hero-mark">
      <svg viewBox="0 0 160 180" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="80" cy="72" r="64" stroke="currentColor" stroke-width="4" fill="none"/>
        <path d="M60 44 L60 100 M60 44 L85 44 C100 44 108 52 108 62 C108 72 100 80 85 80 L60 80"
              stroke="currentColor" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        <circle cx="32" cy="148" r="10" stroke="currentColor" stroke-width="3.5" fill="none"/>
        <circle cx="18" cy="172" r="5.5" stroke="currentColor" stroke-width="3" fill="none"/>
      </svg>
    </div>
    <div class="hero-content">
      <h1 class="hero-title">
        {% set active_count = states|selectattr('status', 'in', ['active', 'working'])|list|length %}<span class="count">{{ active_count }}</span> agent{{ 's' if active_count != 1 else '' }} working
      </h1>
    </div>
  </div>

  <!-- Agent Strip -->
  <div class="hero-agents">
    {% for s in states if s.status in ('active', 'working') %}
    <div class="hero-agent">
      <div class="hero-agent-ring active">{{ s.agent_id[:2]|upper }}</div>
      <div class="hero-agent-info">
        <div class="hero-agent-name">{{ s.agent_id }}</div>
        <div class="hero-agent-task">{{ s.current_task or 'working' }} &middot; <span class="relative-time" data-ts="{{ s.updated_at }}">{{ s.updated_at }}</span></div>
      </div>
    </div>
    {% endfor %}
    {% if not states|selectattr('status', 'in', ['active', 'working'])|list %}<div class="muted">All agents idle</div>{% endif %}
  </div>

  <!-- Tabs -->
  <div class="tabs">
    <div class="tab active" data-tab="overview" onclick="showTab('overview', this)">Overview</div>
    <div class="tab" data-tab="chat" onclick="showTab('chat', this)">Chat</div>
    <div class="tab" data-tab="agents" onclick="showTab('agents', this)">Agents</div>
    <div class="tab" data-tab="knowledge" onclick="showTab('knowledge', this)">Knowledge</div>
    <div class="tab" data-tab="system" onclick="showTab('system', this)">System</div>
  </div>

<div id="tab-overview" class="tab-content active">
  <div class="section">
    <div class="section-head">
      <div class="section-title">Tasks</div>
      <a class="section-link">view all &rarr;</a>
    </div>
    {% for t in tasks %}
    <div class="task {{ 'done' if t.status in ('done', 'completed', 'success') else '' }}">
      <div>
        <div class="task-row">
          <span class="task-num">#{{ t.id }}</span>
          <span class="task-title">{{ t.title }}</span>
        </div>
        <div class="task-sub">
          {{ t.assigned_to or '-' }}
          {% if t.created_by and t.created_by != t.assigned_to %} &middot; from {{ t.created_by }}{% endif %}
          {% if t.priority %} &middot; <strong>{{ t.priority }}</strong>{% endif %}
          &middot; <span class="relative-time" data-ts="{{ t.created_at }}">{{ t.created_at }}</span>
        </div>
      </div>
      <span class="pill pill-{{ t.status }}">{{ t.status }}</span>
    </div>
    {% endfor %}
    {% if not tasks %}<div class="muted">No tasks yet</div>{% endif %}
  </div>

  <div class="section">
    <div class="section-head">
      <div class="section-title">Recent Activity</div>
      <a class="section-link">all events &rarr;</a>
    </div>
    {% for e in events %}
    <div class="tl-item">
      <span class="tl-time"><span class="relative-time" data-ts="{{ e.created_at }}">{{ e.created_at }}</span></span>
      <span class="tl-who">{{ e.source_agent }}</span>
      <span class="tl-text">
        <strong>{{ e.event_type }}</strong>{% if e.target_agent %} &rarr; {{ e.target_agent }}{% endif %}
        {% if e.data %}{% set d = e.data_parsed or {} %} &mdash; {{ d.get('msg') or d.get('summary') or d.get('title') or d.get('reason') or d.get('branch') or (e.data[:80] if e.data is string else '') }}{% endif %}
      </span>
    </div>
    {% endfor %}
    {% if not events %}<div class="muted">No events yet</div>{% endif %}
  </div>

  <div class="section">
    <div class="section-head">
      <div class="section-title">Chat</div>
      <a class="section-link" onclick="showTab('chat', findTabButton('chat'))">open full chat &rarr;</a>
    </div>
    <div class="chat-preview">
      <div class="chat-header">
        <div class="chat-channel">#{{ default_chat_channel if default_chat_channel != 'all' else 'general' }}</div>
        <div class="chat-channel-list">
          {% for ch in chat_channels[:4] %}
          <span class="{{ 'active' if ch.channel == default_chat_channel else '' }}">{{ '#' + ch.channel }}</span>
          {% endfor %}
        </div>
      </div>
      <div class="chat-messages">
        {% for m in chat_messages[-3:] %}
        <div class="msg {{ 'self' if m.sender_agent == default_onboarding_agent else '' }}">
          <div class="msg-head">
            <span class="msg-from">{{ m.sender_agent }}</span>
            {% if m.target_agent %}<span class="msg-arrow">&rarr;</span><span class="msg-to">{{ m.target_agent }}</span>{% endif %}
            <span class="msg-time"><span class="relative-time" data-ts="{{ m.created_at }}">{{ m.created_at }}</span></span>
          </div>
          <div class="msg-body">{{ m.body[:200] }}</div>
        </div>
        {% endfor %}
        {% if not chat_messages %}<div class="muted">No messages yet</div>{% endif %}
      </div>
    </div>
  </div>
</div><!-- end tab-overview -->

<div id="tab-chat" class="tab-content">
  <div class="chat-shell">
    <aside class="chat-sidebar">
      <div class="section-title" style="margin-bottom: 8px;">Channels</div>
      <div id="chat-channel-tabs" class="chat-channel-tabs"></div>
      <div style="margin-top: 16px;">
        <label for="chat-quick-channel">Open Channel</label>
        <input id="chat-quick-channel" placeholder="general" style="margin-bottom: 6px;">
        <button onclick="jumpToChatChannel()" style="width: 100%;">Open</button>
      </div>
    </aside>
    <section class="chat-main" style="display: flex; flex-direction: column; min-height: 0;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <div style="display: flex; align-items: baseline; gap: 12px;">
          <span class="section-title" id="chat-active-title" style="margin: 0;">#all</span>
          <span id="chat-feed-status" class="muted" style="font-size: 11px;">Watching chat feed.</span>
        </div>
        <span id="chat-follow-state" class="chat-follow">Follow mode: on</span>
      </div>
      <div id="chat-feed" class="chat-feed" style="flex: 1; min-height: 300px; max-height: 55vh;"></div>
      <div style="border: 1px solid #e0ddd6; border-radius: 10px; padding: 12px 16px; margin-top: 10px; background: #fff;">
        <div style="display: flex; gap: 8px; align-items: end;">
          <div style="flex: 1;">
            <textarea id="chat-body" placeholder="Message..." style="min-height: 44px; max-height: 120px; resize: vertical;"></textarea>
          </div>
          <button onclick="sendChatMessage()" style="height: 44px; padding: 0 20px;">Send</button>
        </div>
        <details style="margin-top: 8px;">
          <summary style="font-size: 11px; color: #999; cursor: pointer; user-select: none;">Options</summary>
          <div class="chat-toolbar" style="margin-top: 8px;">
            <div>
              <label for="chat-watch-agent">Highlight Agent</label>
              <input id="chat-watch-agent" list="agent-ids" value="{{ default_onboarding_agent }}" placeholder="optional">
            </div>
            <div>
              <label for="chat-channel">Channel</label>
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
        </details>
        <span id="chat-status" class="muted" style="font-size: 11px;"></span>
      </div>
    </section>
  </div>
</div>

<div id="tab-agents" class="tab-content">
  <div class="section-head"><div class="section-title">Agent Registry</div></div>
  {% for profile in agent_profiles %}
  <div class="agent-card">
    <div class="agent-card-name">{{ profile.agent_id }}{% if profile.display_name %} &mdash; {{ profile.display_name }}{% endif %}</div>
    <div class="agent-card-meta">
      <span class="status-{{ profile.state.status if profile.state else 'idle' }}">{{ profile.state.status if profile.state else 'idle' }}</span>
      {% if profile.integration_mode %}<span>{{ profile.integration_mode }}</span>{% endif %}
      {% if profile.native_feature %}<span>{{ profile.native_feature }}</span>{% endif %}
    </div>
    {% if profile.onboarding_note %}<div class="muted" style="margin-top: 4px; font-size: 12px;">{{ profile.onboarding_note }}</div>{% endif %}
  </div>
  {% endfor %}
  {% if not agent_profiles %}<div class="muted">No agents registered yet</div>{% endif %}
</div>


<div id="tab-knowledge" class="tab-content">
  <div class="section-head"><div class="section-title">Knowledge Base</div></div>
  <table>
    <tr><th>#</th><th>Category</th><th>Subject</th><th>Predicate</th><th>Object</th><th>Confidence</th><th>Source</th></tr>
    {% for k in all_knowledge %}
    <tr>
      <td>{{ k.id }}</td>
      <td>{{ k.category }}</td>
      <td><strong>{{ k.subject }}</strong></td>
      <td>{{ k.predicate }}</td>
      <td>{{ k.object }}</td>
      <td><div class="confidence"><div class="confidence-fill" style="width:{{ (k.confidence * 100)|int }}%"></div></div> {{ "%.0f"|format(k.confidence * 100) }}%</td>
      <td>{{ k.source or '-' }}</td>
    </tr>
    {% endfor %}
    {% if not all_knowledge %}<tr><td colspan="7" class="muted">No knowledge yet</td></tr>{% endif %}
  </table>
</div>

<div id="tab-system" class="tab-content">
  {% for note in pinned_notes %}
  <div class="pinned">
    <h3>{{ note.subject }}</h3>
    <button class="copy-btn" onclick="copyText(this, 'note-{{ note.id }}')" style="position: absolute; top: 12px; right: 12px;">Copy</button>
    <pre id="note-{{ note.id }}">{{ note.object }}</pre>
  </div>
  {% endfor %}

  <div class="section">
    <div class="section-head"><div class="section-title">Sessions</div></div>
    <table>
      <tr><th>Session</th><th>Agent</th><th>Started</th><th>Status</th></tr>
      {% for s in sessions %}
      <tr>
        <td>{{ s.id }}</td>
        <td class="agent">{{ s.agent_id }}</td>
        <td><span class="relative-time" data-ts="{{ s.started_at }}">{{ s.started_at }}</span></td>
        <td class="{{ 'session-active' if not s.ended_at else 'session-ended' }}">{{ 'active' if not s.ended_at else 'ended' }}</td>
      </tr>
      {% endfor %}
      {% if not sessions %}<tr><td colspan="4" class="muted">No sessions</td></tr>{% endif %}
    </table>
  </div>

  <div class="section">
    <div class="section-head"><div class="section-title">Working Memory</div></div>
    {% for agent_id, wm_data in wm_by_agent.items() %}
    <div class="panel">
      <div style="font-family: 'IBM Plex Mono', monospace; font-weight: 600; margin-bottom: 8px;">{{ agent_id }} <span class="muted">({{ wm_data.session_id }})</span></div>
      <table>
        <tr><th>Key</th><th>Value</th></tr>
        {% for k, v in wm_data.items.items() %}
        <tr><td class="wm-key">{{ k }}</td><td>{{ v }}</td></tr>
        {% endfor %}
        {% if not wm_data.items %}<tr><td colspan="2" class="muted">(empty)</td></tr>{% endif %}
      </table>
    </div>
    {% endfor %}
    {% if not wm_by_agent %}<div class="muted">No active working memory.</div>{% endif %}
  </div>

  <div class="section">
    <div class="section-head"><div class="section-title">Episodes</div></div>
    <table>
      <tr><th>#</th><th>Title</th><th>Agent</th><th>Category</th><th>Outcome</th><th>Tags</th><th>Started</th></tr>
      {% for ep in all_episodes %}
      <tr>
        <td>{{ ep.id }}</td>
        <td>{{ ep.title }}</td>
        <td class="agent">{{ ep.agent_id }}</td>
        <td>{{ ep.category }}</td>
        <td>{{ ep.outcome or '...' }}</td>
        <td>{% if ep.tags %}{% for tag in ep.tags_list %}<span class="tag">{{ tag }}</span>{% endfor %}{% endif %}</td>
        <td><span class="relative-time" data-ts="{{ ep.started_at }}">{{ ep.started_at }}</span></td>
      </tr>
      {% endfor %}
      {% if not all_episodes %}<tr><td colspan="7" class="muted">No episodes yet</td></tr>{% endif %}
    </table>
  </div>

  <div class="section">
    <div class="section-head"><div class="section-title">Onboarding</div></div>
    <div class="panel">
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
      <div id="onboarding-status" class="muted" style="font-size: 11px;">Canonical onboarding bundle for current and future agents.</div>
      <pre id="onboarding-prompt" class="prompt-box">{{ onboarding_bundle.prompt if onboarding_bundle else '(select an agent)' }}</pre>
    </div>
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
const TAB_NAMES = ['overview', 'chat', 'agents', 'knowledge', 'system'];
const TAB_REDIRECTS = { 'working': 'system', 'episodes': 'system', 'onboarding': 'system' };
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
  let tab = rawTab.toLowerCase();
  if (TAB_REDIRECTS[tab]) tab = TAB_REDIRECTS[tab];
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

function formatRelativeTime(ts) {
  if (!ts) return '';
  var d = new Date(ts.replace(' ', 'T') + (ts.includes('+') || ts.includes('Z') ? '' : 'Z'));
  if (isNaN(d)) return ts;
  var diff = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return months[d.getMonth()] + ' ' + d.getDate() + ', ' + String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
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
    const target = escapeHtml(msg.target_agent || '');
    const body = escapeHtml(msg.body);
    const created = escapeHtml(msg.created_at);
    const isSelf = watchAgent && sender.toLowerCase() === watchAgent;
    const cls = isSelf ? 'msg self' : 'msg';
    const targetHtml = target
      ? `<span class="msg-arrow">&rarr;</span><span class="msg-to">${target}</span>`
      : '';
    return `
      <div class="${cls}" data-id="${msg.id}">
        <div class="msg-head">
          <span class="msg-from">${sender}</span>
          ${targetHtml}
          <span class="msg-time relative-time" data-ts="${created}">${formatRelativeTime(msg.created_at)}</span>
        </div>
        <div class="msg-body">${body}</div>
      </div>
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
    const target = event.target.closest('[data-channel]');
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
function updateRelativeTimes() {
  document.querySelectorAll('.relative-time').forEach(function(el) {
    var ts = el.getAttribute('data-ts');
    if (ts) {
      el.textContent = formatRelativeTime(ts);
      el.title = ts;
    }
  });
}
updateRelativeTimes();
setInterval(updateRelativeTimes, 30000);
syncTabFromHash();
</script>
</div>
</body></html>
"""


LIVE_HTML = """<!doctype html>
<html><head>
<title>Ponder - Live</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace; background: #06080f; color: #e8edff; padding: 16px; }
  h1 { font-size: 1.1rem; color: #7c3aed; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
  h1 .dot { width: 8px; height: 8px; border-radius: 50%; animation: pulse 2s ease infinite; }
  .dot-active { background: #4ade80; }
  .dot-idle { background: #888; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  .agent-bar { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
  .agent-card { background: rgba(17, 22, 40, 0.65); border: 1px solid rgba(120, 130, 180, 0.12); border-radius: 8px; padding: 10px 14px; min-width: 200px; }
  .agent-name { font-weight: 600; color: #22d3ee; font-size: 0.85rem; }
  .agent-status { font-size: 0.75rem; margin-top: 2px; }
  .agent-task { font-size: 0.78rem; color: #e8edff; margin-top: 4px; }
  .status-active, .status-working { color: #4ade80; }
  .status-idle { color: #666; }
  .obs-list { display: flex; flex-direction: column; gap: 2px; }
  .obs { display: flex; gap: 10px; padding: 6px 10px; border-radius: 6px; font-size: 0.78rem; align-items: baseline; }
  .obs:nth-child(odd) { background: rgba(17, 22, 40, 0.4); }
  .obs-time { color: #666; min-width: 55px; flex-shrink: 0; }
  .obs-tool { color: #c084fc; min-width: 50px; font-weight: 600; flex-shrink: 0; }
  .obs-action { color: #22d3ee; min-width: 55px; flex-shrink: 0; }
  .obs-summary { color: #e8edff; word-break: break-all; }
  .section-title { font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: #766e86; margin: 14px 0 6px; }
  .empty { color: #666; font-style: italic; font-size: 0.82rem; padding: 8px 0; }
  .refresh { font-size: 0.65rem; color: #666; }
</style>
</head>
<body>
<h1><div class="dot" id="pulse-dot"></div> Ponder Live <span class="refresh" id="refresh-label"></span></h1>
<div class="agent-bar" id="agents"></div>
<div class="section-title">Recent Activity</div>
<div class="obs-list" id="observations"><div class="empty">Loading...</div></div>
<script>
function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
var VALID_STATUSES = ['active', 'working', 'idle', 'waiting'];
function safeStatus(s) { return VALID_STATUSES.indexOf(s) >= 0 ? s : 'idle'; }
async function refresh() {
  try {
    var statesRes = await fetch('/api/state?stale_days=7');
    if (!statesRes.ok) throw new Error('state: ' + statesRes.status);
    var states = await statesRes.json();
    var agentsEl = document.getElementById('agents');
    var dot = document.getElementById('pulse-dot');
    var anyActive = states.some(function(s) { return s.status === 'active' || s.status === 'working'; });
    dot.className = 'dot ' + (anyActive ? 'dot-active' : 'dot-idle');
    agentsEl.innerHTML = states.map(function(s) {
      var cls = safeStatus(s.status);
      return '<div class="agent-card"><div class="agent-name">' + esc(s.agent_id) + '</div>' +
        '<div class="agent-status status-' + cls + '">' + esc(s.status) + '</div>' +
        (s.current_task ? '<div class="agent-task">' + esc(s.current_task) + '</div>' : '') +
        '</div>';
    }).join('');
    var obsRes = await fetch('/api/observations?limit=30');
    if (!obsRes.ok) throw new Error('observations: ' + obsRes.status);
    var obs = await obsRes.json();
    var el = document.getElementById('observations');
    if (!obs.length) { el.innerHTML = '<div class="empty">No observations yet</div>'; return; }
    el.innerHTML = obs.map(function(o) {
      var t = new Date((o.created_at || '').replace(' ', 'T') + 'Z');
      var time = isNaN(t) ? o.created_at : t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      return '<div class="obs">' +
        '<span class="obs-time">' + esc(time) + '</span>' +
        '<span class="obs-tool">' + esc(o.tool_name) + '</span>' +
        '<span class="obs-action">' + esc(o.action || '') + '</span>' +
        '<span class="obs-summary">' + esc((o.summary || '').substring(0, 120)) + '</span></div>';
    }).join('');
    document.getElementById('refresh-label').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (e) {
    document.getElementById('refresh-label').textContent = 'Error: ' + e.message;
  }
}
refresh();
setInterval(refresh, 3000);
</script>
</body></html>"""


@app.route("/live")
def live_dashboard():
    return LIVE_HTML


def _parse_event_data(events):
    for e in events:
        e["data_parsed"] = {}
        if e.get("data"):
            try:
                e["data_parsed"] = json.loads(e["data"]) if isinstance(e["data"], str) else e["data"]
            except (json.JSONDecodeError, TypeError):
                pass
    return events


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
        states=mem.get_all_states(stale_days=7),
        tasks=mem.list_tasks(include_done=False, limit=3),
        events=_parse_event_data(mem.get_latest_events(limit=5)),
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
    stale_days = _parse_int_arg("stale_days", None)
    return jsonify(mem.get_all_states(stale_days=stale_days))


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


# ── API: Observations ────────────────────────────────────────

@app.route("/api/observations", methods=["GET"])
def api_observations_list():
    return jsonify(mem.get_observations(
        agent_id=request.args.get("agent_id"),
        session_id=request.args.get("session_id"),
        tool_name=request.args.get("tool_name"),
        limit=_parse_int_arg("limit", 100),
        offset=_parse_int_arg("offset", 0),
    ))


@app.route("/api/observations", methods=["POST"])
def api_observations_create():
    data = request.get_json(force=True)
    agent_id = data.get("agent_id")
    tool_name = data.get("tool_name")
    if not agent_id or not tool_name:
        return jsonify({"error": "agent_id and tool_name required"}), 400
    oid = mem.add_observation(
        agent_id=agent_id,
        tool_name=tool_name,
        action=data.get("action"),
        file_path=data.get("file_path"),
        summary=data.get("summary"),
        session_id=data.get("session_id"),
    )
    return jsonify({"ok": True, "id": oid})


@app.route("/api/observations/search")
def api_observations_search():
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "q parameter required"}), 400
    try:
        results = mem.search_observations(
            query=query,
            limit=_parse_int_arg("limit", 50),
        )
    except Exception:
        return jsonify({"error": "Invalid search query"}), 400
    return jsonify(results)


@app.route("/api/observations/summary/<session_id>")
def api_observations_summary(session_id):
    summary = mem.session_observation_summary(session_id)
    if summary is None:
        return jsonify({"error": "No observations for session"}), 404
    return jsonify({"session_id": session_id, "summary": summary})


# ── API: Maintenance ─────────────────────────────────────────

@app.route("/api/maintenance", methods=["POST"])
def api_maintenance():
    cleaned_wm = mem.cleanup_expired_wm()
    cleaned_tasks = mem.cleanup_done_tasks(days=7)
    decayed = mem.decay_knowledge(days_threshold=30, decay_rate=0.05)
    cleaned_obs = mem.cleanup_old_observations(days=30)
    return jsonify({
        "ok": True,
        "cleaned_wm": cleaned_wm,
        "cleaned_tasks": cleaned_tasks,
        "decayed_knowledge": decayed,
        "cleaned_observations": cleaned_obs,
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
    cleaned_obs = mem.cleanup_old_observations(days=30)
    if cleaned_obs:
        log.info("Cleaned up %d old observations", cleaned_obs)

    try:
        from waitress import serve
        serve(app, host=host, port=PORT, threads=2, _quiet=True)
    except ImportError:
        log.warning("waitress not found, using Flask dev server")
        app.run(host=host, port=PORT, debug=False)
    finally:
        if not DOCKER:
            remove_pid()
