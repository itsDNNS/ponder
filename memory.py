"""Agent Memory -- Shared SQLite state layer for AI agent collaboration.

Core module providing direct SQLite access. Can be imported by Nova (Python)
or used by the daemon. Thread-safe, WAL mode, ACID transactions.

Usage:
    from memory import AgentMemory
    mem = AgentMemory()  # uses default path ~/.openclaw/agent-memory/agent.db
    mem.update_state("nova", "working", "Implementing smokeping collector")
    mem.append_event("commit", "nova", {"hash": "abc123", "message": "..."})
    mem.create_task("Fix CGA 401 bug", created_by="dennis", assigned_to="claude")
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_DB_PATH = Path(os.environ.get("AGENT_MEMORY_DB", str(Path.home() / ".openclaw" / "agent-memory" / "agent.db")))

DEFAULT_AGENT_PROFILES = {
    "claude": {
        "display_name": "Claude",
        "integration_mode": "native_or_file",
        "integration_target": "Use Claude-native startup instructions or CLAUDE.md only when that runtime explicitly supports it.",
        "native_feature": "Claude-compatible startup instructions",
        "onboarding_note": "Do not create Codex- or Nova-specific config files. Stay inside Claude-supported mechanisms.",
        "metadata": {"builtin": True},
    },
    "codex": {
        "display_name": "Codex",
        "integration_mode": "native",
        "integration_target": "Use Codex developer instructions, AGENTS.md, config.toml, or the host's Codex-native startup feature.",
        "native_feature": "Codex native instruction stack",
        "onboarding_note": "Do not create or rely on ~/.claude/CLAUDE.md. Use Codex-native features instead.",
        "metadata": {"builtin": True},
    },
    "nova": {
        "display_name": "Nova",
        "integration_mode": "native",
        "integration_target": "Use Nova's own persistent agent configuration or host-managed startup prompt.",
        "native_feature": "Nova native startup configuration",
        "onboarding_note": "Do not borrow file conventions from other agents. Keep onboarding inside Nova's own mechanism.",
        "metadata": {"builtin": True},
    },
}

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_state (
    agent_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'idle',
    current_task TEXT,
    context TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 0,
    assigned_to TEXT,
    payload TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    claimed_at TEXT,
    completed_at TEXT,
    result TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    source_agent TEXT NOT NULL,
    target_agent TEXT,
    data TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to, status);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source_agent, created_at);

CREATE TABLE IF NOT EXISTS agent_profiles (
    agent_id TEXT PRIMARY KEY,
    display_name TEXT,
    integration_mode TEXT NOT NULL DEFAULT 'native_or_session_bootstrap',
    integration_target TEXT,
    native_feature TEXT,
    onboarding_note TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL DEFAULT 'general',
    sender_agent TEXT NOT NULL,
    target_agent TEXT,
    body TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_chat_channel ON chat_messages(channel, id);
CREATE INDEX IF NOT EXISTS idx_chat_target ON chat_messages(target_agent, id);

-- ── Three-Tier Memory ────────────────────────────────────

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    summary TEXT,
    episode_id INTEGER REFERENCES episodes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS working_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    UNIQUE(agent_id, session_id, key)
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    session_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL DEFAULT 'general',
    tags TEXT,
    outcome TEXT,
    lessons TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS episode_events (
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    PRIMARY KEY (episode_id, event_id)
);

CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source TEXT,
    source_episode_id INTEGER REFERENCES episodes(id) ON DELETE SET NULL,
    tags TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    validated_by TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

-- ── Observations (tool-call tracking) ──────────────────

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    action TEXT,
    file_path TEXT,
    summary TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_observations_session ON observations(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_observations_agent ON observations(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_observations_tool ON observations(tool_name, created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
    summary, file_path, tool_name, action,
    content='observations', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS observations_ai AFTER INSERT ON observations BEGIN
    INSERT INTO observations_fts(rowid, summary, file_path, tool_name, action)
    VALUES (new.id, new.summary, new.file_path, new.tool_name, new.action);
END;

CREATE TRIGGER IF NOT EXISTS observations_ad AFTER DELETE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, summary, file_path, tool_name, action)
    VALUES ('delete', old.id, old.summary, old.file_path, old.tool_name, old.action);
END;

CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id, started_at);
CREATE INDEX IF NOT EXISTS idx_wm_agent_session ON working_memory(agent_id, session_id);
CREATE INDEX IF NOT EXISTS idx_episodes_agent ON episodes(agent_id, started_at);
CREATE INDEX IF NOT EXISTS idx_episodes_category ON episodes(category);
CREATE INDEX IF NOT EXISTS idx_knowledge_subject ON knowledge(subject, active);
CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge(category, active);
"""


class AgentMemory:
    """Shared agent memory backed by SQLite."""

    def __init__(self, db_path=None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _connect(self):
        class ManagedConnection(sqlite3.Connection):
            def __exit__(self, exc_type, exc_val, exc_tb):
                try:
                    return super().__exit__(exc_type, exc_val, exc_tb)
                finally:
                    self.close()

        conn = sqlite3.connect(self.db_path, timeout=5.0, factory=ManagedConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _json_load(self, value, default=None):
        if value is None:
            return {} if default is None else default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {} if default is None else default

    def _default_agent_profile(self, agent_id):
        agent_key = (agent_id or "agent").strip() or "agent"
        canonical_agent_id = agent_key.lower()
        profile = DEFAULT_AGENT_PROFILES.get(canonical_agent_id)
        if profile:
            return {
                "agent_id": canonical_agent_id,
                **profile,
                "metadata": dict(profile.get("metadata") or {}),
            }
        return {
            "agent_id": agent_key,
            "display_name": agent_key,
            "integration_mode": "native_or_session_bootstrap",
            "integration_target": "Use the agent's own native persistent instructions, startup hooks, or host-managed developer instructions when available.",
            "native_feature": "Agent-native startup instructions or hooks",
            "onboarding_note": "Do not create configuration files for unrelated agent ecosystems. If no native feature exists, run the bootstrap at the start of each session.",
            "metadata": {"builtin": False, "auto_generated": True},
        }

    def _merge_agent_profile(self, row, include_state=True, requested_agent_id=None):
        base = self._default_agent_profile(row["agent_id"] if row else requested_agent_id)
        if row:
            merged = {
                **base,
                "agent_id": row["agent_id"],
                "display_name": row["display_name"] or base["display_name"],
                "integration_mode": row["integration_mode"] or base["integration_mode"],
                "integration_target": row["integration_target"] or base["integration_target"],
                "native_feature": row["native_feature"] or base["native_feature"],
                "onboarding_note": row["onboarding_note"] or base["onboarding_note"],
                "metadata": self._json_load(row["metadata"], default={}) or base["metadata"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        else:
            merged = base
        if include_state:
            merged["state"] = self.get_state(merged["agent_id"])
        return merged

    # ── Agent State ──────────────────────────────────────────

    def get_state(self, agent_id):
        """Get current state of an agent. Returns dict or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_state WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_states(self):
        """Get state of all agents."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_state ORDER BY agent_id"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_state(self, agent_id, status, current_task=None, context=None):
        """Update agent state (upsert)."""
        ctx_json = json.dumps(context) if context else None
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO agent_state (agent_id, status, current_task, context, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(agent_id) DO UPDATE SET
                    status = excluded.status,
                    current_task = excluded.current_task,
                    context = excluded.context,
                    updated_at = excluded.updated_at
            """, (agent_id, status, current_task, ctx_json))
            conn.commit()

    # ── Task Queue ───────────────────────────────────────────

    # -- Agent Profiles ---------------------------------------------------

    def get_agent_profile(self, agent_id, include_state=True):
        """Get a merged agent profile, including built-in defaults."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_profiles WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT * FROM agent_profiles WHERE lower(agent_id) = lower(?) LIMIT 1",
                    (agent_id,),
                ).fetchone()
        return self._merge_agent_profile(row, include_state=include_state, requested_agent_id=agent_id)

    def list_agent_profiles(self, include_state=True):
        """List known agent profiles plus built-in defaults and observed agents."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_profiles ORDER BY agent_id"
            ).fetchall()
            state_rows = conn.execute(
                "SELECT agent_id FROM agent_state ORDER BY agent_id"
            ).fetchall()
        row_map = {row["agent_id"]: row for row in rows}
        agent_ids = set(row_map)
        agent_ids.update(DEFAULT_AGENT_PROFILES)
        agent_ids.update(row["agent_id"] for row in state_rows)
        return [
            self._merge_agent_profile(
                row_map.get(agent_id),
                include_state=include_state,
                requested_agent_id=agent_id,
            )
            for agent_id in sorted(agent_ids)
        ]

    def upsert_agent_profile(self, agent_id, display_name=None, integration_mode=None,
                             integration_target=None, native_feature=None,
                             onboarding_note=None, metadata=None):
        """Create or update a persistent agent profile."""
        current = self.get_agent_profile(agent_id, include_state=False)
        merged = {
            "display_name": display_name if display_name is not None else current["display_name"],
            "integration_mode": integration_mode if integration_mode is not None else current["integration_mode"],
            "integration_target": integration_target if integration_target is not None else current["integration_target"],
            "native_feature": native_feature if native_feature is not None else current["native_feature"],
            "onboarding_note": onboarding_note if onboarding_note is not None else current["onboarding_note"],
            "metadata": metadata if metadata is not None else current.get("metadata"),
        }
        metadata_json = json.dumps(merged["metadata"]) if merged["metadata"] is not None else None
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO agent_profiles (
                    agent_id, display_name, integration_mode, integration_target,
                    native_feature, onboarding_note, metadata, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(agent_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    integration_mode = excluded.integration_mode,
                    integration_target = excluded.integration_target,
                    native_feature = excluded.native_feature,
                    onboarding_note = excluded.onboarding_note,
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at
            """, (
                agent_id,
                merged["display_name"],
                merged["integration_mode"],
                merged["integration_target"],
                merged["native_feature"],
                merged["onboarding_note"],
                metadata_json,
            ))
            conn.commit()
        return self.get_agent_profile(agent_id, include_state=True)

    def create_task(self, title, created_by, description=None, assigned_to=None,
                    priority=0, payload=None):
        """Create a new task. Returns task id."""
        payload_json = json.dumps(payload) if payload else None
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT INTO tasks (title, description, status, priority, assigned_to,
                                   payload, created_by)
                VALUES (?, ?, 'pending', ?, ?, ?, ?)
            """, (title, description, priority, assigned_to, payload_json, created_by))
            conn.commit()
            return cur.lastrowid

    def claim_task(self, agent_id, task_id=None):
        """Claim a specific task or the next available one. Returns task dict or None."""
        conn = self._connect()
        try:
            if task_id:
                conn.execute("""
                    UPDATE tasks SET status = 'claimed', assigned_to = ?,
                        claimed_at = datetime('now')
                    WHERE id = ? AND status = 'pending'
                """, (agent_id, task_id))
            else:
                # Find and claim next available task atomically
                row = conn.execute("""
                    SELECT id FROM tasks
                    WHERE status = 'pending'
                      AND (assigned_to IS NULL OR assigned_to = ?)
                    ORDER BY priority DESC, created_at
                    LIMIT 1
                """, (agent_id,)).fetchone()
                if not row:
                    return None
                task_id = row["id"]
                conn.execute("""
                    UPDATE tasks SET status = 'claimed', assigned_to = ?,
                        claimed_at = datetime('now')
                    WHERE id = ? AND status = 'pending'
                """, (agent_id, task_id))
            conn.commit()
            if conn.total_changes == 0:
                return None
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def complete_task(self, task_id, result=None):
        """Mark a task as completed."""
        result_json = json.dumps(result) if result else None
        with self._connect() as conn:
            conn.execute("""
                UPDATE tasks SET status = 'done', completed_at = datetime('now'),
                    result = ?
                WHERE id = ?
            """, (result_json, task_id))
            conn.commit()

    def fail_task(self, task_id, error=None):
        """Mark a task as failed."""
        result_json = json.dumps({"error": error}) if error else None
        with self._connect() as conn:
            conn.execute("""
                UPDATE tasks SET status = 'failed', completed_at = datetime('now'),
                    result = ?
                WHERE id = ?
            """, (result_json, task_id))
            conn.commit()

    def list_tasks(self, status=None, assigned_to=None, include_done=False,
                    limit=50):
        """List tasks with optional filters.

        By default, only pending/claimed tasks are shown.
        Set include_done=True or pass a specific status to see completed/failed tasks.
        """
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        elif not include_done:
            query += " AND status NOT IN ('done', 'failed')"
        if assigned_to:
            query += " AND assigned_to = ?"
            params.append(assigned_to)
        query += " ORDER BY priority DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def cleanup_done_tasks(self, days=7):
        """Delete done/failed tasks older than N days. Returns count deleted."""
        with self._connect() as conn:
            cur = conn.execute("""
                DELETE FROM tasks
                WHERE status IN ('done', 'failed')
                  AND completed_at < datetime('now', ? || ' days')
            """, (f"-{days}",))
            conn.commit()
            return cur.rowcount

    # ── Event Log ────────────────────────────────────────────

    def append_event(self, event_type, source_agent, data=None, target_agent=None):
        """Append an event to the log. Returns event id."""
        data_json = json.dumps(data) if data else None
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT INTO events (event_type, source_agent, target_agent, data)
                VALUES (?, ?, ?, ?)
            """, (event_type, source_agent, target_agent, data_json))
            conn.commit()
            return cur.lastrowid

    def get_events(self, since_id=0, event_type=None, source_agent=None,
                   target_agent=None, limit=100, since_time=None):
        """Get events since a given id or time, with optional filters."""
        if since_time:
            query = "SELECT * FROM events WHERE created_at >= ?"
            params = [since_time]
        else:
            query = "SELECT * FROM events WHERE id > ?"
            params = [since_id]
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if source_agent:
            query += " AND source_agent = ?"
            params.append(source_agent)
        if target_agent:
            query += " AND (target_agent = ? OR target_agent IS NULL)"
            params.append(target_agent)
        query += " ORDER BY id ASC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_latest_events(self, limit=20):
        """Get the most recent events."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    # ── Convenience ──────────────────────────────────────────

    # -- Agent Chat -------------------------------------------------------

    def append_chat_message(self, sender_agent, body, channel="general",
                            target_agent=None, metadata=None):
        """Append a message to the agent chat log."""
        metadata_json = json.dumps(metadata) if metadata else None
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT INTO chat_messages (channel, sender_agent, target_agent, body, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (channel or "general", sender_agent, target_agent, body, metadata_json))
            conn.commit()
            return cur.lastrowid

    def get_chat_messages(
        self, channel=None, agent_id=None, since_id=0, before_id=0, limit=100
    ):
        """Fetch chat messages, optionally filtered by channel or agent visibility.

        If both ``before_id`` and ``since_id`` are provided, ``before_id`` wins.
        That keeps pagination deterministic for scrollback requests.
        """
        query = "SELECT * FROM chat_messages WHERE 1=1"
        params = []
        if before_id:
            query += " AND id < ?"
            params.append(before_id)
        elif since_id:
            query += " AND id > ?"
            params.append(since_id)
        if channel:
            query += " AND channel = ?"
            params.append(channel)
        if agent_id:
            query += " AND (sender_agent = ? OR target_agent = ? OR target_agent IS NULL)"
            params.extend([agent_id, agent_id])
        if before_id:
            query += " ORDER BY id DESC LIMIT ?"
        elif since_id:
            query += " ORDER BY id ASC LIMIT ?"
        else:
            query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            messages = [dict(r) for r in rows]
        if not since_id:
            messages.reverse()
        for message in messages:
            message["metadata"] = self._json_load(message.get("metadata"), default={})
        return messages

    def list_chat_channels(self, limit=50):
        """Return chat channels ordered by latest activity with message counts."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    channel,
                    COUNT(*) AS message_count,
                    MAX(id) AS last_message_id,
                    MAX(created_at) AS last_created_at
                FROM chat_messages
                GROUP BY channel
                ORDER BY last_message_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def handoff(self, from_agent, to_agent, title, description=None, payload=None):
        """Create a task handoff from one agent to another and log it."""
        task_id = self.create_task(
            title=title,
            description=description,
            created_by=from_agent,
            assigned_to=to_agent,
            payload=payload,
        )
        self.append_event("handoff", from_agent, target_agent=to_agent, data={
            "task_id": task_id,
            "title": title,
        })
        return task_id

    def log_commit(self, agent, hash, message, branch=None, files=None):
        """Log a git commit event."""
        return self.append_event("commit", agent, data={
            "hash": hash,
            "message": message,
            "branch": branch,
            "files": files,
        })

    def log_deploy(self, agent, container, image, port=None):
        """Log a container deployment event."""
        return self.append_event("deploy", agent, data={
            "container": container,
            "image": image,
            "port": port,
        })

    def stats(self):
        """Get memory stats."""
        with self._connect() as conn:
            agents = conn.execute("SELECT COUNT(*) FROM agent_state").fetchone()[0]
            tasks_total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            tasks_pending = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status='pending'"
            ).fetchone()[0]
            events_total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            sessions_active = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE ended_at IS NULL"
            ).fetchone()[0]
            episodes_total = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            knowledge_active = conn.execute(
                "SELECT COUNT(*) FROM knowledge WHERE active = 1"
            ).fetchone()[0]
            chat_total = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
            db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
            return {
                "agents": agents,
                "tasks_total": tasks_total,
                "tasks_pending": tasks_pending,
                "events_total": events_total,
                "sessions_active": sessions_active,
                "episodes_total": episodes_total,
                "knowledge_active": knowledge_active,
                "chat_total": chat_total,
                "db_size_bytes": db_size,
                "db_path": self.db_path,
            }

    # ── Working Memory ────────────────────────────────────────

    def begin_session(self, agent_id):
        """Start a new session for an agent. Returns session_id."""
        session_id = str(uuid.uuid4())[:8]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, agent_id) VALUES (?, ?)",
                (session_id, agent_id),
            )
            conn.commit()
        return session_id

    def end_session(self, agent_id, session_id, title=None, outcome=None, lessons=None):
        """End a session and create an episode from it. Returns episode_id."""
        with self._connect() as conn:
            session = conn.execute(
                "SELECT * FROM sessions WHERE id = ? AND agent_id = ?",
                (session_id, agent_id),
            ).fetchone()
            if not session:
                return None

            # Build episode title from session if not provided
            if not title:
                title = f"Session {session_id}"

            # Create episode from session
            cur = conn.execute("""
                INSERT INTO episodes (agent_id, session_id, title, category, outcome, lessons, started_at, ended_at)
                VALUES (?, ?, ?, 'session', ?, ?, ?, datetime('now'))
            """, (agent_id, session_id, title, outcome, lessons, session["started_at"]))
            episode_id = cur.lastrowid

            # Close session
            conn.execute("""
                UPDATE sessions SET ended_at = datetime('now'), summary = ?, episode_id = ?
                WHERE id = ?
            """, (title, episode_id, session_id))

            # Clean up working memory for this session
            conn.execute(
                "DELETE FROM working_memory WHERE agent_id = ? AND session_id = ?",
                (agent_id, session_id),
            )
            conn.commit()
            return episode_id

    def get_active_session(self, agent_id):
        """Get the current active session for an agent. Returns dict or None."""
        with self._connect() as conn:
            row = conn.execute("""
                SELECT * FROM sessions
                WHERE agent_id = ? AND ended_at IS NULL
                ORDER BY started_at DESC LIMIT 1
            """, (agent_id,)).fetchone()
            return dict(row) if row else None

    def list_sessions(self, agent_id=None, limit=20):
        """List sessions, optionally filtered by agent."""
        query = "SELECT * FROM sessions WHERE 1=1"
        params = []
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def wm_set(self, agent_id, session_id, key, value, ttl_minutes=None):
        """Set a working memory key-value pair."""
        expires = None
        if ttl_minutes:
            expires = (datetime.utcnow() + timedelta(minutes=ttl_minutes)).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO working_memory (agent_id, session_id, key, value, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(agent_id, session_id, key) DO UPDATE SET
                    value = excluded.value,
                    expires_at = excluded.expires_at,
                    updated_at = datetime('now')
            """, (agent_id, session_id, key, value, expires))
            conn.commit()

    def wm_get(self, agent_id, session_id, key):
        """Get a working memory value. Returns None if expired or missing."""
        with self._connect() as conn:
            row = conn.execute("""
                SELECT value FROM working_memory
                WHERE agent_id = ? AND session_id = ? AND key = ?
                  AND (expires_at IS NULL OR expires_at > datetime('now'))
            """, (agent_id, session_id, key)).fetchone()
            return row["value"] if row else None

    def wm_get_all(self, agent_id, session_id):
        """Get all working memory for a session. Returns dict."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT key, value FROM working_memory
                WHERE agent_id = ? AND session_id = ?
                  AND (expires_at IS NULL OR expires_at > datetime('now'))
            """, (agent_id, session_id)).fetchall()
            return {r["key"]: r["value"] for r in rows}

    def wm_delete(self, agent_id, session_id, key):
        """Delete a single working memory key."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM working_memory WHERE agent_id = ? AND session_id = ? AND key = ?",
                (agent_id, session_id, key),
            )
            conn.commit()

    def wm_clear(self, agent_id, session_id):
        """Clear all working memory for a session."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM working_memory WHERE agent_id = ? AND session_id = ?",
                (agent_id, session_id),
            )
            conn.commit()

    # ── Episodic Memory ───────────────────────────────────────

    def create_episode(self, agent_id, title, category="general", tags=None,
                       description=None, session_id=None):
        """Create a new episode. Returns episode_id."""
        tags_json = json.dumps(tags) if tags else None
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT INTO episodes (agent_id, session_id, title, description, category, tags)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (agent_id, session_id, title, description, category, tags_json))
            conn.commit()
            return cur.lastrowid

    def complete_episode(self, episode_id, outcome, lessons=None):
        """Complete an episode with outcome and optional lessons.
        Auto-promotes lessons to knowledge if present."""
        with self._connect() as conn:
            conn.execute("""
                UPDATE episodes SET outcome = ?, lessons = ?, ended_at = datetime('now')
                WHERE id = ?
            """, (outcome, lessons, episode_id))
            conn.commit()
        # Auto-promote lessons to knowledge
        if lessons:
            self.promote_lesson(episode_id)

    def get_episode(self, episode_id):
        """Get a single episode with its linked events."""
        with self._connect() as conn:
            ep = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
            if not ep:
                return None
            ep = dict(ep)
            events = conn.execute("""
                SELECT e.* FROM events e
                JOIN episode_events ee ON ee.event_id = e.id
                WHERE ee.episode_id = ?
                ORDER BY e.id
            """, (episode_id,)).fetchall()
            ep["events"] = [dict(e) for e in events]
            return ep

    def search_episodes(self, agent_id=None, category=None, outcome=None,
                        tag=None, query=None, limit=20):
        """Search episodes with optional filters."""
        sql = "SELECT * FROM episodes WHERE 1=1"
        params = []
        if agent_id:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        if category:
            sql += " AND category = ?"
            params.append(category)
        if outcome:
            sql += " AND outcome = ?"
            params.append(outcome)
        if tag:
            sql += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
        if query:
            sql += " AND (title LIKE ? OR description LIKE ? OR lessons LIKE ?)"
            params.extend([f"%{query}%"] * 3)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def link_event_to_episode(self, episode_id, event_id):
        """Link an event to an episode."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO episode_events (episode_id, event_id) VALUES (?, ?)",
                (episode_id, event_id),
            )
            conn.commit()

    # ── Semantic Memory (Knowledge) ───────────────────────────

    def learn(self, subject, predicate, object, category="fact", source=None,
              confidence=1.0, tags=None, source_episode_id=None):
        """Store a knowledge triple. Returns knowledge id."""
        tags_json = json.dumps(tags) if tags else None
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT INTO knowledge (category, subject, predicate, object, confidence,
                                       source, source_episode_id, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (category, subject, predicate, object, confidence, source, source_episode_id, tags_json))
            conn.commit()
            return cur.lastrowid

    def recall(self, subject=None, predicate=None, category=None, tag=None,
               query=None, limit=50):
        """Recall knowledge with optional filters. Only returns active entries."""
        sql = "SELECT * FROM knowledge WHERE active = 1"
        params = []
        if subject:
            sql += " AND subject LIKE ?"
            params.append(f"%{subject}%")
        if predicate:
            sql += " AND predicate = ?"
            params.append(predicate)
        if category:
            sql += " AND category = ?"
            params.append(category)
        if tag:
            sql += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
        if query:
            sql += " AND (subject LIKE ? OR predicate LIKE ? OR object LIKE ?)"
            params.extend([f"%{query}%"] * 3)
        sql += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def forget(self, knowledge_id):
        """Soft-delete a knowledge entry (set active=0)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE knowledge SET active = 0, updated_at = datetime('now') WHERE id = ?",
                (knowledge_id,),
            )
            conn.commit()

    def validate_knowledge(self, knowledge_id, validated_by):
        """Mark a knowledge entry as validated."""
        with self._connect() as conn:
            conn.execute("""
                UPDATE knowledge SET validated_by = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (validated_by, knowledge_id))
            conn.commit()

    # ── Cross-Tier ────────────────────────────────────────────

    def context_for(self, topic):
        """Get context across all tiers for a topic.
        Knowledge sorted by confidence, episodes by recency."""
        knowledge = self.recall(query=topic, limit=10)
        episodes = self.search_episodes(query=topic, limit=5)
        # Check all active sessions for relevant working memory
        working = {}
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT wm.agent_id, wm.session_id, wm.key, wm.value
                FROM working_memory wm
                JOIN sessions s ON s.id = wm.session_id AND s.agent_id = wm.agent_id
                WHERE s.ended_at IS NULL
                  AND (wm.expires_at IS NULL OR wm.expires_at > datetime('now'))
                  AND (wm.key LIKE ? OR wm.value LIKE ?)
            """, (f"%{topic}%", f"%{topic}%")).fetchall()
            for r in rows:
                key = f"{r['agent_id']}:{r['session_id']}"
                if key not in working:
                    working[key] = {}
                working[key][r["key"]] = r["value"]
        return {
            "knowledge": knowledge,
            "episodes": episodes,
            "working": working,
            "summary": {
                "knowledge_count": len(knowledge),
                "episodes_count": len(episodes),
                "working_keys": sum(len(v) for v in working.values()),
            },
        }

    def onboarding_context(self, agent_id=None):
        """Return canonical onboarding context for an agent."""
        bundle = self.get_onboarding_bundle(agent_id=agent_id)
        return {
            "knowledge": bundle["entries"],
            "episodes": [],
            "working": {},
            "summary": {
                "knowledge_count": len(bundle["entries"]),
                "episodes_count": 0,
                "working_keys": 0,
            },
            "profile": bundle["profile"],
            "prompt": bundle["prompt"],
        }

    def get_onboarding_bundle(self, agent_id=None):
        """Build a universal onboarding bundle for a known or future agent."""
        resolved_agent = (agent_id or "<agent_id>").strip() or "<agent_id>"
        profile = self.get_agent_profile(resolved_agent, include_state=False)
        canonical_agent_id = profile["agent_id"]
        sections = [
            {
                "subject": "onboarding_connection",
                "predicate": "instructions",
                "object": (
                    "## Agent Memory Connection\n\n"
                    "- Base URL: http://127.0.0.1:9077\n"
                    "- Dashboard: http://127.0.0.1:9077\n"
                    "- Preferred access method: direct HTTP API\n"
                    "- Optional convenience env var: AGENT_MEMORY_URL=http://127.0.0.1:9077\n\n"
                    "Agent Memory is the shared memory layer across sessions, agents, and machines."
                ),
            },
            {
                "subject": "onboarding_bootstrap",
                "predicate": "instructions",
                "object": (
                    "## Bootstrap - Run first in every new session\n\n"
                    f"1. Load onboarding: GET /api/context/onboarding?agent_id={canonical_agent_id}\n"
                    "2. Read all onboarding_* entries and treat them as the source of truth.\n"
                    "3. Check health and current state: GET /api/status and GET /api/state\n"
                    f"4. Mark yourself active: POST /api/state/{canonical_agent_id} with your current task\n"
                    "5. Load the latest events: GET /api/events?limit=500\n"
                    "6. Load open tasks: GET /api/tasks\n"
                    "7. Load recent knowledge: GET /api/knowledge?limit=500\n"
                    "8. If you are working on a project, load project context with GET /api/context/<project>\n\n"
                    "If Agent Memory is unreachable, stop and ask the user instead of assuming stale context."
                ),
            },
            {
                "subject": "onboarding_pflichten",
                "predicate": "instructions",
                "object": (
                    "## Required Updates\n\n"
                    "- Update your state when you start work and when you finish.\n"
                    "- Log meaningful commits, deploys, handoffs, and session summaries as events.\n"
                    "- Store reusable facts, patterns, and decisions as knowledge.\n"
                    "- Improve onboarding itself when you notice stale or agent-specific instructions."
                ),
            },
            {
                "subject": "onboarding_regeln",
                "predicate": "instructions",
                "object": (
                    f"## Agent Integration and Rules for {profile['display_name']}\n\n"
                    f"- Agent ID: {profile['agent_id']}\n"
                    f"- Preferred integration mode: {profile['integration_mode']}\n"
                    f"- Integration target: {profile['integration_target']}\n"
                    f"- Native feature: {profile['native_feature']}\n"
                    f"- Special note: {profile['onboarding_note']}\n\n"
                    "Universal rule: use the current agent's own startup or persistent instruction feature. "
                    "Do not create configuration files for another agent family."
                ),
            },
            {
                "subject": "onboarding_workflow",
                "predicate": "instructions",
                "object": (
                    "## Workflow Expectations\n\n"
                    "- For non-trivial work, make a short plan before implementation.\n"
                    "- Verify outcomes before marking work complete.\n"
                    "- Prefer minimal, defensible changes over broad rewrites.\n"
                    "- After every user correction, update Agent Memory with the corrected pattern.\n"
                    "- Save reusable knowledge proactively when it will prevent future mistakes or save time."
                ),
            },
            {
                "subject": "onboarding_api_referenz",
                "predicate": "instructions",
                "object": (
                    "## API Reference\n\n"
                    "Read:\n"
                    "- GET /api/status\n"
                    "- GET /api/state\n"
                    "- GET /api/state/<agent>\n"
                    "- GET /api/events?limit=N\n"
                    "- GET /api/tasks\n"
                    "- GET /api/knowledge?limit=N\n"
                    "- GET /api/context/<topic>\n"
                    "- GET /api/onboarding/<agent>\n"
                    "- GET /api/agents\n"
                    "- GET /api/chat?limit=N\n\n"
                    "Write:\n"
                    "- POST /api/state/<agent>\n"
                    "- POST /api/events\n"
                    "- POST /api/knowledge\n"
                    "- POST /api/agents/<agent>\n"
                    "- POST /api/chat"
                ),
            },
        ]

        custom_entries = [
            entry for entry in self.recall(category="onboarding", limit=200)
            if str(entry.get("subject", "")).startswith("onboarding_custom_")
        ]
        custom_entries.sort(key=lambda entry: entry.get("subject", ""))

        entries = []
        for index, section in enumerate(sections, start=1):
            entries.append({
                "id": f"builtin:{section['subject']}",
                "subject": section["subject"],
                "predicate": section["predicate"],
                "object": section["object"],
                "category": "onboarding",
                "source": "builtin",
                "active": 1,
                "confidence": 1.0,
                "created_at": None,
                "updated_at": None,
                "validated_by": "system",
                "order": index,
            })
        for entry in custom_entries:
            cloned = dict(entry)
            cloned["order"] = len(entries) + 1
            entries.append(cloned)

        prompt_sections = "\n\n".join(entry["object"] for entry in entries)
        prompt = (
            f"Agent Memory onboarding for {profile['display_name']} ({profile['agent_id']}).\n"
            "Use this agent's own native startup instruction feature when available. "
            "Do not create or rely on another agent's config files.\n\n"
            "Your first session action is to load /api/context/onboarding with your agent_id, then execute the bootstrap.\n\n"
            f"{prompt_sections}\n\n"
            "After reading this, execute the bootstrap and confirm which state, events, tasks, and knowledge you loaded."
        )

        return {
            "agent_id": profile["agent_id"],
            "profile": profile,
            "entries": entries,
            "prompt": prompt,
        }

    def promote_lesson(self, episode_id):
        """Extract lessons from an episode and store as knowledge. Returns list of knowledge ids."""
        ep = self.get_episode(episode_id)
        if not ep or not ep.get("lessons"):
            return []
        ids = []
        # Each line of lessons becomes a knowledge entry
        for line in ep["lessons"].strip().split("\n"):
            line = line.strip().lstrip("- ")
            if not line:
                continue
            kid = self.learn_or_update(
                subject=ep.get("title", "unknown"),
                predicate="learned",
                object=line,
                category="pattern",
                source=f"episode:{episode_id}",
                source_episode_id=episode_id,
            )
            ids.append(kid)
        return ids

    def decay_knowledge(self, days_threshold=30, decay_rate=0.05, min_confidence=0.1):
        """Reduce confidence of unvalidated knowledge older than threshold.
        Returns count of affected entries."""
        with self._connect() as conn:
            cur = conn.execute("""
                UPDATE knowledge
                SET confidence = MAX(?, confidence - ?),
                    updated_at = datetime('now')
                WHERE active = 1
                  AND validated_by IS NULL
                  AND updated_at < datetime('now', ? || ' days')
                  AND confidence > ?
            """, (min_confidence, decay_rate, f"-{days_threshold}", min_confidence))
            conn.commit()
            return cur.rowcount

    def cleanup_expired_wm(self):
        """Delete expired working memory entries. Returns count deleted."""
        with self._connect() as conn:
            cur = conn.execute("""
                DELETE FROM working_memory
                WHERE expires_at IS NOT NULL AND expires_at < datetime('now')
            """)
            conn.commit()
            return cur.rowcount

    def learn_or_update(self, subject, predicate, object, category="fact",
                        source=None, confidence=1.0, tags=None, source_episode_id=None):
        """Learn new knowledge or strengthen existing if same subject+predicate exists."""
        with self._connect() as conn:
            existing = conn.execute("""
                SELECT id, confidence FROM knowledge
                WHERE subject = ? AND predicate = ? AND active = 1
            """, (subject, predicate)).fetchone()

            if existing:
                # Strengthen: average with new confidence, update object
                new_conf = min(1.0, (existing["confidence"] + confidence) / 2 + 0.1)
                conn.execute("""
                    UPDATE knowledge
                    SET object = ?, confidence = ?, source = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                """, (object, new_conf, source, existing["id"]))
                conn.commit()
                return existing["id"]
            else:
                return self.learn(subject, predicate, object, category,
                                  source, confidence, tags, source_episode_id)

    # ── Observations ────────────────────────────────────────

    def add_observation(self, agent_id, tool_name, action=None, file_path=None,
                        summary=None, session_id=None):
        """Record a tool-call observation. Returns observation id."""
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT INTO observations (session_id, agent_id, tool_name, action, file_path, summary)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, agent_id, tool_name, action, file_path, summary))
            conn.commit()
            return cur.lastrowid

    def get_observations(self, agent_id=None, session_id=None, tool_name=None,
                         limit=100, offset=0):
        """List observations with optional filters."""
        clauses = []
        params = []
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if tool_name:
            clauses.append("tool_name = ?")
            params.append(tool_name)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM observations{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def search_observations(self, query, limit=50):
        """Full-text search over observations."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT o.* FROM observations o
                JOIN observations_fts fts ON o.id = fts.rowid
                WHERE observations_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit)).fetchall()
            return [dict(r) for r in rows]

    def session_observation_summary(self, session_id):
        """Generate a template-based summary of observations for a session."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT tool_name, action, file_path, summary, created_at
                FROM observations WHERE session_id = ?
                ORDER BY created_at
            """, (session_id,)).fetchall()

        if not rows:
            return None

        tools = {}
        files_modified = set()
        files_read = set()
        actions = []

        for r in rows:
            tool = r["tool_name"]
            tools[tool] = tools.get(tool, 0) + 1
            fp = r["file_path"]
            action = r["action"]
            if fp:
                if action in ("write", "edit", "create"):
                    files_modified.add(fp)
                elif action == "read":
                    files_read.add(fp)
            if r["summary"]:
                actions.append(r["summary"])

        parts = []
        parts.append(f"Tool calls: {sum(tools.values())} ({', '.join(f'{v}x {k}' for k, v in sorted(tools.items(), key=lambda x: -x[1]))})")
        if files_modified:
            parts.append(f"Files modified: {', '.join(sorted(files_modified))}")
        if files_read:
            parts.append(f"Files read: {', '.join(sorted(files_read))}")
        if actions:
            unique = list(dict.fromkeys(actions))
            parts.append(f"Actions: {'; '.join(unique[:20])}")

        return "\n".join(parts)

    def cleanup_old_observations(self, days=30):
        """Delete observations older than the given number of days."""
        with self._connect() as conn:
            cur = conn.execute("""
                DELETE FROM observations
                WHERE created_at < datetime('now', ? || ' days')
            """, (f"-{days}",))
            conn.commit()
            return cur.rowcount
