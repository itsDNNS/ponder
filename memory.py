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
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_DB_PATH = Path(os.environ.get("AGENT_MEMORY_DB", str(Path.home() / ".openclaw" / "agent-memory" / "agent.db")))

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
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA)

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
                   target_agent=None, limit=100):
        """Get events since a given id, with optional filters."""
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
            db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
            return {
                "agents": agents,
                "tasks_total": tasks_total,
                "tasks_pending": tasks_pending,
                "events_total": events_total,
                "sessions_active": sessions_active,
                "episodes_total": episodes_total,
                "knowledge_active": knowledge_active,
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
        """Complete an episode with outcome and optional lessons."""
        with self._connect() as conn:
            conn.execute("""
                UPDATE episodes SET outcome = ?, lessons = ?, ended_at = datetime('now')
                WHERE id = ?
            """, (outcome, lessons, episode_id))
            conn.commit()

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
        """Get context across all tiers for a topic."""
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
            kid = self.learn(
                subject=ep.get("title", "unknown"),
                predicate="learned",
                object=line,
                category="pattern",
                source=f"episode:{episode_id}",
                source_episode_id=episode_id,
            )
            ids.append(kid)
        return ids
