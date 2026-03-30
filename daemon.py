#!/usr/bin/env python3
"""Ponder Daemon -- REST API for shared agent state.

Runs on localhost:9077 (mnemonic: 90 = memory, 77 = lucky).
Used by AI agents and humans via browser.

Start:  python daemon.py
Stop:   kill $(cat ~/.ponder/ponder/daemon.pid)

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

log = logging.getLogger("ponder")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

STARTUP_TIME = datetime.now(timezone.utc)

PORT = int(os.environ.get("PONDER_PORT", 9077))
PONDER_URL = os.environ.get("PONDER_URL", f"http://localhost:{PORT}")
DOCKER = os.environ.get("DOCKER", "").strip() == "1"
PID_FILE = Path.home() / ".ponder" / "ponder" / "daemon.pid"

app = Flask(__name__)
mem = AgentMemory()

# ── Setup Wizard ────────────────────────────────────────────

WIZARD_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ponder Setup</title>
<link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700;800;900&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Figtree', sans-serif; background: #f5f3ef; color: #1a1a1a; }

  .wizard-page {
    min-height: 100vh;
    display: none;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 40px 24px;
    position: relative;
  }
  .wizard-page.active { display: flex; }

  .wizard-progress {
    position: absolute;
    top: 32px;
    display: flex;
    gap: 8px;
  }
  .wizard-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #e0ddd6;
    transition: background 0.3s;
  }
  .wizard-dot.active { background: #c45a3c; }
  .wizard-dot.done { background: #1a1a1a; }

  .wizard-content {
    max-width: 560px;
    width: 100%;
    text-align: center;
  }

  .wizard-title {
    font-size: 42px;
    font-weight: 800;
    line-height: 1.1;
    margin-bottom: 16px;
    letter-spacing: -0.5px;
  }

  .wizard-subtitle {
    font-size: 17px;
    color: #666;
    line-height: 1.6;
    margin-bottom: 40px;
  }

  .wizard-card {
    background: #fff;
    border: 1px solid #e0ddd6;
    border-radius: 14px;
    padding: 32px;
    text-align: left;
    margin-bottom: 32px;
  }

  .wizard-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #999;
    font-weight: 600;
    margin-bottom: 8px;
  }

  .wizard-hint {
    font-size: 12px;
    color: #999;
    margin-top: 6px;
    line-height: 1.5;
  }

  .wizard-input {
    width: 100%;
    padding: 12px 16px;
    border: 1px solid #e0ddd6;
    border-radius: 8px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 15px;
    outline: none;
    transition: border-color 0.2s;
  }
  .wizard-input:focus { border-color: #c45a3c; }

  .wizard-input-normal {
    width: 100%;
    padding: 12px 16px;
    border: 1px solid #e0ddd6;
    border-radius: 8px;
    font-family: 'Figtree', sans-serif;
    font-size: 15px;
    outline: none;
    transition: border-color 0.2s;
  }
  .wizard-input-normal:focus { border-color: #c45a3c; }

  .wizard-btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 14px 32px;
    background: #1a1a1a;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    font-family: 'Figtree', sans-serif;
    transition: transform 0.1s;
  }
  .wizard-btn:hover { transform: translateY(-1px); }
  .wizard-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

  .wizard-btn-secondary {
    background: transparent;
    color: #999;
    border: 1px solid #e0ddd6;
  }

  .wizard-code {
    background: #1a1a1a;
    color: #e0ddd6;
    border-radius: 10px;
    padding: 20px 24px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    line-height: 1.8;
    text-align: left;
    position: relative;
    overflow-x: auto;
    margin-bottom: 16px;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .copy-badge {
    position: absolute;
    top: 12px; right: 12px;
    padding: 4px 12px;
    background: rgba(255,255,255,0.1);
    border-radius: 6px;
    font-size: 11px;
    color: #999;
    cursor: pointer;
    border: none;
    font-family: 'Figtree', sans-serif;
    transition: background 0.2s, color 0.2s;
  }
  .copy-badge:hover { background: rgba(255,255,255,0.2); color: #fff; }

  .waiting-indicator {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 20px;
    color: #999;
    font-size: 14px;
  }

  .pulse-ring {
    width: 12px; height: 12px;
    border-radius: 50%;
    background: #c45a3c;
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 0.4; transform: scale(0.8); }
    50% { opacity: 1; transform: scale(1.2); }
  }

  .success-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 20px;
    background: #d4edda;
    color: #155724;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 24px;
  }

  .step-label {
    display: inline-block;
    padding: 4px 12px;
    background: #e0ddd6;
    border-radius: 20px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #999;
    font-weight: 600;
    margin-bottom: 24px;
  }

  .btn-row {
    display: flex;
    gap: 12px;
    justify-content: center;
    margin-top: 8px;
  }

  .field-group {
    margin-bottom: 20px;
  }
  .field-group:last-child { margin-bottom: 0; }

  .example-pills {
    display: flex;
    gap: 6px;
    margin-top: 8px;
    flex-wrap: wrap;
  }
  .example-pill {
    padding: 3px 10px;
    background: #f5f3ef;
    border: 1px solid #e0ddd6;
    border-radius: 20px;
    font-size: 11px;
    font-family: 'IBM Plex Mono', monospace;
    color: #666;
    cursor: pointer;
    transition: border-color 0.2s;
  }
  .example-pill:hover { border-color: #c45a3c; }

  .send-guide {
    background: #fff;
    border: 1px solid #e0ddd6;
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 24px;
    text-align: left;
  }
  .send-guide-title {
    font-weight: 600;
    font-size: 14px;
    margin-bottom: 12px;
  }
  .send-guide-step {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    margin-bottom: 12px;
    font-size: 13px;
    color: #666;
    line-height: 1.5;
  }
  .send-guide-step:last-child { margin-bottom: 0; }
  .send-guide-num {
    width: 24px; height: 24px;
    min-width: 24px;
    background: #f5f3ef;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    font-weight: 700;
    color: #c45a3c;
  }

  .wizard-error {
    background: #f8d7da;
    color: #721c24;
    border: 1px solid #f5c6cb;
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 13px;
    margin-bottom: 16px;
    display: none;
  }

  .wizard-back {
    color: #999;
    font-size: 13px;
    cursor: pointer;
    border: none;
    background: none;
    font-family: 'Figtree', sans-serif;
    margin-bottom: 16px;
  }
  .wizard-back:hover { color: #666; }

  .timeout-hint {
    color: #c45a3c;
    font-size: 12px;
    margin-top: 8px;
    display: none;
  }

  /* Finish animation */
  .finish-icon {
    width: 80px; height: 80px;
    margin: 0 auto 24px;
    position: relative;
  }
  .finish-circle {
    width: 80px; height: 80px;
    border-radius: 50%;
    border: 3px solid #1a1a1a;
    display: flex;
    align-items: center;
    justify-content: center;
    animation: scaleIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) both;
  }
  @keyframes scaleIn {
    0% { transform: scale(0); opacity: 0; }
    100% { transform: scale(1); opacity: 1; }
  }
  .finish-check {
    width: 32px; height: 32px;
    animation: drawCheck 0.4s 0.4s ease-out both;
  }
  @keyframes drawCheck {
    0% { opacity: 0; transform: scale(0.5) rotate(-10deg); }
    100% { opacity: 1; transform: scale(1) rotate(0deg); }
  }
  .finish-rays {
    position: absolute;
    top: -12px; left: -12px;
    right: -12px; bottom: -12px;
  }
  .finish-ray {
    position: absolute;
    width: 2px;
    height: 10px;
    background: #c45a3c;
    border-radius: 2px;
    animation: rayBurst 0.5s 0.6s ease-out both;
    transform-origin: center;
  }
  @keyframes rayBurst {
    0% { opacity: 0; transform: scaleY(0); }
    50% { opacity: 1; transform: scaleY(1); }
    100% { opacity: 0; transform: scaleY(0.5) translateY(-4px); }
  }
  .finish-ray:nth-child(1) { top: 0; left: 50%; transform: translateX(-50%); }
  .finish-ray:nth-child(2) { top: 8px; right: 8px; transform: rotate(45deg); }
  .finish-ray:nth-child(3) { right: 0; top: 50%; transform: translateY(-50%) rotate(90deg); }
  .finish-ray:nth-child(4) { bottom: 8px; right: 8px; transform: rotate(135deg); }
  .finish-ray:nth-child(5) { bottom: 0; left: 50%; transform: translateX(-50%) rotate(180deg); }
  .finish-ray:nth-child(6) { bottom: 8px; left: 8px; transform: rotate(225deg); }
  .finish-ray:nth-child(7) { left: 0; top: 50%; transform: translateY(-50%) rotate(270deg); }
  .finish-ray:nth-child(8) { top: 8px; left: 8px; transform: rotate(315deg); }
</style>
</head>
<body>

<!-- ============ STEP 1: Welcome ============ -->
<div id="step-welcome" class="wizard-page active" style="background: linear-gradient(180deg, #f5f3ef 0%, #ece9e3 100%);">
  <div class="wizard-progress">
    <div class="wizard-dot active"></div>
    <div class="wizard-dot"></div>
    <div class="wizard-dot"></div>
    <div class="wizard-dot"></div>
  </div>
  <div class="wizard-content">
    <div style="font-size: 64px; font-weight: 900; margin-bottom: 24px; letter-spacing: -2px;">P</div>
    <div class="wizard-title">Welcome to Ponder</div>
    <div class="wizard-subtitle">
      Shared memory for your AI agents. Connect Claude Code, Codex, and other agents
      to a central knowledge layer that persists across sessions.
    </div>
    <button class="wizard-btn" onclick="showStep('register')">Get Started &rarr;</button>
  </div>
</div>

<!-- ============ STEP 2: Register Agent ============ -->
<div id="step-register" class="wizard-page">
  <div class="wizard-progress">
    <div class="wizard-dot done"></div>
    <div class="wizard-dot active"></div>
    <div class="wizard-dot"></div>
    <div class="wizard-dot"></div>
  </div>
  <div class="wizard-content">
    <div class="step-label">Step 1 of 3</div>
    <div class="wizard-title" style="font-size: 32px;">Register your first agent</div>
    <div class="wizard-subtitle">
      Every agent needs a unique ID so Ponder can track its state, knowledge, and conversations separately.
    </div>
    <div id="register-error" class="wizard-error"></div>
    <div class="wizard-card">
      <div class="field-group">
        <div class="wizard-label">Agent ID</div>
        <input id="agent-id-input" class="wizard-input" placeholder="e.g. claude-lin">
        <div class="wizard-hint">A short, unique identifier. Use lowercase with hyphens. Convention: <strong>tool-machine</strong> (e.g. claude-lin = Claude on Linux).</div>
        <div class="example-pills">
          <span class="example-pill" onclick="document.getElementById('agent-id-input').value=this.textContent">claude-lin</span>
          <span class="example-pill" onclick="document.getElementById('agent-id-input').value=this.textContent">codex-win</span>
          <span class="example-pill" onclick="document.getElementById('agent-id-input').value=this.textContent">claude-mac</span>
          <span class="example-pill" onclick="document.getElementById('agent-id-input').value=this.textContent">gemini-srv</span>
        </div>
      </div>
      <div class="field-group">
        <div class="wizard-label">Display Name</div>
        <input id="agent-name-input" class="wizard-input-normal" placeholder="A friendly name shown in the dashboard">
        <div class="wizard-hint">This appears in the dashboard, chat, and leaderboard. Can be anything you want.</div>
      </div>
    </div>
    <button class="wizard-btn" onclick="registerAgent()">Continue &rarr;</button>
  </div>
</div>

<!-- ============ STEP 3: Connect / Pairing ============ -->
<div id="step-connect" class="wizard-page">
  <div class="wizard-progress">
    <div class="wizard-dot done"></div>
    <div class="wizard-dot done"></div>
    <div class="wizard-dot active"></div>
    <div class="wizard-dot"></div>
  </div>
  <div class="wizard-content">
    <div class="step-label">Step 2 of 3</div>
    <button class="wizard-back" onclick="showStep('register')">&larr; Back</button>
    <div class="wizard-title" style="font-size: 32px;">Connect your agent</div>
    <div class="wizard-subtitle">
      Send the onboarding instructions to your agent. It will read them and connect to Ponder automatically.
    </div>

    <div class="wizard-code" style="padding-right: 72px;">
      <button class="copy-badge" onclick="copyInstructions()">Copy</button>
      <div id="onboarding-code">Loading onboarding instructions...</div>
    </div>

    <div class="send-guide">
      <div class="send-guide-title">How to connect</div>
      <div class="send-guide-step">
        <div class="send-guide-num">1</div>
        <div>Copy the instructions above</div>
      </div>
      <div class="send-guide-step">
        <div class="send-guide-num">2</div>
        <div>Open a conversation with your agent (Claude Code, Codex, or any AI assistant)</div>
      </div>
      <div class="send-guide-step">
        <div class="send-guide-num">3</div>
        <div>Paste the instructions and tell the agent to follow them. It will connect to Ponder and set its status to active.</div>
      </div>
    </div>

    <div class="waiting-indicator">
      <div class="pulse-ring"></div>
      Waiting for <strong id="waiting-agent-name" style="margin: 0 4px;">agent</strong> to check in...
    </div>
    <div id="timeout-hint" class="timeout-hint">
      Taking longer than expected? Check that your agent can reach this server.
    </div>
  </div>
</div>

<!-- ============ STEP 3b: Agent Connected! ============ -->
<div id="step-connected" class="wizard-page">
  <div class="wizard-progress">
    <div class="wizard-dot done"></div>
    <div class="wizard-dot done"></div>
    <div class="wizard-dot active"></div>
    <div class="wizard-dot"></div>
  </div>
  <div class="wizard-content">
    <div class="success-badge" id="connected-badge">&#10003; <span id="connected-agent-name">agent</span> connected</div>
    <div class="wizard-title" style="font-size: 32px;">Agent connected!</div>
    <div class="wizard-subtitle" id="connected-subtitle">
      Your agent has checked in and is ready to use Ponder.
    </div>
    <div class="btn-row">
      <button class="wizard-btn wizard-btn-secondary" onclick="showStep('register')">+ Add another agent</button>
      <button class="wizard-btn" onclick="showStep('done')">Finish Setup &rarr;</button>
    </div>
  </div>
</div>

<!-- ============ STEP 4: Done ============ -->
<div id="step-done" class="wizard-page" style="background: linear-gradient(180deg, #f5f3ef 0%, #ece9e3 100%);">
  <div class="wizard-progress">
    <div class="wizard-dot done"></div>
    <div class="wizard-dot done"></div>
    <div class="wizard-dot done"></div>
    <div class="wizard-dot active"></div>
  </div>
  <div class="wizard-content">
    <div class="finish-icon">
      <div class="finish-rays">
        <div class="finish-ray"></div>
        <div class="finish-ray"></div>
        <div class="finish-ray"></div>
        <div class="finish-ray"></div>
        <div class="finish-ray"></div>
        <div class="finish-ray"></div>
        <div class="finish-ray"></div>
        <div class="finish-ray"></div>
      </div>
      <div class="finish-circle">
        <svg class="finish-check" viewBox="0 0 24 24" fill="none" stroke="#1a1a1a" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="4 12 10 18 20 6"></polyline>
        </svg>
      </div>
    </div>
    <div class="wizard-title" style="font-size: 32px;">You're all set</div>
    <div class="wizard-subtitle">
      Ponder is ready. Your agents will share knowledge, state, and chat across sessions.
    </div>
    <button class="wizard-btn" onclick="window.location.href='/'">Open Dashboard &rarr;</button>
  </div>
</div>

<script>
var currentAgentId = '';
var pollTimer = null;
var timeoutTimer = null;
var ponderUrl = '{{ ponder_url }}';

function showStep(name) {
  document.querySelectorAll('.wizard-page').forEach(function(p) {
    p.classList.remove('active');
  });
  var target = document.getElementById('step-' + name);
  if (target) target.classList.add('active');

  /* Reset progress dots on the target step -- they are baked into each
     step's HTML already, so we don't need dynamic logic here.  But when
     navigating *back* to register we should clear errors. */
  if (name === 'register') {
    document.getElementById('register-error').style.display = 'none';
  }
}

async function registerAgent() {
  var agentId = document.getElementById('agent-id-input').value.trim();
  var displayName = document.getElementById('agent-name-input').value.trim();
  var errEl = document.getElementById('register-error');

  if (!agentId) {
    errEl.textContent = 'Please enter an Agent ID.';
    errEl.style.display = 'block';
    return;
  }
  if (!/^[a-z0-9-]+$/.test(agentId)) {
    errEl.textContent = 'Agent ID must be lowercase letters, numbers, and hyphens only.';
    errEl.style.display = 'block';
    return;
  }
  errEl.style.display = 'none';

  try {
    var res = await fetch('/api/agents/' + encodeURIComponent(agentId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: displayName || agentId })
    });
    if (!res.ok) {
      var body = await res.json().catch(function() { return {}; });
      throw new Error(body.error || 'Failed to register agent (HTTP ' + res.status + ')');
    }

    currentAgentId = agentId;
    await fetchOnboarding(agentId);
    document.getElementById('waiting-agent-name').textContent = agentId;
    showStep('connect');
    startPolling(agentId);
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = 'block';
  }
}

async function fetchOnboarding(agentId) {
  try {
    var res = await fetch('/api/onboarding/' + encodeURIComponent(agentId));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var data = await res.json();
    var codeEl = document.getElementById('onboarding-code');
    if (data && data.prompt) {
      codeEl.textContent = data.prompt;
    } else {
      codeEl.textContent = '(No onboarding prompt available)';
    }
  } catch (e) {
    document.getElementById('onboarding-code').textContent = 'Error loading onboarding: ' + e.message;
  }
}

function startPolling(agentId) {
  stopPolling();
  var hint = document.getElementById('timeout-hint');
  hint.style.display = 'none';

  pollTimer = setInterval(async function() {
    try {
      var res = await fetch('/api/state/' + encodeURIComponent(agentId));
      if (!res.ok) return;
      var data = await res.json();
      if (data && data.status) {
        stopPolling();
        document.getElementById('connected-agent-name').textContent = agentId;
        document.getElementById('connected-subtitle').textContent =
          agentId + ' has checked in and is ready to use Ponder.';
        showStep('connected');
      }
    } catch (e) { /* ignore, retry next interval */ }
  }, 3000);

  timeoutTimer = setTimeout(function() {
    hint.style.display = 'block';
  }, 120000);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  if (timeoutTimer) { clearTimeout(timeoutTimer); timeoutTimer = null; }
}

function copyInstructions() {
  var code = document.getElementById('onboarding-code').textContent;
  var btn = document.querySelector('.copy-badge');
  navigator.clipboard.writeText(code).then(function() {
    btn.textContent = 'Copied!';
    setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
  }).catch(function() {
    /* Fallback for non-HTTPS contexts */
    var ta = document.createElement('textarea');
    ta.value = code;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    btn.textContent = 'Copied!';
    setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
  });
}
</script>
</body>
</html>"""

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
  .msg-continuation { padding-top: 2px; border-bottom: none; }
  .msg-continuation + .msg:not(.msg-continuation) { border-top: 1px solid #eae7e0; }
  .msg-head-mini { margin-bottom: 2px; }
  .msg-head-mini .msg-time { font-size: 9px; color: #ccc; }
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

  /* Knowledge */
  .k-pill { font-family: 'IBM Plex Mono', monospace; font-size: 11px; padding: 4px 10px; border-radius: 5px; cursor: pointer; border: 1px solid #e0ddd6; background: #fff; color: #888; transition: all 0.12s; display: inline-block; }
  .k-pill:hover { border-color: #c4c0b8; color: #1a1a1a; }
  .k-pill.active { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }
  .k-card { background: #fff; border: 1px solid #e0ddd6; border-radius: 10px; padding: 14px 18px; margin-bottom: 6px; transition: border-color 0.12s; }
  .k-card:hover { border-color: #c4c0b8; }
  .k-card[hidden] { display: none; }

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
    .sys-health-grid { grid-template-columns: repeat(2, 1fr) !important; }
    .sys-wm-grid { grid-template-columns: 1fr !important; }
    .sys-maint-grid { grid-template-columns: 1fr !important; }
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
    <aside class="chat-sidebar" style="display:flex;flex-direction:column;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <div class="section-title" style="margin:0;">Channels</div>
        <span id="chat-sort-toggle" onclick="toggleChannelSort()" style="font-size:10px;color:#999;cursor:pointer;user-select:none;border:1px solid #e0ddd6;padding:2px 8px;border-radius:4px;background:#fff;" title="Click to toggle sort">by activity</span>
      </div>
      <div id="chat-channel-tabs" class="chat-channel-tabs" style="flex:1;overflow-y:auto;"></div>
      <div style="margin-top:auto;padding-top:12px;border-top:1px solid #eae7e0;">
        <div style="display:flex;gap:6px;">
          <input id="chat-quick-channel" placeholder="New channel..." style="flex:1;font-size:12px;padding:6px 8px;">
          <button onclick="jumpToChatChannel()" style="padding:6px 12px;font-size:12px;">Create</button>
        </div>
      </div>
    </aside>
    <section class="chat-main" style="display: flex; flex-direction: column; min-height: 0;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <div style="display: flex; align-items: baseline; gap: 12px;">
          <span class="section-title" id="chat-active-title" style="margin: 0;">All Channels</span>
          <span id="chat-feed-status" class="muted" style="font-size: 11px;">Watching chat feed.</span>
        </div>
        <span id="chat-follow-state" class="chat-follow">Follow mode: on</span>
      </div>
      <div id="chat-feed" class="chat-feed" style="flex: 1; min-height: 300px; max-height: 55vh;"></div>
      <input type="hidden" id="chat-watch-agent" value="{{ default_onboarding_agent }}">
      <input type="hidden" id="chat-channel" value="{{ default_chat_channel if default_chat_channel != 'all' else 'general' }}">
      <input type="hidden" id="chat-target" value="">
      <input type="hidden" id="chat-sender" value="">
      <div style="border: 1px solid #e0ddd6; border-radius: 10px; padding: 10px 14px; margin-top: 10px; background: #fff;">
        <div style="display: flex; gap: 8px; align-items: end;">
          <div style="flex: 1;">
            <textarea id="chat-body" placeholder="Message..." style="min-height: 40px; max-height: 120px; resize: vertical;"></textarea>
          </div>
          <button onclick="sendChatMessage()" style="height: 40px; padding: 0 20px;">Send</button>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
          <span id="chat-post-hint" class="muted" style="font-size: 11px;">Posting to <strong id="chat-post-channel-label">#general</strong> as <span id="chat-sender-label" style="cursor:pointer; text-decoration: underline dotted;" onclick="changeChatNickname()">...</span></span>
          <span id="chat-status" class="muted" style="font-size: 11px;"></span>
        </div>
      </div>
    </section>
  </div>
</div>

<div id="tab-agents" class="tab-content">
  <div style="display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap;">
    <div style="background:#fff;border:1px solid #e0ddd6;border-radius:8px;padding:14px 20px;flex:1;min-width:120px;">
      <div style="font-size:28px;font-weight:800;color:#1a1a1a;">{{ agent_profiles|length }}</div>
      <div style="font-size:11px;color:#999;margin-top:2px;">Total Agents</div>
    </div>
    <div style="background:#fff;border:1px solid #e0ddd6;border-radius:8px;padding:14px 20px;flex:1;min-width:120px;">
      <div style="font-size:28px;font-weight:800;color:#2ecc71;">{{ agents_active|length }}</div>
      <div style="font-size:11px;color:#999;margin-top:2px;">Active</div>
    </div>
    <div style="background:#fff;border:1px solid #e0ddd6;border-radius:8px;padding:14px 20px;flex:1;min-width:120px;">
      <div style="font-size:28px;font-weight:800;color:#d4791c;">{{ agents_inactive|length }}</div>
      <div style="font-size:11px;color:#999;margin-top:2px;">Inactive</div>
    </div>
    <div style="background:#fff;border:1px solid #e0ddd6;border-radius:8px;padding:14px 20px;flex:1;min-width:120px;">
      <div style="font-size:28px;font-weight:800;color:#ccc;">{{ agents_deactivated|length }}</div>
      <div style="font-size:11px;color:#999;margin-top:2px;">Deactivated</div>
    </div>
  </div>
  {% set deactivated_ids = agents_deactivated|map(attribute='agent_id')|list %}
  {% set top_agents = [] %}
  {% for a in leaderboard if a.score > 0 and a.agent_id not in deactivated_ids %}
    {% if top_agents|length < 3 %}{% if top_agents.append(a) %}{% endif %}{% endif %}
  {% endfor %}
  {% if top_agents %}
  <div style="margin-bottom:28px;">
    <div class="section-head"><div class="section-title">Employee of the Month</div></div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;">
      {% for a in top_agents %}
      <div style="flex:1;min-width:200px;background:#fff;border:1px solid {{ '#d4a017' if loop.index == 1 else '#c0c0c0' if loop.index == 2 else '#b87333' }};border-radius:12px;padding:20px;position:relative;overflow:hidden;{{ 'border-width:2px;' if loop.index == 1 else '' }}">
        <div style="position:absolute;top:8px;right:12px;font-size:40px;opacity:0.08;font-weight:900;">{{ loop.index }}</div>
        <div style="margin-bottom:4px;">{% if loop.index == 1 %}<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#d4a017" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 6l4 6l5 -4l-2 10h-14l-2 -10l5 4z"/></svg>{% elif loop.index == 2 %}<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#8a8a8a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v4"/><path d="M10 15h4"/></svg>{% else %}<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#b87333" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v4"/><path d="M10 15h4"/></svg>{% endif %}</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:15px;font-weight:700;margin-bottom:2px;">{{ a.display_name }}</div>
        <div style="font-size:11px;color:#999;margin-bottom:10px;">{{ a.agent_id }}</div>
        <div style="font-size:24px;font-weight:800;color:{{ '#d4a017' if loop.index == 1 else '#8a8a8a' if loop.index == 2 else '#b87333' }};margin-bottom:8px;">{{ a.score }} <span style="font-size:12px;font-weight:500;color:#999;">pts</span></div>
        <div style="display:flex;gap:12px;font-size:11px;color:#999;">
          <span><strong style="color:#1a1a1a;">{{ a.messages }}</strong> msgs</span>
          <span><strong style="color:#1a1a1a;">{{ a.events }}</strong> evts</span>
          <span><strong style="color:#1a1a1a;">{{ a.tasks_created }}</strong> tasks</span>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  <div class="section-head"><div class="section-title">Active Agents</div></div>
  {% for profile in agents_active %}
  <div class="agent-card">
    <div class="agent-card-name">{{ profile.agent_id }}{% if profile.display_name and profile.display_name != profile.agent_id %} &mdash; <span class="agent-rename" onclick="renameAgent('{{ profile.agent_id }}', this)" title="Click to rename" style="cursor:pointer;border-bottom:1px dotted #ccc;">{{ profile.display_name }}</span>{% else %} <span class="agent-rename" onclick="renameAgent('{{ profile.agent_id }}', this)" title="Click to set display name" style="cursor:pointer;color:#ccc;border-bottom:1px dotted #ccc;font-size:11px;">set name</span>{% endif %}</div>
    <div class="agent-card-meta">
      <span class="status-{{ profile.state.status if profile.state else 'idle' }}">{{ profile.state.status if profile.state else 'idle' }}</span>
      {% if profile.state and profile.state.current_task %}<span>{{ profile.state.current_task }}</span>{% endif %}
      {% if profile.state and profile.state.updated_at %}<span class="relative-time" data-ts="{{ profile.state.updated_at }}">{{ profile.state.updated_at }}</span>{% endif %}
    </div>
    {% if profile.onboarding_note %}<div class="muted" style="margin-top: 4px; font-size: 12px;">{{ profile.onboarding_note }}</div>{% endif %}
  </div>
  {% endfor %}
  {% if not agents_active %}<div class="muted">No active agents</div>{% endif %}

  {% if agents_inactive %}
  <details style="margin-top: 20px;">
    <summary style="font-size: 13px; font-weight: 600; color: #999; cursor: pointer; user-select: none;">Inactive ({{ agents_inactive|length }}) <span style="font-weight: 400; font-size: 11px; color: #bbb;">&mdash; no activity for 72h+</span></summary>
    <div style="margin-top: 10px;">
    {% for profile in agents_inactive %}
    <div class="agent-card" style="opacity: 0.6;">
      <div class="agent-card-name">{{ profile.agent_id }}{% if profile.display_name and profile.display_name != profile.agent_id %} &mdash; <span class="agent-rename" onclick="renameAgent('{{ profile.agent_id }}', this)" title="Click to rename" style="cursor:pointer;border-bottom:1px dotted #ccc;">{{ profile.display_name }}</span>{% else %} <span class="agent-rename" onclick="renameAgent('{{ profile.agent_id }}', this)" title="Click to set display name" style="cursor:pointer;color:#ccc;border-bottom:1px dotted #ccc;font-size:11px;">set name</span>{% endif %}</div>
      <div class="agent-card-meta">
        <span class="muted">inactive</span>
        {% if profile.state and profile.state.updated_at %}<span class="relative-time" data-ts="{{ profile.state.updated_at }}">{{ profile.state.updated_at }}</span>{% endif %}
      </div>
    </div>
    {% endfor %}
    </div>
  </details>
  {% endif %}

  {% if agents_deactivated %}
  <details style="margin-top: 16px;">
    <summary style="font-size: 13px; font-weight: 600; color: #666; cursor: pointer; user-select: none;">Deactivated ({{ agents_deactivated|length }}) <span style="font-weight: 400; font-size: 11px; color: #999;">&mdash; no activity for 7d+</span></summary>
    <div style="margin-top: 10px;">
    {% for profile in agents_deactivated %}
    <div class="agent-card" style="display:flex;justify-content:space-between;align-items:center;" id="agent-card-{{ profile.agent_id }}">
      <div style="opacity:0.35;">
        <div class="agent-card-name">{{ profile.agent_id }}{% if profile.display_name and profile.display_name != profile.agent_id %} &mdash; <span class="agent-rename" onclick="renameAgent('{{ profile.agent_id }}', this)" title="Click to rename" style="cursor:pointer;border-bottom:1px dotted #ccc;">{{ profile.display_name }}</span>{% else %} <span class="agent-rename" onclick="renameAgent('{{ profile.agent_id }}', this)" title="Click to set display name" style="cursor:pointer;color:#ccc;border-bottom:1px dotted #ccc;font-size:11px;">set name</span>{% endif %}</div>
        <div class="agent-card-meta">
          <span class="muted">deactivated</span>
          {% if profile.state and profile.state.updated_at %}<span class="relative-time" data-ts="{{ profile.state.updated_at }}">{{ profile.state.updated_at }}</span>{% endif %}
        </div>
      </div>
      <span onclick="deleteAgent('{{ profile.agent_id }}')" style="cursor:pointer;color:#c45a3c;display:flex;flex-shrink:0;padding:4px;" title="Remove agent (keeps knowledge and chat)"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12"/><path d="M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"/></svg></span>
    </div>
    {% endfor %}
    </div>
  </details>
  {% endif %}
</div>


<div id="tab-knowledge" class="tab-content">
  <div style="display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap;">
    <div style="background:#fff;border:1px solid #e0ddd6;border-radius:8px;padding:14px 20px;flex:1;min-width:100px;">
      <div style="font-size:28px;font-weight:800;">{{ all_knowledge|length }}</div>
      <div style="font-size:11px;color:#999;margin-top:2px;">Total Entries</div>
    </div>
    {% for cat, count in knowledge_categories_sorted[:4] %}
    <div style="background:#fff;border:1px solid #e0ddd6;border-radius:8px;padding:14px 20px;flex:1;min-width:100px;">
      <div style="font-size:28px;font-weight:800;">{{ count }}</div>
      <div style="font-size:11px;color:#999;margin-top:2px;">{{ cat|title }}</div>
    </div>
    {% endfor %}
  </div>

  <div style="margin-bottom:12px;">
    <input id="knowledge-search" type="text" placeholder="Search knowledge..." oninput="filterKnowledge()" style="width:100%;font-size:13px;padding:10px 14px;border:1px solid #e0ddd6;border-radius:8px;background:#fff;">
  </div>

  <div id="knowledge-cat-pills" style="display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap;">
    <span class="k-pill active" onclick="setKnowledgeCategory('all', this)">All <span style="font-size:10px;color:#888;margin-left:2px;">{{ all_knowledge|length }}</span></span>
    {% for cat, count in knowledge_categories_sorted %}
    <span class="k-pill" onclick="setKnowledgeCategory('{{ cat }}', this)">{{ cat }} <span style="font-size:10px;color:#bbb;margin-left:2px;">{{ count }}</span></span>
    {% endfor %}
  </div>

  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <div class="section-title" style="margin:0;">
      <span id="knowledge-showing">{{ all_knowledge|length }}</span> entries
    </div>
    <div style="display:flex;gap:4px;">
      <span id="k-sort-confidence" onclick="setKnowledgeSort('confidence')" style="font-size:10px;color:#999;cursor:pointer;border:1px solid #e0ddd6;padding:2px 8px;border-radius:4px;background:#1a1a1a;color:#fff;">by confidence</span>
      <span id="k-sort-alpha" onclick="setKnowledgeSort('alpha')" style="font-size:10px;color:#999;cursor:pointer;border:1px solid #e0ddd6;padding:2px 8px;border-radius:4px;background:#fff;">A-Z</span>
      <span id="k-sort-newest" onclick="setKnowledgeSort('newest')" style="font-size:10px;color:#999;cursor:pointer;border:1px solid #e0ddd6;padding:2px 8px;border-radius:4px;background:#fff;">newest</span>
    </div>
  </div>

  <div id="knowledge-cards">
    {% for k in all_knowledge %}
    <div class="k-card" data-category="{{ k.category }}" data-subject="{{ k.subject|lower }}" data-object="{{ k.object|lower if k.object else '' }}" data-predicate="{{ k.predicate|lower if k.predicate else '' }}" data-confidence="{{ k.confidence }}" data-id="{{ k.id }}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:4px;">
        <div style="font-size:14px;font-weight:600;">{{ k.subject }}</div>
        <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
          <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;padding:2px 8px;border-radius:4px;background:#f5f3ef;color:#888;">{{ k.category }}</span>
          <div style="display:flex;align-items:center;gap:4px;">
            <div style="width:36px;height:5px;background:#eae7e0;border-radius:3px;overflow:hidden;"><div style="height:100%;background:#2ecc71;border-radius:3px;width:{{ (k.confidence * 100)|int }}%;"></div></div>
            <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#999;">{{ "%.0f"|format(k.confidence * 100) }}%</span>
          </div>
        </div>
      </div>
      {% if k.predicate %}<div style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#c45a3c;margin-bottom:4px;">{{ k.predicate }}</div>{% endif %}
      {% if k.object %}
      <div class="k-object-truncated" style="font-size:13px;color:#666;line-height:1.5;max-height:3em;overflow:hidden;position:relative;">{{ k.object }}</div>
      {% if k.object|length > 150 %}
      <span class="k-expand" onclick="toggleKnowledgeCard(this)" style="font-size:11px;color:#c45a3c;cursor:pointer;">show more</span>
      {% endif %}
      {% endif %}
      <div style="display:flex;gap:12px;margin-top:6px;font-size:11px;color:#ccc;">
        {% if k.source %}<span>{{ k.source }}</span>{% endif %}
        {% if k.validated_by %}<span>validated: {{ k.validated_by }}</span>{% endif %}
      </div>
    </div>
    {% endfor %}
    {% if not all_knowledge %}<div class="muted">No knowledge yet</div>{% endif %}
  </div>
</div>

<div id="tab-system" class="tab-content">
  <!-- Sub-tab navigation -->
  <div style="display:flex; gap:24px; border-bottom:1px solid #e0ddd6; margin-bottom:20px; padding-bottom:0;">
    <div class="sys-subtab active" data-subtab="health" onclick="showSystemSubTab('health', this)" style="cursor:pointer; padding:8px 0; font-size:13px; font-weight:700; color:#c45a3c; border-bottom:2px solid #c45a3c; margin-bottom:-2px;">Health</div>
    <div class="sys-subtab" data-subtab="admin" onclick="showSystemSubTab('admin', this)" style="cursor:pointer; padding:8px 0; font-size:13px; font-weight:400; color:#999; border-bottom:none; margin-bottom:0;">Admin</div>
  </div>

  <!-- Health sub-tab -->
  <div id="sys-health" class="sys-subtab-content" style="display:block;">
    <div style="text-transform:uppercase; font-size:11px; color:#aaa; letter-spacing:1px; margin-bottom:12px; font-weight:600;">Health</div>
    <div class="sys-health-grid" style="display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; margin-bottom:24px;">
      <div style="background:#fff; border:1px solid #e0ddd6; border-radius:10px; padding:16px;">
        <div style="font-size:11px; color:#999; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px;">Uptime</div>
        <div id="sys-uptime" style="font-size:22px; font-weight:700; font-family:'IBM Plex Mono',monospace;">-</div>
      </div>
      <div style="background:#fff; border:1px solid #e0ddd6; border-radius:10px; padding:16px;">
        <div style="font-size:11px; color:#999; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px;">Database</div>
        <div style="font-size:22px; font-weight:700; font-family:'IBM Plex Mono',monospace;">{{ "%.1f"|format(stats.db_size_bytes / 1048576) }} MB</div>
      </div>
      <div style="background:#fff; border:1px solid #e0ddd6; border-radius:10px; padding:16px;">
        <div style="font-size:11px; color:#999; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px;">Records</div>
        <div style="font-size:22px; font-weight:700; font-family:'IBM Plex Mono',monospace;">{{ "{:,}".format(stats.chat_total + stats.events_total + stats.knowledge_active) }}</div>
        <div style="font-size:11px; color:#999; margin-top:4px;">{{ stats.chat_total }} chat / {{ stats.events_total }} events / {{ stats.knowledge_active }} knowledge</div>
      </div>
      <div style="background:#fff; border:1px solid #e0ddd6; border-radius:10px; padding:16px;">
        <div style="font-size:11px; color:#999; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px;">Active Sessions</div>
        <div style="font-size:22px; font-weight:700; font-family:'IBM Plex Mono',monospace; color:#2ecc71;">{{ sessions|selectattr('ended_at', 'none')|list|length }}</div>
        <div style="font-size:11px; color:#999; margin-top:4px;">of {{ agent_profiles|length }} agents</div>
      </div>
    </div>

    <div style="text-transform:uppercase; font-size:11px; color:#aaa; letter-spacing:1px; margin-bottom:12px; font-weight:600;">Working Memory</div>
    <div class="sys-wm-grid" style="display:grid; grid-template-columns:repeat(2, 1fr); gap:12px; margin-bottom:24px;">
      {% for agent_id, wm_data in wm_by_agent.items() %}
      <div style="background:#fff; border:1px solid #e0ddd6; border-radius:10px; padding:16px;">
        <div style="font-family:'IBM Plex Mono',monospace; font-weight:600; margin-bottom:8px;">{{ agent_id }} <span style="color:#999; font-weight:400;">({{ wm_data.session_id }})</span></div>
        {% for k, v in wm_data.items.items() %}
        <div style="margin-bottom:4px;"><span style="color:#c45a3c; font-family:'IBM Plex Mono',monospace; font-size:12px;">{{ k }}</span> <span style="font-family:'IBM Plex Mono',monospace; font-size:12px;">{{ v }}</span></div>
        {% endfor %}
        {% if not wm_data.items %}<div style="color:#999; font-size:12px;">(empty)</div>{% endif %}
      </div>
      {% endfor %}
    </div>
    {% if not wm_by_agent %}<div class="muted" style="margin-bottom:24px;">No active sessions</div>{% endif %}

    <div style="text-transform:uppercase; font-size:11px; color:#aaa; letter-spacing:1px; margin-bottom:12px; font-weight:600;">Onboarding</div>
    <div style="background:#fff; border:1px solid #e0ddd6; border-radius:10px; padding:16px; margin-bottom:24px;">
      <div style="display:flex; gap:10px; align-items:end; margin-bottom:12px;">
        <div>
          <label for="onboarding-agent" style="font-size:11px; color:#999; text-transform:uppercase; letter-spacing:0.5px; display:block; margin-bottom:4px;">Agent</label>
          <input id="onboarding-agent" list="agent-ids" value="{{ default_onboarding_agent }}" placeholder="agent-id eingeben" style="padding:6px 10px; border:1px solid #e0ddd6; border-radius:6px; font-family:'Figtree',sans-serif; font-size:13px; width:180px;">
        </div>
        <button onclick="loadOnboardingPrompt()" style="padding:8px 20px; background:#1a1a1a; color:#fff; border:none; border-radius:6px; font-size:12px; cursor:pointer; font-family:'Figtree',sans-serif;">Load</button>
        <button onclick="copyText(this, 'onboarding-prompt')" style="padding:8px 20px; background:#1a1a1a; color:#fff; border:none; border-radius:6px; font-size:12px; cursor:pointer; font-family:'Figtree',sans-serif;">Copy</button>
      </div>
      <pre id="onboarding-prompt" style="background:#faf9f6; border:1px solid #e0ddd6; border-radius:8px; padding:12px; font-family:'IBM Plex Mono',monospace; font-size:12px; white-space:pre-wrap; word-break:break-word; max-height:300px; overflow-y:auto;">{{ onboarding_bundle.prompt if onboarding_bundle else '(select an agent)' }}</pre>
    </div>
  </div>

  <!-- Admin sub-tab -->
  <div id="sys-admin" class="sys-subtab-content" style="display:none;">
    <div style="text-transform:uppercase; font-size:11px; color:#aaa; letter-spacing:1px; margin-bottom:12px; font-weight:600;">Maintenance Actions</div>
    <div class="sys-maint-grid" style="display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; margin-bottom:24px;">
      <div style="background:#fff; border:1px solid #e0ddd6; border-radius:10px; padding:16px;">
        <div style="font-weight:600; margin-bottom:6px;">Cleanup Tasks</div>
        <div style="font-size:12px; color:#999; margin-bottom:12px;">Remove completed and failed tasks older than 7 days.</div>
        <button onclick="runMaintenance(this, 'tasks')" style="padding:8px 20px; background:#1a1a1a; color:#fff; border:none; border-radius:6px; font-size:12px; cursor:pointer; font-family:'Figtree',sans-serif;">Run</button>
      </div>
      <div style="background:#fff; border:1px solid #e0ddd6; border-radius:10px; padding:16px;">
        <div style="font-weight:600; margin-bottom:6px;">Knowledge Decay</div>
        <div style="font-size:12px; color:#999; margin-bottom:12px;">Decay confidence of stale knowledge entries.</div>
        <button onclick="runMaintenance(this, 'knowledge')" style="padding:8px 20px; background:#1a1a1a; color:#fff; border:none; border-radius:6px; font-size:12px; cursor:pointer; font-family:'Figtree',sans-serif;">Run</button>
      </div>
      <div style="background:#fff; border:1px solid #e0ddd6; border-radius:10px; padding:16px;">
        <div style="font-weight:600; margin-bottom:6px;">Purge Observations</div>
        <div style="font-size:12px; color:#999; margin-bottom:12px;">Delete observation records older than 48 hours.</div>
        <button onclick="runMaintenance(this, 'observations')" style="padding:8px 20px; background:#1a1a1a; color:#fff; border:none; border-radius:6px; font-size:12px; cursor:pointer; font-family:'Figtree',sans-serif;">Run</button>
      </div>
    </div>

    <div style="text-transform:uppercase; font-size:11px; color:#aaa; letter-spacing:1px; margin-bottom:12px; font-weight:600;">Maintenance Log</div>
    <div id="maintenance-log" style="background:#fff; border:1px solid #e0ddd6; border-radius:10px; padding:16px; margin-bottom:24px; font-family:'IBM Plex Mono',monospace; font-size:12px; min-height:60px;">
      <div class="muted" style="text-align:center;">No maintenance runs yet</div>
    </div>

    <div style="text-transform:uppercase; font-size:11px; color:#aaa; letter-spacing:1px; margin-bottom:12px; font-weight:600;">Episodes</div>
    <div style="background:#fff; border:1px solid #e0ddd6; border-radius:10px; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <tr>
          <th style="background:#faf9f6; border-bottom:1px solid #e0ddd6; padding:10px 14px; font-size:11px; text-transform:uppercase; color:#999; text-align:left;">#</th>
          <th style="background:#faf9f6; border-bottom:1px solid #e0ddd6; padding:10px 14px; font-size:11px; text-transform:uppercase; color:#999; text-align:left;">Title</th>
          <th style="background:#faf9f6; border-bottom:1px solid #e0ddd6; padding:10px 14px; font-size:11px; text-transform:uppercase; color:#999; text-align:left;">Agent</th>
          <th style="background:#faf9f6; border-bottom:1px solid #e0ddd6; padding:10px 14px; font-size:11px; text-transform:uppercase; color:#999; text-align:left;">Category</th>
          <th style="background:#faf9f6; border-bottom:1px solid #e0ddd6; padding:10px 14px; font-size:11px; text-transform:uppercase; color:#999; text-align:left;">Outcome</th>
          <th style="background:#faf9f6; border-bottom:1px solid #e0ddd6; padding:10px 14px; font-size:11px; text-transform:uppercase; color:#999; text-align:left;">Tags</th>
        </tr>
        {% for ep in all_episodes %}
        <tr style="border-bottom:1px solid #f0ede8;">
          <td style="padding:10px 14px; font-size:13px;">{{ ep.id }}</td>
          <td style="padding:10px 14px; font-size:13px;">{{ ep.title }}</td>
          <td style="padding:10px 14px; font-size:13px; font-family:'IBM Plex Mono',monospace;">{{ ep.agent_id }}</td>
          <td style="padding:10px 14px; font-size:13px;"><span style="padding:2px 8px; border-radius:10px; font-size:11px; background:#f0ede8; color:#666;">{{ ep.category }}</span></td>
          <td style="padding:10px 14px; font-size:13px;">
            {% if ep.outcome == 'success' %}<span style="padding:2px 8px; border-radius:10px; font-size:11px; background:#e8f5e9; color:#2e7d32;">{{ ep.outcome }}</span>
            {% elif ep.outcome == 'failure' %}<span style="padding:2px 8px; border-radius:10px; font-size:11px; background:#fbe9e7; color:#c62828;">{{ ep.outcome }}</span>
            {% else %}<span style="padding:2px 8px; border-radius:10px; font-size:11px; background:#f0ede8; color:#666;">{{ ep.outcome or '...' }}</span>{% endif %}
          </td>
          <td style="padding:10px 14px; font-size:13px;">{% if ep.tags %}{% for tag in ep.tags_list %}<span class="tag">{{ tag }}</span>{% endfor %}{% endif %}</td>
        </tr>
        {% endfor %}
      </table>
      {% if not all_episodes %}<div class="muted" style="padding:20px; text-align:center;">No episodes yet</div>{% endif %}
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
const TAB_REDIRECTS = { 'working': 'system', 'episodes': 'system', 'onboarding': 'system', 'admin': 'system' };
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
  lastRealChannel: '{{ default_chat_channel if default_chat_channel != "all" else "general" }}',
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

function showSystemSubTab(name, el) {
  document.querySelectorAll('.sys-subtab-content').forEach(n => n.style.display = 'none');
  document.querySelectorAll('.sys-subtab').forEach(n => {
    n.classList.remove('active');
    n.style.color = '#999';
    n.style.fontWeight = '400';
    n.style.borderBottom = 'none';
    n.style.marginBottom = '0';
  });
  document.getElementById('sys-' + name).style.display = 'block';
  if (el) {
    el.classList.add('active');
    el.style.color = '#c45a3c';
    el.style.fontWeight = '700';
    el.style.borderBottom = '2px solid #c45a3c';
    el.style.marginBottom = '-2px';
  }
  window.location.hash = name === 'health' ? 'system' : 'system/' + name;
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

async function runMaintenance(btn, only) {
  if (btn.dataset.confirm !== 'yes') {
    btn.textContent = 'Confirm?';
    btn.style.background = '#c45a3c';
    btn.dataset.confirm = 'yes';
    setTimeout(function() { btn.textContent = 'Run'; btn.style.background = '#1a1a1a'; delete btn.dataset.confirm; }, 3000);
    return;
  }
  btn.textContent = '...';
  btn.disabled = true;
  delete btn.dataset.confirm;
  try {
    var res = await postJson('/api/maintenance', { only: only });
    var log = document.getElementById('maintenance-log');
    var ts = new Date().toLocaleTimeString();
    var counts = Object.entries(res).filter(function(e) { return e[0] !== 'ok'; }).map(function(e) { return e[0] + ': ' + e[1]; }).join(', ');
    var line = document.createElement('div');
    var tsSpan = document.createElement('span');
    tsSpan.style.color = '#999';
    tsSpan.textContent = ts;
    line.appendChild(tsSpan);
    line.appendChild(document.createTextNode(' ' + only + ': ' + counts));
    if (log.querySelector('.muted')) log.textContent = '';
    log.appendChild(line);
  } catch (e) {
    var log = document.getElementById('maintenance-log');
    var ts = new Date().toLocaleTimeString();
    var line = document.createElement('div');
    var tsSpan = document.createElement('span');
    tsSpan.style.color = '#999';
    tsSpan.textContent = ts;
    var errSpan = document.createElement('span');
    errSpan.style.color = '#b33a3a';
    errSpan.textContent = 'ERROR: ' + e.message;
    line.appendChild(tsSpan);
    line.appendChild(document.createTextNode(' '));
    line.appendChild(errSpan);
    if (log.querySelector('.muted')) log.textContent = '';
    log.appendChild(line);
  }
  btn.textContent = 'Run';
  btn.style.background = '#1a1a1a';
  btn.disabled = false;
}

async function loadUptime() {
  try {
    var r = await fetch('/api/status');
    var d = await r.json();
    var s = Math.floor(d.uptime_seconds || 0);
    var days = Math.floor(s / 86400);
    var hours = Math.floor((s % 86400) / 3600);
    var mins = Math.floor((s % 3600) / 60);
    var text = '';
    if (days > 0) text += days + 'd ';
    if (hours > 0 || days > 0) text += hours + 'h';
    else text += mins + 'm';
    document.getElementById('sys-uptime').textContent = text.trim();
  } catch(e) { document.getElementById('sys-uptime').textContent = '-'; }
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
  var postChannel = nextChannel === 'all' ? (chatState.lastRealChannel || 'general') : nextChannel;
  if (nextChannel !== 'all') chatState.lastRealChannel = nextChannel;
  document.getElementById('chat-channel').value = postChannel;
  document.getElementById('chat-active-title').textContent = nextChannel === 'all' ? 'All Channels' : ('#' + nextChannel);
  var hint = document.getElementById('chat-post-channel-label');
  if (hint) hint.textContent = '#' + postChannel;
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

function getChannelSort() {
  return localStorage.getItem('ponder_channel_sort') || 'activity';
}
function toggleChannelSort() {
  var current = getChannelSort();
  var next = current === 'activity' ? 'alpha' : 'activity';
  localStorage.setItem('ponder_channel_sort', next);
  document.getElementById('chat-sort-toggle').textContent = next === 'activity' ? 'by activity' : 'A-Z';
  renderChatChannelTabs();
}
(function() {
  var s = getChannelSort();
  var el = document.getElementById('chat-sort-toggle');
  if (el) el.textContent = s === 'activity' ? 'by activity' : 'A-Z';
})();

function getHiddenChannels() {
  try { return JSON.parse(localStorage.getItem('ponder_hidden_channels') || '[]'); } catch(e) { return []; }
}
function setHiddenChannels(list) {
  localStorage.setItem('ponder_hidden_channels', JSON.stringify(list));
}
function hideChannel(ch) {
  var hidden = getHiddenChannels();
  if (hidden.indexOf(ch) === -1) hidden.push(ch);
  setHiddenChannels(hidden);
  if (chatState.activeChannel === ch) setActiveChatChannel('all');
  renderChatChannelTabs();
}
function unhideChannel(ch) {
  setHiddenChannels(getHiddenChannels().filter(function(c) { return c !== ch; }));
  renderChatChannelTabs();
}

function renderChatChannelTabs() {
  const host = document.getElementById('chat-channel-tabs');
  const hidden = getHiddenChannels();
  const totalMessages = chatState.channelSummaries.reduce((sum, item) => sum + (item.message_count || 0), 0);
  const allTab = `
    <button class="chat-channel-tab ${chatState.activeChannel === 'all' ? 'active' : ''}" type="button" data-channel="all">
      <span class="chat-channel-name">All Channels</span>
      <span class="chat-channel-count">${totalMessages}</span>
    </button>
  `;
  var visible = chatState.channelSummaries.filter((item) => item.channel !== 'all' && hidden.indexOf(item.channel) === -1);
  if (getChannelSort() === 'alpha') {
    visible = visible.slice().sort((a, b) => a.channel.localeCompare(b.channel));
  }
  const hiddenItems = chatState.channelSummaries.filter((item) => item.channel !== 'all' && hidden.indexOf(item.channel) !== -1);

  const channelTabs = visible.map((item) => {
    const channel = escapeHtml(item.channel);
    const activeClass = item.channel === chatState.activeChannel ? 'active' : '';
    return `
      <button class="chat-channel-tab ${activeClass}" type="button" data-channel="${channel}">
        <span class="chat-channel-name">#${channel}</span>
        <span style="display:flex;align-items:center;gap:6px;">
          <span class="chat-channel-count">${item.message_count}</span>
          <span class="chat-channel-hide" onclick="event.stopPropagation();hideChannel('${channel}')" title="Hide channel" style="color:#ccc;font-size:14px;line-height:1;cursor:pointer;">&times;</span>
        </span>
      </button>
    `;
  }).join('');

  var hiddenHtml = '';
  if (hiddenItems.length) {
    var hiddenTabs = hiddenItems.map((item) => {
      const channel = escapeHtml(item.channel);
      return `
        <button class="chat-channel-tab" type="button" style="opacity:0.5;" onclick="unhideChannel('${channel}')">
          <span class="chat-channel-name">#${channel}</span>
          <span class="chat-channel-count">${item.message_count}</span>
        </button>
      `;
    }).join('');
    hiddenHtml = `
      <details style="margin-top:8px;">
        <summary style="font-size:11px;color:#999;cursor:pointer;">Hidden (${hiddenItems.length})</summary>
        <div style="margin-top:4px;display:flex;flex-direction:column;gap:4px;">${hiddenTabs}</div>
      </details>
    `;
  }

  host.innerHTML = allTab + channelTabs + hiddenHtml;
}

function renderMarkdown(text) {
  var s = escapeHtml(text);
  s = s.replace(new RegExp('```([\\s\\S]*?)```', 'g'), '<pre style="background:#f5f3ef;padding:8px 10px;border-radius:6px;margin:4px 0;overflow-x:auto;font-size:12px;">$1</pre>');
  s = s.replace(new RegExp('`([^`]+)`', 'g'), '<code style="background:#f5f3ef;padding:1px 5px;border-radius:3px;font-size:12px;">$1</code>');
  s = s.replace(new RegExp('[*][*]([^*]+)[*][*]', 'g'), '<strong>$1</strong>');
  s = s.replace(new RegExp('[*]([^*]+)[*]', 'g'), '<em>$1</em>');
  s = s.replace(new RegExp('^- (.+)$', 'gm'), '<div style="padding-left:12px;">&bull; $1</div>');
  s = s.replace(new RegExp('^\\d+[.] (.+)$', 'gm'), function(m, p1) { return '<div style="padding-left:12px;">' + m.match(new RegExp('^\\d+'))[0] + '. ' + p1 + '</div>'; });
  var imgIdx = 0, imgStore = {};
  s = s.replace(new RegExp('(https?://[^\\s<]+[.](png|jpg|jpeg|gif|webp|svg)([?][^\\s<]*)?)', 'gi'), function(url) {
    var key = '%%IMG' + (imgIdx++) + '%%';
    imgStore[key] = '<img src="' + url + '" style="max-width:100%;max-height:300px;border-radius:6px;margin:4px 0;display:block;" loading="lazy">';
    return key;
  });
  s = s.replace(new RegExp('(https?://[^\\s<]+)', 'g'), '<a href="$1" target="_blank" rel="noopener" style="color:#c45a3c;word-break:break-all;">$1</a>');
  Object.keys(imgStore).forEach(function(key) { s = s.replace(key, imgStore[key]); });
  s = s.replace(new RegExp('\\n', 'g'), '<br>');
  return s;
}

var _agentColorCache = {};
var _agentColors = ['#c45a3c','#2e7d6f','#6b5b95','#d4791c','#3a7bbf','#8b6b3d','#c74375','#4a8c5c','#7b5ea7','#b8860b'];
function agentColor(name) {
  if (!name) return '#1a1a1a';
  if (_agentColorCache[name]) return _agentColorCache[name];
  var h = 0;
  for (var i = 0; i < name.length; i++) h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  _agentColorCache[name] = _agentColors[Math.abs(h) % _agentColors.length];
  return _agentColorCache[name];
}

function renderChatMessages(messages) {
  const feed = getChatFeed();
  const watchAgent = document.getElementById('chat-watch-agent').value.trim().toLowerCase();
  if (!messages.length) {
    feed.innerHTML = '<div class="muted">No chat messages yet.</div>';
    return;
  }

  var prevSender = null;
  feed.innerHTML = messages.map((msg, i) => {
    const sender = escapeHtml(msg.sender_agent);
    const target = escapeHtml(msg.target_agent || '');
    const created = escapeHtml(msg.created_at);
    const isSelf = watchAgent && sender.toLowerCase() === watchAgent;
    const sameSender = msg.sender_agent === prevSender;
    prevSender = msg.sender_agent;
    const cls = (isSelf ? 'msg self' : 'msg') + (sameSender ? ' msg-continuation' : '');
    const senderColor = agentColor(msg.sender_agent);
    const targetHtml = target
      ? `<span class="msg-arrow">&rarr;</span><span class="msg-to" style="color:${agentColor(msg.target_agent)}">${target}</span>`
      : '';
    const headerHtml = sameSender
      ? `<div class="msg-head msg-head-mini"><span class="msg-time relative-time" data-ts="${created}">${formatRelativeTime(msg.created_at)}</span></div>`
      : `<div class="msg-head"><span class="msg-from" style="color:${senderColor}">${sender}</span>${targetHtml}<span class="msg-time relative-time" data-ts="${created}">${formatRelativeTime(msg.created_at)}</span></div>`;
    return `
      <div class="${cls}" data-id="${msg.id}">
        ${headerHtml}
        <div class="msg-body">${renderMarkdown(msg.body)}</div>
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

function getChatNickname() {
  var nick = localStorage.getItem('ponder_nickname') || 'Human';
  document.getElementById('chat-sender').value = nick;
  document.getElementById('chat-sender-label').textContent = nick;
  return nick;
}
function changeChatNickname() {
  var current = localStorage.getItem('ponder_nickname') || 'Human';
  var nick = prompt('Your chat nickname:', current);
  if (nick !== null && nick.trim()) {
    localStorage.setItem('ponder_nickname', nick.trim());
    getChatNickname();
  }
}
getChatNickname();

async function renameAgent(agentId, el) {
  var current = el.textContent === 'set name' ? '' : el.textContent;
  var name = prompt('Display name for ' + agentId + ' (leave empty to clear):', current);
  if (name === null) return;
  try {
    var newName = name.trim() || agentId;
    await postJson('/api/agents/' + encodeURIComponent(agentId), { display_name: newName });
    if (newName === agentId) {
      el.textContent = 'set name';
      el.style.color = '#ccc';
      el.style.fontSize = '11px';
    } else {
      el.textContent = newName;
      el.style.color = '';
      el.style.fontSize = '';
    }
  } catch(e) {
    alert('Failed: ' + e.message);
  }
}

async function deleteAgent(agentId) {
  if (!confirm('Remove ' + agentId + '? Chat messages, knowledge, and events will be kept.')) return;
  try {
    var res = await fetch('/api/agents/' + encodeURIComponent(agentId), { method: 'DELETE' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var card = document.getElementById('agent-card-' + agentId);
    if (card) card.remove();
  } catch(e) {
    alert('Failed: ' + e.message);
  }
}

async function sendChatMessage() {
  const sender = document.getElementById('chat-sender').value.trim();
  const target = document.getElementById('chat-target').value.trim();
  const channel = document.getElementById('chat-channel').value.trim() || (chatState.activeChannel !== 'all' ? chatState.activeChannel : 'general');
  const body = document.getElementById('chat-body').value.trim();
  const status = document.getElementById('chat-status');
  if (!sender) {
    changeChatNickname();
    return;
  }
  if (!body) {
    status.textContent = 'Message is empty.';
    return;
  }
  if (channel.toLowerCase() === 'all') {
    status.textContent = '"all" is reserved. Pick a channel name.';
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
  var hashState = getHashState();
  if (hashState.tab === 'chat' && hashState.chatChannel) {
    setActiveChatChannel(hashState.chatChannel, { refresh: false, syncHash: false });
  }
  showTab(hashState.tab, findTabButton(hashState.tab), { setHash: false });
  if (hashState.tab === 'system') {
    var hash = window.location.hash.replace(/^#/, '');
    var subTab = hash.indexOf('/') !== -1 ? hash.split('/')[1] : 'health';
    var btn = document.querySelector('.sys-subtab[data-subtab="' + subTab + '"]');
    showSystemSubTab(subTab, btn);
    loadUptime();
  }
}

async function loadOnboardingPrompt() {
  var agent = document.getElementById('onboarding-agent').value.trim() || 'agent';
  var prompt = document.getElementById('onboarding-prompt');
  prompt.textContent = 'Loading...';
  try {
    var res = await fetch('/api/onboarding/' + encodeURIComponent(agent));
    var data = await res.json();
    if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
    prompt.textContent = data.prompt;
  } catch (err) {
    prompt.textContent = 'Error: ' + err.message;
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
var knowledgeState = { category: 'all', sort: 'confidence' };

function filterKnowledge() {
  var q = (document.getElementById('knowledge-search').value || '').toLowerCase();
  var cards = document.querySelectorAll('#knowledge-cards .k-card');
  var shown = 0;
  cards.forEach(function(card) {
    var cat = card.getAttribute('data-category');
    var matchesCat = knowledgeState.category === 'all' || cat === knowledgeState.category;
    var matchesSearch = !q || card.getAttribute('data-subject').indexOf(q) !== -1 || card.getAttribute('data-object').indexOf(q) !== -1 || card.getAttribute('data-predicate').indexOf(q) !== -1 || cat.indexOf(q) !== -1;
    if (matchesCat && matchesSearch) { card.hidden = false; shown++; } else { card.hidden = true; }
  });
  var el = document.getElementById('knowledge-showing');
  if (el) el.textContent = shown;
}

function setKnowledgeCategory(cat, el) {
  knowledgeState.category = cat;
  document.querySelectorAll('#knowledge-cat-pills .k-pill').forEach(function(p) { p.classList.remove('active'); });
  if (el) el.classList.add('active');
  filterKnowledge();
}

function setKnowledgeSort(sort) {
  knowledgeState.sort = sort;
  ['confidence', 'alpha', 'newest'].forEach(function(s) {
    var btn = document.getElementById('k-sort-' + s);
    if (btn) { btn.style.background = s === sort ? '#1a1a1a' : '#fff'; btn.style.color = s === sort ? '#fff' : '#999'; }
  });
  var container = document.getElementById('knowledge-cards');
  var cards = Array.from(container.querySelectorAll('.k-card'));
  cards.sort(function(a, b) {
    if (sort === 'confidence') return parseFloat(b.getAttribute('data-confidence')) - parseFloat(a.getAttribute('data-confidence'));
    if (sort === 'alpha') return a.getAttribute('data-subject').localeCompare(b.getAttribute('data-subject'));
    if (sort === 'newest') return parseInt(b.getAttribute('data-id')) - parseInt(a.getAttribute('data-id'));
    return 0;
  });
  cards.forEach(function(card) { container.appendChild(card); });
}

function toggleKnowledgeCard(el) {
  var obj = el.previousElementSibling;
  if (obj.style.maxHeight === 'none') {
    obj.style.maxHeight = '3em';
    el.textContent = 'show more';
  } else {
    obj.style.maxHeight = 'none';
    el.textContent = 'show less';
  }
}

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
                parsed = json.loads(e["data"]) if isinstance(e["data"], str) else e["data"]
                e["data_parsed"] = parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                pass
    return events


@app.route("/")
def dashboard():
    # First-run wizard: show setup if no agents registered
    agent_profiles = mem.list_agent_profiles()
    if not agent_profiles:
        return render_template_string(WIZARD_HTML, ponder_url=PONDER_URL)

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

    all_knowledge = mem.recall(limit=1000)
    pinned_notes = [k for k in all_knowledge if k.get("category") == "pinned"]
    knowledge_categories = {}
    for k in all_knowledge:
        cat = k.get("category", "other")
        knowledge_categories[cat] = knowledge_categories.get(cat, 0) + 1
    knowledge_categories_sorted = sorted(knowledge_categories.items(), key=lambda x: x[1], reverse=True)
    agent_profiles = mem.list_agent_profiles()
    now = datetime.now(timezone.utc)
    agents_active, agents_inactive, agents_deactivated = [], [], []
    for p in agent_profiles:
        updated = None
        if p.get("state") and p["state"].get("updated_at"):
            try:
                ts = p["state"]["updated_at"]
                updated = datetime.fromisoformat(ts.replace(" ", "T") + ("+00:00" if "+" not in ts and "Z" not in ts else "").replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        if updated and (now - updated) > timedelta(days=7):
            agents_deactivated.append(p)
        elif updated and (now - updated) > timedelta(hours=72):
            agents_inactive.append(p)
        else:
            agents_active.append(p)
    # Build agent leaderboard
    agent_scores = {}
    for p in agent_profiles:
        aid = p["agent_id"]
        agent_scores[aid] = {"agent_id": aid, "display_name": p.get("display_name", aid), "messages": 0, "events": 0, "tasks_created": 0, "tasks_done": 0, "score": 0}
    all_chat = mem.get_chat_messages(limit=5000)
    for m in all_chat:
        s = m.get("sender_agent", "")
        if s in agent_scores:
            agent_scores[s]["messages"] += 1
    all_events_full = mem.get_latest_events(limit=5000)
    for e in all_events_full:
        s = e.get("source_agent", "")
        if s in agent_scores:
            agent_scores[s]["events"] += 1
    all_tasks_full = mem.list_tasks(include_done=True, limit=500)
    for t in all_tasks_full:
        cb = t.get("created_by", "")
        if cb in agent_scores:
            agent_scores[cb]["tasks_created"] += 1
        at = t.get("assigned_to", "")
        if at in agent_scores and t.get("status") in ("done", "completed", "success"):
            agent_scores[at]["tasks_done"] += 1
    for a in agent_scores.values():
        a["score"] = a["messages"] * 2 + int(a["events"] * 0.1) + a["tasks_created"] * 10 + a["tasks_done"] * 15
    leaderboard = sorted(agent_scores.values(), key=lambda x: x["score"], reverse=True)

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
        agents_active=agents_active,
        agents_inactive=agents_inactive,
        agents_deactivated=agents_deactivated,
        leaderboard=leaderboard,
        sessions=sessions[:20],
        wm_by_agent=wm_by_agent,
        all_episodes=all_episodes,
        all_knowledge=all_knowledge,
        knowledge_categories_sorted=knowledge_categories_sorted,
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


@app.route("/api/agents/<agent_id>", methods=["DELETE"])
def api_agents_delete(agent_id):
    mem.delete_agent(agent_id)
    return jsonify({"ok": True})


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
    channel = data.get("channel", "general").strip().lower()
    if channel == "all":
        return jsonify({"error": "'all' is a reserved channel name"}), 400
    message_id = mem.append_chat_message(
        sender_agent=data["sender_agent"],
        body=data["body"],
        channel=channel,
        target_agent=data.get("target_agent"),
        metadata=data.get("metadata"),
    )
    return jsonify({"ok": True, "id": message_id})


@app.route("/api/status")
def api_status():
    uptime = (datetime.now(timezone.utc) - STARTUP_TIME).total_seconds()
    return jsonify({"ok": True, "uptime_seconds": uptime, **mem.stats()})


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
    data = request.get_json(force=True) if request.data else {}
    only = data.get("only")
    result = {"ok": True}
    if not only or only == "wm":
        result["cleaned_wm"] = mem.cleanup_expired_wm()
    if not only or only == "tasks":
        result["cleaned_tasks"] = mem.cleanup_done_tasks(days=7)
    if not only or only == "knowledge":
        result["decayed_knowledge"] = mem.decay_knowledge(days_threshold=30, decay_rate=0.05)
    if not only or only == "observations":
        result["cleaned_observations"] = mem.cleanup_old_observations(days=30)
    return jsonify(result)


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

    log.info("Ponder daemon starting on %s:%d", host, PORT)
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
