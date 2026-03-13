#!/usr/bin/env python3
"""Agent Memory CLI -- Command-line interface for agent-memory daemon.

Usage:
  am status                              Show stats
  am state [agent] [status] [task]       Agent state
  am tasks [--all] [status] [agent]      List tasks
  am task create/claim/done/fail         Task operations
  am events [--since N] [--type T]       Event log
  am event <type> <source> [data]        Log event
  am handoff <from> <to> <title>         Handoff

  am session start <agent>               Start session
  am session end <id> <title> [outcome]  End session -> Episode
  am session list [agent]                List sessions
  am wm <agent> [key] [value]            Working memory
  am episodes [--tag X] [-q QUERY]       Search episodes
  am episode <id>                        Show episode detail
  am know [subject]                      Recall knowledge
  am learn <subj> <pred> <obj> [--cat C] Store knowledge
  am forget <id>                         Deactivate knowledge
  am context <topic>                     Cross-tier context
  am agents                              List agent profiles
  am onboarding [agent]                  Print canonical onboarding
  am chat [--agent A] [--channel C]      List chat messages
  am say <sender> <message...>           Store chat message
  am promote <episode_id>                Promote episode lessons -> knowledge
  am maintenance                         Run cleanup + decay
  am dashboard                           Open web UI
"""

import json
import os
import subprocess
import sys

try:
    import requests
except ImportError:
    # Fallback: use urllib
    import urllib.request
    import urllib.error

    class _MinimalRequests:
        """Minimal requests-like wrapper around urllib."""
        class Response:
            def __init__(self, data, status):
                self.text = data
                self.status_code = status
            def json(self):
                return json.loads(self.text)
            @property
            def ok(self):
                return 200 <= self.status_code < 400

        def get(self, url, **kw):
            try:
                r = urllib.request.urlopen(url, timeout=5)
                return self.Response(r.read().decode(), r.status)
            except urllib.error.HTTPError as e:
                return self.Response(e.read().decode(), e.code)
            except urllib.error.URLError:
                return self.Response("", 0)

        def post(self, url, json=None, **kw):
            data = __builtins__.__import__('json').dumps(json).encode() if json else None
            req = urllib.request.Request(url, data=data,
                headers={"Content-Type": "application/json"} if data else {})
            try:
                r = urllib.request.urlopen(req, timeout=5)
                return self.Response(r.read().decode(), r.status)
            except urllib.error.HTTPError as e:
                return self.Response(e.read().decode(), e.code)
            except urllib.error.URLError:
                return self.Response("", 0)

    requests = _MinimalRequests()

BASE = os.environ.get("AGENT_MEMORY_URL", "http://localhost:9077")


def _get(path, params=None):
    url = f"{BASE}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if qs:
            url += f"?{qs}"
    r = requests.get(url)
    if not r.ok and r.status_code == 0:
        print("Error: Agent Memory daemon not running. Start with: python daemon.py")
        sys.exit(1)
    return r.json()


def _post(path, data=None):
    r = requests.post(f"{BASE}{path}", json=data or {})
    if not r.ok and r.status_code == 0:
        print("Error: Agent Memory daemon not running. Start with: python daemon.py")
        sys.exit(1)
    try:
        return r.json()
    except (json.JSONDecodeError, Exception):
        if not r.ok:
            print(f"Error: HTTP {r.status_code}")
            return {"error": f"HTTP {r.status_code}"}
        return {"ok": True}


def _fmt_json(data):
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data
    return json.dumps(data, indent=2, ensure_ascii=False)


def cmd_status():
    s = _get("/api/status")
    print(f"Agents:     {s['agents']}")
    print(f"Tasks:      {s['tasks_total']} ({s['tasks_pending']} pending)")
    print(f"Events:     {s['events_total']}")
    print(f"Sessions:   {s.get('sessions_active', 0)} active")
    print(f"Episodes:   {s.get('episodes_total', 0)}")
    print(f"Knowledge:  {s.get('knowledge_active', 0)} active")
    print(f"DB size:    {s['db_size_bytes'] / 1024:.1f} KB")
    print(f"DB path:    {s['db_path']}")


def cmd_state(args):
    if not args:
        states = _get("/api/state")
        if not states:
            print("No agents registered.")
            return
        for s in states:
            task = s.get("current_task") or "-"
            print(f"  {s['agent_id']:10s}  {s['status']:10s}  {task}  ({s['updated_at']})")
        return

    agent_id = args[0]
    if len(args) >= 2:
        status = args[1]
        task = args[2] if len(args) > 2 else None
        _post(f"/api/state/{agent_id}", {"status": status, "current_task": task})
        print(f"Updated {agent_id} -> {status}" + (f" ({task})" if task else ""))
    else:
        s = _get(f"/api/state/{agent_id}")
        if "error" in s:
            print(f"Agent '{agent_id}' not found.")
            return
        print(f"  Agent:   {s['agent_id']}")
        print(f"  Status:  {s['status']}")
        print(f"  Task:    {s.get('current_task') or '-'}")
        print(f"  Updated: {s['updated_at']}")
        if s.get("context"):
            print(f"  Context: {_fmt_json(s['context'])}")


def cmd_tasks(args):
    params = {}
    show_all = "--all" in args
    if show_all:
        args = [a for a in args if a != "--all"]
        params["all"] = "true"
    if args:
        params["status"] = args[0]
    if len(args) > 1:
        params["assigned_to"] = args[1]
    tasks = _get("/api/tasks", params)
    if not tasks:
        print("No open tasks." if not show_all else "No tasks.")
        return
    for t in tasks:
        assigned = t.get("assigned_to") or "-"
        print(f"  #{t['id']:<4d} [{t['status']:7s}] {t['title']:<40s}  -> {assigned}  (by {t['created_by']}, {t['created_at']})")


def cmd_task_create(args):
    if not args:
        print("Usage: am task create <title> --by <agent> [--for <agent>] [--priority N]")
        return
    title = args[0]
    by = None
    assigned = None
    priority = 0
    i = 1
    while i < len(args):
        if args[i] == "--by" and i + 1 < len(args):
            by = args[i + 1]; i += 2
        elif args[i] == "--for" and i + 1 < len(args):
            assigned = args[i + 1]; i += 2
        elif args[i] == "--priority" and i + 1 < len(args):
            priority = int(args[i + 1]); i += 2
        else:
            i += 1
    if not by:
        print("Error: --by <agent> required")
        return
    result = _post("/api/tasks", {
        "title": title, "created_by": by, "assigned_to": assigned, "priority": priority
    })
    print(f"Task #{result['id']} created.")


def cmd_task_claim(args):
    if len(args) < 2:
        print("Usage: am task claim <id> <agent>")
        return
    result = _post(f"/api/tasks/{args[0]}/claim", {"agent": args[1]})
    if "error" in result:
        print(f"Error: {result['error']}")
    else:
        print(f"Task #{args[0]} claimed by {args[1]}.")


def cmd_task_done(args):
    if not args:
        print("Usage: am task done <id> [result_json]")
        return
    data = {}
    if len(args) > 1:
        data["result"] = args[1]
    _post(f"/api/tasks/{args[0]}/complete", data)
    print(f"Task #{args[0]} completed.")


def cmd_task_fail(args):
    if not args:
        print("Usage: am task fail <id> [error_message]")
        return
    data = {}
    if len(args) > 1:
        data["error"] = args[1]
    _post(f"/api/tasks/{args[0]}/fail", data)
    print(f"Task #{args[0]} failed.")


def cmd_events(args):
    params = {}
    i = 0
    while i < len(args):
        if args[i] == "--since" and i + 1 < len(args):
            params["since"] = args[i + 1]; i += 2
        elif args[i] == "--type" and i + 1 < len(args):
            params["type"] = args[i + 1]; i += 2
        elif args[i] == "--source" and i + 1 < len(args):
            params["source"] = args[i + 1]; i += 2
        else:
            i += 1
    events = _get("/api/events", params)
    if not events:
        print("No events.")
        return
    for e in events:
        target = f" -> {e['target_agent']}" if e.get("target_agent") else ""
        data_str = ""
        if e.get("data"):
            try:
                d = json.loads(e["data"]) if isinstance(e["data"], str) else e["data"]
                if isinstance(d, dict):
                    data_str = " | " + ", ".join(f"{k}={v}" for k, v in d.items())
                else:
                    data_str = f" | {d}"
            except (json.JSONDecodeError, TypeError):
                data_str = f" | {e['data']}"
        print(f"  #{e['id']:<4d} [{e['event_type']:12s}] {e['source_agent']}{target}{data_str}  ({e['created_at']})")


def cmd_event(args):
    if len(args) < 2:
        print("Usage: am event <type> <source_agent> [data_json] [--to <target>]")
        return
    event_type = args[0]
    source = args[1]
    data = None
    target = None
    i = 2
    while i < len(args):
        if args[i] == "--to" and i + 1 < len(args):
            target = args[i + 1]; i += 2
        elif data is None:
            try:
                data = json.loads(args[i])
            except json.JSONDecodeError:
                data = {"message": args[i]}
            i += 1
        else:
            i += 1
    result = _post("/api/events", {
        "event_type": event_type,
        "source_agent": source,
        "target_agent": target,
        "data": data,
    })
    print(f"Event #{result['id']} logged.")


def cmd_handoff(args):
    if len(args) < 3:
        print("Usage: am handoff <from> <to> <title> [description]")
        return
    data = {
        "from_agent": args[0],
        "to_agent": args[1],
        "title": args[2],
    }
    if len(args) > 3:
        data["description"] = args[3]
    result = _post("/api/handoff", data)
    print(f"Handoff task #{result['task_id']}: {args[0]} -> {args[1]}")


def cmd_session(args):
    if not args:
        print("Usage: am session start <agent> | end <id> <title> | list [agent]")
        return
    sub = args[0]
    rest = args[1:]
    if sub == "start":
        if not rest:
            print("Usage: am session start <agent>")
            return
        result = _post("/api/sessions", {"agent_id": rest[0]})
        print(f"Session {result['session_id']} started for {rest[0]}.")
    elif sub == "end":
        if len(rest) < 2:
            print("Usage: am session end <id> <title> [--outcome O] [--lessons L]")
            return
        sid = rest[0]
        title = rest[1]
        outcome = None
        lessons = None
        # Find agent_id from session (need it for the API)
        sessions = _get("/api/sessions")
        agent_id = None
        for s in sessions:
            if s["id"] == sid:
                agent_id = s["agent_id"]
                break
        if not agent_id:
            print(f"Session {sid} not found.")
            return
        i = 2
        while i < len(rest):
            if rest[i] == "--outcome" and i + 1 < len(rest):
                outcome = rest[i + 1]; i += 2
            elif rest[i] == "--lessons" and i + 1 < len(rest):
                lessons = rest[i + 1]; i += 2
            else:
                i += 1
        result = _post(f"/api/sessions/{sid}/end", {
            "agent_id": agent_id, "title": title, "outcome": outcome, "lessons": lessons
        })
        print(f"Session {sid} ended -> Episode #{result['episode_id']}.")
    elif sub == "list":
        params = {}
        if rest:
            params["agent_id"] = rest[0]
        sessions = _get("/api/sessions", params)
        if not sessions:
            print("No sessions.")
            return
        for s in sessions:
            status = "ended" if s.get("ended_at") else "active"
            ep = f" -> ep#{s['episode_id']}" if s.get("episode_id") else ""
            summary = s.get("summary") or ""
            print(f"  {s['id']}  {s['agent_id']:10s}  [{status:6s}]  {s['started_at']}{ep}  {summary}")
    else:
        print(f"Unknown session subcommand: {sub}")


def cmd_wm(args):
    if not args:
        print("Usage: am wm <agent> [key] [value] [--ttl N]")
        return
    agent = args[0]
    if len(args) == 1:
        # Show all working memory
        result = _get(f"/api/wm/{agent}")
        if "error" in result:
            print(f"Error: {result['error']}")
            return
        print(f"  Session: {result['session_id']}")
        data = result.get("data", {})
        if not data:
            print("  (empty)")
        for k, v in data.items():
            print(f"  {k}: {v}")
    elif len(args) == 2:
        # Get single key (via get all and filter)
        result = _get(f"/api/wm/{agent}")
        if "error" in result:
            print(f"Error: {result['error']}")
            return
        val = result.get("data", {}).get(args[1])
        if val is None:
            print(f"  {args[1]}: (not set)")
        else:
            print(f"  {args[1]}: {val}")
    else:
        # Set key=value
        key = args[1]
        value = args[2]
        ttl = None
        if "--ttl" in args:
            idx = args.index("--ttl")
            if idx + 1 < len(args):
                ttl = int(args[idx + 1])
        data = {"key": key, "value": value}
        if ttl:
            data["ttl_minutes"] = ttl
        result = _post(f"/api/wm/{agent}", data)
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"  {key} = {value}")


def cmd_episodes(args):
    params = {}
    i = 0
    while i < len(args):
        if args[i] == "--tag" and i + 1 < len(args):
            params["tag"] = args[i + 1]; i += 2
        elif args[i] in ("-q", "--query") and i + 1 < len(args):
            params["q"] = args[i + 1]; i += 2
        elif args[i] == "--category" and i + 1 < len(args):
            params["category"] = args[i + 1]; i += 2
        elif args[i] == "--outcome" and i + 1 < len(args):
            params["outcome"] = args[i + 1]; i += 2
        elif args[i] == "--agent" and i + 1 < len(args):
            params["agent_id"] = args[i + 1]; i += 2
        else:
            i += 1
    episodes = _get("/api/episodes", params)
    if not episodes:
        print("No episodes found.")
        return
    for ep in episodes:
        outcome = ep.get("outcome") or "..."
        tags = ""
        if ep.get("tags"):
            try:
                t = json.loads(ep["tags"]) if isinstance(ep["tags"], str) else ep["tags"]
                tags = f" [{', '.join(t)}]"
            except (json.JSONDecodeError, TypeError):
                tags = f" [{ep['tags']}]"
        print(f"  #{ep['id']:<4d} [{outcome:8s}] {ep['title']:<40s}  {ep['category']}{tags}  ({ep['started_at']})")


def cmd_episode(args):
    if not args:
        print("Usage: am episode <id> | am episode complete <id> <outcome> [--lessons L]")
        return
    # Subcommand: episode complete
    if args[0] == "complete":
        cmd_episode_complete(args[1:])
        return
    ep = _get(f"/api/episodes/{args[0]}")
    if "error" in ep:
        print(f"Episode #{args[0]} not found.")
        return
    print(f"  Episode:    #{ep['id']}")
    print(f"  Title:      {ep['title']}")
    print(f"  Agent:      {ep['agent_id']}")
    print(f"  Category:   {ep['category']}")
    print(f"  Outcome:    {ep.get('outcome') or '-'}")
    print(f"  Started:    {ep['started_at']}")
    print(f"  Ended:      {ep.get('ended_at') or '-'}")
    if ep.get("description"):
        print(f"  Description: {ep['description']}")
    if ep.get("tags"):
        print(f"  Tags:       {ep['tags']}")
    if ep.get("lessons"):
        print(f"  Lessons:    {ep['lessons']}")
    events = ep.get("events", [])
    if events:
        print(f"\n  Events ({len(events)}):")
        for e in events:
            print(f"    #{e['id']} [{e['event_type']}] {e['source_agent']}  ({e['created_at']})")


def cmd_episode_complete(args):
    if len(args) < 2:
        print("Usage: am episode complete <id> <outcome> [--lessons L]")
        return
    data = {"outcome": args[1]}
    if "--lessons" in args:
        idx = args.index("--lessons")
        if idx + 1 < len(args):
            data["lessons"] = args[idx + 1]
    result = _post(f"/api/episodes/{args[0]}/complete", data)
    if "error" in result:
        print(f"Error: {result['error']}")
    else:
        print(f"Episode #{args[0]} completed ({args[1]}).")
        if data.get("lessons"):
            print("  Lessons auto-promoted to knowledge.")


def cmd_know(args):
    params = {}
    if args:
        params["subject"] = args[0]
    i = 1
    while i < len(args):
        if args[i] == "--cat" and i + 1 < len(args):
            params["category"] = args[i + 1]; i += 2
        elif args[i] in ("-q", "--query") and i + 1 < len(args):
            params["q"] = args[i + 1]; i += 2
        else:
            i += 1
    knowledge = _get("/api/knowledge", params)
    if not knowledge:
        print("No knowledge found.")
        return
    for k in knowledge:
        conf = f"{k['confidence']:.0%}"
        validated = " [validated]" if k.get("validated_by") else ""
        print(f"  #{k['id']:<4d} [{k['category']:10s}] {k['subject']} {k['predicate']} {k['object']}  ({conf}){validated}")


def cmd_learn(args):
    if len(args) < 3:
        print("Usage: am learn <subject> <predicate> <object> [--cat category] [--conf 0.8]")
        return
    subject = args[0]
    predicate = args[1]
    obj = args[2]
    category = "fact"
    confidence = 1.0
    source = "manual"
    i = 3
    while i < len(args):
        if args[i] == "--cat" and i + 1 < len(args):
            category = args[i + 1]; i += 2
        elif args[i] == "--conf" and i + 1 < len(args):
            confidence = float(args[i + 1]); i += 2
        elif args[i] == "--source" and i + 1 < len(args):
            source = args[i + 1]; i += 2
        else:
            i += 1
    result = _post("/api/knowledge", {
        "subject": subject, "predicate": predicate, "object": obj,
        "category": category, "confidence": confidence, "source": source,
    })
    print(f"Knowledge #{result['id']}: {subject} {predicate} {obj}")


def cmd_forget(args):
    if not args:
        print("Usage: am forget <id>")
        return
    _post(f"/api/knowledge/{args[0]}/forget")
    print(f"Knowledge #{args[0]} deactivated.")


def cmd_context(args):
    if not args:
        print("Usage: am context <topic>")
        return
    topic = args[0]
    ctx = _get(f"/api/context/{topic}")

    knowledge = ctx.get("knowledge", [])
    if knowledge:
        print(f"Knowledge ({len(knowledge)}):")
        for k in knowledge:
            print(f"  {k['subject']} {k['predicate']} {k['object']}")

    episodes = ctx.get("episodes", [])
    if episodes:
        print(f"\nEpisodes ({len(episodes)}):")
        for ep in episodes:
            outcome = ep.get("outcome") or "..."
            print(f"  #{ep['id']} [{outcome}] {ep['title']}")

    working = ctx.get("working", {})
    if working:
        print(f"\nWorking Memory:")
        for session_key, data in working.items():
            print(f"  {session_key}:")
            for k, v in data.items():
                print(f"    {k}: {v}")

    if not knowledge and not episodes and not working:
        print(f"No context found for '{topic}'.")


def cmd_agents():
    agents = _get("/api/agents")
    if not agents:
        print("No agent profiles found.")
        return
    for agent in agents:
        state = agent.get("state") or {}
        status = state.get("status", "idle")
        print(
            f"  {agent['agent_id']:10s}  {status:10s}  "
            f"{agent.get('integration_mode') or '-':28s}  "
            f"{agent.get('integration_target') or '-'}"
        )


def cmd_onboarding(args):
    agent_id = args[0] if args else None
    path = f"/api/onboarding/{agent_id}" if agent_id else "/api/onboarding"
    bundle = _get(path)
    if "error" in bundle:
        print(f"Error: {bundle['error']}")
        return
    print(bundle.get("prompt", ""))


def cmd_chat(args):
    params = {}
    i = 0
    while i < len(args):
        if args[i] == "--agent" and i + 1 < len(args):
            params["agent_id"] = args[i + 1]
            i += 2
        elif args[i] == "--channel" and i + 1 < len(args):
            params["channel"] = args[i + 1]
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            params["limit"] = args[i + 1]
            i += 2
        else:
            i += 1
    messages = _get("/api/chat", params)
    if not messages:
        print("No chat messages.")
        return
    for msg in messages:
        target = f" -> {msg['target_agent']}" if msg.get("target_agent") else ""
        print(f"  #{msg['id']:<4d} [{msg['channel']}] {msg['sender_agent']}{target}: {msg['body']}  ({msg['created_at']})")


def cmd_say(args):
    if len(args) < 2:
        print("Usage: am say <sender> <message...> [--to <agent>] [--channel <name>]")
        return
    sender = args[0]
    target = None
    channel = "general"
    message_parts = []
    i = 1
    while i < len(args):
        if args[i] == "--to" and i + 1 < len(args):
            target = args[i + 1]
            i += 2
        elif args[i] == "--channel" and i + 1 < len(args):
            channel = args[i + 1]
            i += 2
        else:
            message_parts.append(args[i])
            i += 1
    body = " ".join(message_parts).strip()
    if not body:
        print("Error: message required")
        return
    result = _post("/api/chat", {
        "sender_agent": sender,
        "target_agent": target,
        "channel": channel,
        "body": body,
    })
    if "error" in result:
        print(f"Error: {result['error']}")
        return
    print(f"Chat message #{result['id']} stored.")


def cmd_promote(args):
    if not args:
        print("Usage: am promote <episode_id>")
        return
    result = _post(f"/api/episodes/{args[0]}/promote")
    if "error" in result:
        print(f"Error: {result['error']}")
        return
    ids = result.get("knowledge_ids", [])
    print(f"Promoted {len(ids)} lessons from episode #{args[0]} to knowledge.")


def cmd_maintenance():
    result = _post("/api/maintenance")
    if "error" in result:
        print(f"Error: {result['error']}")
        return
    print(f"Working memory cleaned: {result.get('cleaned_wm', 0)}")
    print(f"Tasks cleaned:         {result.get('cleaned_tasks', 0)}")
    print(f"Knowledge decayed:     {result.get('decayed_knowledge', 0)}")


def cmd_dashboard():
    import webbrowser
    webbrowser.open(f"{BASE}/")


def main():
    args = sys.argv[1:]
    if not args:
        print("Agent Memory CLI")
        print()
        print("Commands:")
        print("  am status                              Stats (all tiers)")
        print("  am state [agent] [status] [task]       Agent state")
        print("  am tasks [--all] [status] [agent]      List tasks")
        print("  am task create/claim/done/fail          Task operations")
        print("  am events [--since N] [--type T]       Event log")
        print("  am event <type> <source> [data]        Log event")
        print("  am handoff <from> <to> <title>         Handoff")
        print()
        print("  am session start <agent>               Start session")
        print("  am session end <id> <title> [--outcome O]")
        print("  am session list [agent]                List sessions")
        print("  am wm <agent> [key] [value]            Working memory")
        print("  am episodes [--tag X] [-q QUERY]       Search episodes")
        print("  am episode <id>                        Episode detail")
        print("  am know [subject]                      Recall knowledge")
        print("  am learn <subj> <pred> <obj>           Store knowledge")
        print("  am forget <id>                         Deactivate knowledge")
        print("  am context <topic>                     Cross-tier context")
        print("  am agents                              List agent profiles")
        print("  am onboarding [agent]                  Print canonical onboarding")
        print("  am chat [--agent A] [--channel C]      List chat messages")
        print("  am say <sender> <message...>           Store chat message")
        print("  am promote <episode_id>                Promote lessons -> knowledge")
        print("  am maintenance                         Run cleanup + decay")
        print("  am dashboard                           Open web UI")
        return

    cmd = args[0]
    rest = args[1:]

    if cmd == "status":
        cmd_status()
    elif cmd == "state":
        cmd_state(rest)
    elif cmd == "tasks":
        cmd_tasks(rest)
    elif cmd == "task":
        if rest and rest[0] == "create":
            cmd_task_create(rest[1:])
        elif rest and rest[0] == "claim":
            cmd_task_claim(rest[1:])
        elif rest and rest[0] == "done":
            cmd_task_done(rest[1:])
        elif rest and rest[0] == "fail":
            cmd_task_fail(rest[1:])
        else:
            print("Usage: am task [create|claim|done|fail] ...")
    elif cmd == "events":
        cmd_events(rest)
    elif cmd == "event":
        cmd_event(rest)
    elif cmd == "handoff":
        cmd_handoff(rest)
    elif cmd == "session":
        cmd_session(rest)
    elif cmd == "wm":
        cmd_wm(rest)
    elif cmd == "episodes":
        cmd_episodes(rest)
    elif cmd == "episode":
        cmd_episode(rest)
    elif cmd == "know":
        cmd_know(rest)
    elif cmd == "learn":
        cmd_learn(rest)
    elif cmd == "forget":
        cmd_forget(rest)
    elif cmd == "context":
        cmd_context(rest)
    elif cmd == "agents":
        cmd_agents()
    elif cmd == "onboarding":
        cmd_onboarding(rest)
    elif cmd == "chat":
        cmd_chat(rest)
    elif cmd == "say":
        cmd_say(rest)
    elif cmd == "promote":
        cmd_promote(rest)
    elif cmd == "maintenance":
        cmd_maintenance()
    elif cmd == "dashboard":
        cmd_dashboard()
    else:
        print(f"Unknown command: {cmd}")
        print("Run 'am' without arguments for help.")


if __name__ == "__main__":
    main()
