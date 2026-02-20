#!/usr/bin/env python3
"""Agent Memory Daemon -- REST API for shared agent state.

Runs on localhost:9077 (mnemonic: 90 = memory, 77 = lucky).
Used by Nova (Python), Claude (CLI/curl), and Dennis (browser).

Start:  python daemon.py
Stop:   kill $(cat ~/.openclaw/agent-memory/daemon.pid)

API:
  GET  /                         Dashboard (HTML)
  GET  /api/status               Stats and health
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
import signal
import sys
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
<style>
  body { font-family: monospace; background: #1a1a2e; color: #e0e0e0; margin: 2em; }
  h1 { color: #0f3460; }
  h2 { color: #16213e; border-bottom: 1px solid #333; padding-bottom: 4px; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 2em; }
  th, td { text-align: left; padding: 6px 12px; border-bottom: 1px solid #333; }
  th { color: #e94560; }
  .status-idle { color: #888; }
  .status-working { color: #4ade80; }
  .status-waiting { color: #facc15; }
  .pending { color: #facc15; }
  .claimed { color: #60a5fa; }
  .done, .success { color: #4ade80; }
  .failed, .failure { color: #f87171; }
  .partial { color: #facc15; }
  .abandoned { color: #888; }
  .event-type { color: #c084fc; }
  .agent { color: #22d3ee; }
  .stats { display: flex; gap: 2em; margin-bottom: 2em; flex-wrap: wrap; }
  .stat { background: #16213e; padding: 12px 20px; border-radius: 8px; }
  .stat-value { font-size: 1.5em; color: #e94560; }
  .stat-label { font-size: 0.85em; color: #888; }
  pre { background: #16213e; padding: 8px; border-radius: 4px; overflow-x: auto; max-width: 600px; }
  .tabs { display: flex; gap: 0; margin-bottom: 2em; border-bottom: 2px solid #333; }
  .tab { padding: 10px 20px; cursor: pointer; color: #888; border-bottom: 2px solid transparent; margin-bottom: -2px; }
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
  .pinned { border: 1px solid #e94560; border-radius: 8px; padding: 16px 20px; margin-bottom: 2em; background: #16213e; position: relative; }
  .pinned h3 { color: #e94560; margin: 0 0 8px 0; font-size: 1.1em; }
  .pinned pre { background: #1a1a2e; padding: 12px; border-radius: 4px; white-space: pre-wrap; word-wrap: break-word; max-width: 100%; margin: 0; font-size: 0.9em; line-height: 1.5; }
  .pinned .copy-btn { position: absolute; top: 12px; right: 12px; background: #e94560; color: #fff; border: none; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 0.85em; }
  .pinned .copy-btn:hover { background: #c73650; }
  .pinned .copy-btn.copied { background: #4ade80; color: #1a1a2e; }
</style>
</head><body>
<h1>Agent Memory</h1>

<div class="stats">
  <div class="stat"><div class="stat-value">{{ stats.agents }}</div><div class="stat-label">Agents</div></div>
  <div class="stat"><div class="stat-value">{{ stats.tasks_pending }}</div><div class="stat-label">Pending Tasks</div></div>
  <div class="stat"><div class="stat-value">{{ stats.events_total }}</div><div class="stat-label">Events</div></div>
  <div class="stat"><div class="stat-value">{{ stats.sessions_active }}</div><div class="stat-label">Active Sessions</div></div>
  <div class="stat"><div class="stat-value">{{ stats.episodes_total }}</div><div class="stat-label">Episodes</div></div>
  <div class="stat"><div class="stat-value">{{ stats.knowledge_active }}</div><div class="stat-label">Knowledge</div></div>
  <div class="stat"><div class="stat-value">{{ "%.1f KB"|format(stats.db_size_bytes / 1024) }}</div><div class="stat-label">DB Size</div></div>
</div>

{% for note in pinned_notes %}
<div class="pinned">
  <h3>{{ note.subject }}</h3>
  <button class="copy-btn" onclick="copyNote(this, 'note-{{ note.id }}')">Copy</button>
  <pre id="note-{{ note.id }}">{{ note.object }}</pre>
</div>
{% endfor %}

<div class="tabs">
  <div class="tab active" onclick="showTab('overview')">Overview</div>
  <div class="tab" onclick="showTab('working')">Working Memory</div>
  <div class="tab" onclick="showTab('episodes')">Episodes</div>
  <div class="tab" onclick="showTab('knowledge')">Knowledge</div>
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
{% if not states %}<tr><td colspan="4" style="color:#666">No agents registered yet</td></tr>{% endif %}
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
{% if not tasks %}<tr><td colspan="6" style="color:#666">No tasks yet</td></tr>{% endif %}
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
{% if not events %}<tr><td colspan="6" style="color:#666">No events yet</td></tr>{% endif %}
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
{% if not sessions %}<tr><td colspan="4" style="color:#666">No sessions</td></tr>{% endif %}
</table>

<h2>Working Memory</h2>
{% for agent_id, wm_data in wm_by_agent.items() %}
<h3 class="agent">{{ agent_id }} ({{ wm_data.session_id }})</h3>
<table>
<tr><th>Key</th><th>Value</th></tr>
{% for k, v in wm_data.items.items() %}
<tr><td class="wm-key">{{ k }}</td><td>{{ v }}</td></tr>
{% endfor %}
{% if not wm_data.items %}<tr><td colspan="2" style="color:#666">(empty)</td></tr>{% endif %}
</table>
{% endfor %}
{% if not wm_by_agent %}<p style="color:#666">No active working memory</p>{% endif %}
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
{% if not all_episodes %}<tr><td colspan="7" style="color:#666">No episodes yet</td></tr>{% endif %}
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
{% if not all_knowledge %}<tr><td colspan="8" style="color:#666">No knowledge yet</td></tr>{% endif %}
</table>
</div>

<script>
function showTab(name) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}
function copyNote(btn, id) {
  var text = document.getElementById(id).textContent;
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
  btn.textContent = 'Copied!';
  btn.classList.add('copied');
  setTimeout(function() { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
}
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

    return render_template_string(
        DASHBOARD_HTML,
        stats=mem.stats(),
        states=mem.get_all_states(),
        tasks=mem.list_tasks(include_done=False, limit=20),
        events=mem.get_latest_events(limit=30),
        sessions=sessions[:20],
        wm_by_agent=wm_by_agent,
        all_episodes=all_episodes,
        all_knowledge=all_knowledge,
        pinned_notes=pinned_notes,
    )


# ── API: Status ──────────────────────────────────────────────

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
        limit=int(request.args.get("limit", 50)),
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

@app.route("/api/events", methods=["GET"])
def api_events_list():
    return jsonify(mem.get_events(
        since_id=int(request.args.get("since", 0)),
        event_type=request.args.get("type"),
        source_agent=request.args.get("source"),
        target_agent=request.args.get("target"),
        limit=int(request.args.get("limit", 100)),
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
        limit=int(request.args.get("limit", 20)),
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
        limit=int(request.args.get("limit", 20)),
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
        limit=int(request.args.get("limit", 50)),
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
