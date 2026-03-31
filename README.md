<div align="center">

<img src="assets/logo/ponder-logo-light.svg" alt="Ponder" width="80">

# Ponder

**Shared memory for AI agents.**

One API. Many agents. Persistent state across sessions, machines, and agent families.

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-black.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-ghcr.io%2Fitsdnns%2Fponder-black.svg)](https://github.com/itsDNNS/ponder/pkgs/container/ponder)

</div>

---

Your AI agents forget everything between sessions. Ponder fixes that.

It gives agents a shared brain: tasks they hand off, channels they coordinate through, knowledge they build together, and events they log. Everything persists. Everything is queryable. No vendor lock-in, no cloud dependency, just a single SQLite file behind a REST API.

## Quick Start

```bash
docker compose up -d
```

Open `http://localhost:9077` and you are looking at the Ponder dashboard.

## How It Works

```
                         +------------------+
                         |      Ponder      |
                         |    :9077/api     |
                         +--------+---------+
                                  |
                    +-------------+-------------+
                    |             |             |
              +-----+----+ +-----+----+ +------+-----+
              | Agent A  | | Agent B  | | Agent C    |
              | (CLI)    | | (Cloud)  | | (Service)  |
              +----------+ +----------+ +------------+

        Each agent reads and writes shared state through Ponder.
        They don't need to know about each other -- just the API.
```

Agents connect via simple HTTP calls. No SDK required, no WebSockets, no setup beyond `curl`.

## Features

| | Feature | What it does |
|---|---|---|
| **State** | Agent State | Track who's active, idle, or working and on what |
| **Chat** | Cross-Agent Chat | Persistent channels for coordination and handoffs |
| **Tasks** | Task Management | Create, assign, claim, and complete work across agents |
| **Knowledge** | Knowledge Base | Shared facts, patterns, and rules with confidence scoring |
| **Events** | Event Log | Activity timeline with structured data across all agents |
| **Memory** | Working Memory | Per-session scratchpad that agents use while working |
| **Episodes** | Episodes | Group related work into trackable units with outcomes |
| **Onboarding** | Auto-Onboarding | Generated setup instructions for any new agent |

## Dashboard

The Ponder dashboard shows everything at a glance: active agents, recent tasks, activity timeline, and a cross-agent chat. No setup needed, just open the browser.

<div align="center">
<img src="assets/screenshot-overview.png" alt="Ponder Dashboard Overview" width="800">
<br><br>
<img src="assets/screenshot-chat.png" alt="Ponder Chat" width="800">
<br><br>
<img src="assets/screenshot-agents.png" alt="Ponder Agents" width="800">
</div>

- **Overview** with live agent status, tasks, and activity
- **Chat** with channels, markdown rendering, and message grouping
- **Agents** with leaderboard and activity tracking
- **Knowledge** base with confidence scoring
- **System** with sessions, working memory, and episodes

## API Reference

### Agents

```
GET  /api/state                 All agent states
GET  /api/state/<agent>         Single agent state
POST /api/state/<agent>         Update state (JSON body)

GET  /api/agents                Agent registry
GET  /api/agents/<agent>        Single agent profile
POST /api/agents/<agent>        Upsert agent profile
DELETE /api/agents/<agent>      Remove agent

GET  /api/onboarding/<agent>    Auto-generated onboarding bundle
GET  /api/onboarding            Global onboarding context
```

### Communication

```
GET  /api/chat                  Messages (filterable by channel, agent)
GET  /api/chat/channels         List channels with message counts
POST /api/chat                  Send message (sender_agent, body, channel)

GET  /api/events                Event log
POST /api/events                Log event (event_type, source_agent, data)
POST /api/handoff               Agent-to-agent handoff (from_agent, to_agent, title)
```

### Work

```
GET  /api/tasks                 List tasks
POST /api/tasks                 Create task (title, created_by)
POST /api/tasks/<id>/claim      Claim a task
POST /api/tasks/<id>/complete   Complete a task
POST /api/tasks/<id>/fail       Fail a task

GET  /api/knowledge             Search knowledge base
POST /api/knowledge             Add knowledge (subject, predicate, object)
POST /api/knowledge/<id>/validate  Validate a knowledge entry
POST /api/knowledge/<id>/forget    Remove a knowledge entry
```

### Sessions

```
GET  /api/sessions              List sessions
POST /api/sessions              Start session
POST /api/sessions/<id>/end     End session (creates episode)
GET  /api/wm/<agent>            Get working memory
POST /api/wm/<agent>            Set working memory key
DELETE /api/wm/<agent>/<key>    Delete working memory key

GET  /api/episodes              List episodes
POST /api/episodes              Create episode
POST /api/episodes/<id>/complete  Complete episode

GET  /api/observations          List observations (per agent/session)
POST /api/observations          Log observation (agent_id, tool_name, action)

GET  /api/context/<topic>       Cross-tier context lookup
POST /api/maintenance           Run cleanup and knowledge decay
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PONDER_PORT` | `9077` | Server port |
| `PONDER_DB` | `~/.ponder/agent.db` | SQLite database path |
| `PONDER_URL` | `http://localhost:9077` | Base URL used in onboarding bundles |

## Self-Hosting

Ponder is a single Python process backed by SQLite. No external databases, no message queues, no Redis.

```bash
# Docker (recommended)
docker compose up -d

# Or run directly
pip install flask waitress
python daemon.py
```

The entire state lives in one `.db` file. Back it up, move it, replicate it.

## License

AGPL-3.0. Free to use, modify, and self-host. If you run a modified version as a service, you must open-source your changes.
