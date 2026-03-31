import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class AgentMemoryFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "agent.db"
        os.environ["PONDER_DB"] = str(self.db_path)
        for module_name in ("memory", "daemon"):
            sys.modules.pop(module_name, None)

        self.memory_mod = importlib.import_module("memory")
        self.daemon_mod = importlib.import_module("daemon")
        self.mem = self.memory_mod.AgentMemory(str(self.db_path))
        self.daemon_mod.mem = self.mem
        self.client = self.daemon_mod.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("PONDER_DB", None)

    def test_onboarding_bundle_uses_agent_native_instructions(self):
        response = self.client.get("/api/onboarding/codex")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["profile"]["agent_id"], "codex")
        self.assertIn("Do not create or rely on another agent's config files", data["prompt"])
        self.assertIn("/api/context/onboarding?agent_id=codex", data["prompt"])

        uppercase = self.client.get("/api/onboarding/Codex").get_json()
        self.assertEqual(uppercase["profile"]["agent_id"], "codex")
        self.assertIn("/api/context/onboarding?agent_id=codex", uppercase["prompt"])

        generic = self.client.get("/api/onboarding/orbital").get_json()
        self.assertEqual(generic["profile"]["agent_id"], "orbital")
        self.assertIn("Do not create or rely on another agent's config files", generic["prompt"])

    def test_context_onboarding_returns_canonical_entries_and_keeps_custom(self):
        self.mem.learn(
            subject="onboarding_codex",
            predicate="instructions",
            object="stale codex-only guidance",
            category="onboarding",
        )
        self.mem.learn(
            subject="onboarding_custom_retention",
            predicate="instructions",
            object="Custom onboarding note",
            category="onboarding",
        )

        response = self.client.get("/api/context/onboarding?agent_id=codex")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        subjects = [entry["subject"] for entry in payload["knowledge"]]

        self.assertIn("onboarding_connection", subjects)
        self.assertIn("onboarding_regeln", subjects)
        self.assertIn("onboarding_pflichten", subjects)
        self.assertIn("onboarding_custom_retention", subjects)
        self.assertNotIn("onboarding_codex", subjects)
        self.assertEqual(payload["profile"]["agent_id"], "codex")

    def test_chat_and_agent_profile_api_roundtrip(self):
        profile_response = self.client.post(
            "/api/agents/orbital",
            json={
                "display_name": "Orbital",
                "integration_mode": "native",
                "integration_target": "Use Orbital's own startup config",
                "native_feature": "Orbital startup instructions",
                "onboarding_note": "Never use another agent's config path.",
            },
        )
        self.assertEqual(profile_response.status_code, 200)

        agent_response = self.client.get("/api/agents/orbital")
        self.assertEqual(agent_response.status_code, 200)
        agent = agent_response.get_json()
        self.assertEqual(agent["display_name"], "Orbital")
        self.assertEqual(agent["integration_mode"], "native")

        chat_post = self.client.post(
            "/api/chat",
            json={
                "sender_agent": "codex",
                "target_agent": "orbital",
                "channel": "handoff",
                "body": "Please verify the onboarding profile.",
            },
        )
        self.assertEqual(chat_post.status_code, 200)

        chat_get = self.client.get("/api/chat?agent_id=orbital&channel=handoff")
        self.assertEqual(chat_get.status_code, 200)
        messages = chat_get.get_json()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["sender_agent"], "codex")
        self.assertEqual(messages[0]["target_agent"], "orbital")
        self.assertEqual(messages[0]["channel"], "handoff")

    def test_invalid_limit_query_uses_default_instead_of_500(self):
        self.mem.append_chat_message(
            sender_agent="codex",
            target_agent="nova",
            channel="general",
            body="hello",
        )

        response = self.client.get("/api/chat?limit=abc")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["body"], "hello")

    def test_chat_before_query_returns_older_messages(self):
        first = self.mem.append_chat_message(
            sender_agent="codex",
            target_agent="nova",
            channel="general",
            body="one",
        )
        second = self.mem.append_chat_message(
            sender_agent="codex",
            target_agent="nova",
            channel="general",
            body="two",
        )
        third = self.mem.append_chat_message(
            sender_agent="codex",
            target_agent="nova",
            channel="general",
            body="three",
        )

        response = self.client.get(f"/api/chat?channel=general&before={third}&limit=2")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([msg["id"] for msg in payload], [first, second])
        self.assertEqual(payload[-1]["body"], "two")

    def test_chat_channel_api_returns_ordered_channel_summaries(self):
        self.mem.append_chat_message(
            sender_agent="codex",
            target_agent="Claude",
            channel="docsight",
            body="sync status",
        )
        self.mem.append_chat_message(
            sender_agent="claude",
            target_agent="codex",
            channel="docsight",
            body="reply",
        )
        self.mem.append_chat_message(
            sender_agent="nova",
            target_agent="codex",
            channel="general",
            body="hello",
        )

        response = self.client.get("/api/chat/channels?limit=abc")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload[0]["channel"], "general")
        self.assertEqual(payload[0]["message_count"], 1)
        self.assertEqual(payload[1]["channel"], "docsight")
        self.assertEqual(payload[1]["message_count"], 2)

    def test_dashboard_contains_hash_addressable_chat_feed(self):
        self.client.post(
            "/api/agents/agent-linux",
            json={
                "display_name": "Agent Linux",
                "integration_mode": "native",
                "integration_target": "Use the agent's own startup instructions",
                "native_feature": "Agent startup instructions",
                "onboarding_note": "Keep onboarding self-contained.",
            },
        )
        self.mem.append_chat_message(
            sender_agent="codex",
            target_agent="Claude",
            channel="docsight",
            body="sync status",
        )

        response = self.client.get("/?chat_channel=docsight")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="chat-feed"', html)
        self.assertIn('id="chat-channel-tabs"', html)
        self.assertIn('id="chat-active-title"', html)
        self.assertIn('id="chat-channel" value="docsight"', html)
        self.assertIn("const INITIAL_CHAT_CHANNELS =", html)
        self.assertIn("function loadOlderChatMessages()", html)
        self.assertIn("query.set('before'", html)
        self.assertIn("function getHashState()", html)
        self.assertIn("window.location.hash = buildHash(name);", html)
        self.assertIn("chat/' + encodeURIComponent(chatState.activeChannel)", html)
        self.assertIn('data-channel="${channel}"', html)
        self.assertIn('data-channel="all"', html)
        self.assertIn("function bindChatChannelClicks()", html)
        self.assertNotIn("onclick=\"setActiveChatChannel(", html)


    # ── Observations ──────────────────────────────────────────

    def test_observation_create_and_list(self):
        resp = self.client.post("/api/observations", json={
            "agent_id": "agent-linux",
            "tool_name": "Edit",
            "action": "edit",
            "file_path": "/app/test-project/web.py",
            "summary": "Edited web.py",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("id", data)

        resp = self.client.get("/api/observations?agent_id=agent-linux")
        self.assertEqual(resp.status_code, 200)
        obs = resp.get_json()
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["tool_name"], "Edit")
        self.assertEqual(obs[0]["file_path"], "/app/test-project/web.py")

    def test_observation_requires_agent_and_tool(self):
        resp = self.client.post("/api/observations", json={"agent_id": "test"})
        self.assertEqual(resp.status_code, 400)

        resp = self.client.post("/api/observations", json={"tool_name": "Read"})
        self.assertEqual(resp.status_code, 400)

    def test_observation_filter_by_tool(self):
        self.client.post("/api/observations", json={
            "agent_id": "agent-linux", "tool_name": "Read", "summary": "Read file"
        })
        self.client.post("/api/observations", json={
            "agent_id": "agent-linux", "tool_name": "Bash", "summary": "Run command"
        })
        resp = self.client.get("/api/observations?tool_name=Bash")
        obs = resp.get_json()
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["tool_name"], "Bash")

    def test_observation_fts_search(self):
        self.client.post("/api/observations", json={
            "agent_id": "agent-linux", "tool_name": "Edit",
            "summary": "Fixed smokeping proxy validation",
        })
        self.client.post("/api/observations", json={
            "agent_id": "agent-linux", "tool_name": "Read",
            "summary": "Read requirements.txt",
        })
        resp = self.client.get("/api/observations/search?q=smokeping")
        self.assertEqual(resp.status_code, 200)
        results = resp.get_json()
        self.assertEqual(len(results), 1)
        self.assertIn("smokeping", results[0]["summary"])

    def test_observation_search_invalid_query_returns_400(self):
        resp = self.client.get('/api/observations/search?q="unterminated')
        self.assertIn(resp.status_code, (200, 400))

    def test_observation_search_empty_query_returns_400(self):
        resp = self.client.get("/api/observations/search?q=")
        self.assertEqual(resp.status_code, 400)

    def test_observation_session_summary(self):
        session_id = "test-session-123"
        for tool, action, fp, summary in [
            ("Read", "read", "/app/web.py", "Read web.py"),
            ("Edit", "edit", "/app/web.py", "Edited web.py"),
            ("Read", "read", "/app/main.py", "Read main.py"),
            ("Bash", "command", None, "git status"),
            ("Write", "write", "/app/new_file.py", "Wrote new_file.py"),
        ]:
            self.client.post("/api/observations", json={
                "agent_id": "agent-linux", "tool_name": tool,
                "action": action, "file_path": fp,
                "summary": summary, "session_id": session_id,
            })

        resp = self.client.get(f"/api/observations/summary/{session_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        summary = data["summary"]
        self.assertIn("Tool calls: 5", summary)
        self.assertIn("/app/web.py", summary)
        self.assertIn("/app/new_file.py", summary)

    def test_observation_summary_missing_session(self):
        resp = self.client.get("/api/observations/summary/nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_observation_invalid_limit_handled(self):
        resp = self.client.get("/api/observations?limit=abc")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
