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
        os.environ["AGENT_MEMORY_DB"] = str(self.db_path)
        for module_name in ("memory", "daemon"):
            sys.modules.pop(module_name, None)

        self.memory_mod = importlib.import_module("memory")
        self.daemon_mod = importlib.import_module("daemon")
        self.mem = self.memory_mod.AgentMemory(str(self.db_path))
        self.daemon_mod.mem = self.mem
        self.client = self.daemon_mod.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("AGENT_MEMORY_DB", None)

    def test_onboarding_bundle_uses_agent_native_instructions(self):
        response = self.client.get("/api/onboarding/codex")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["profile"]["agent_id"], "codex")
        self.assertIn("Do not create or rely on ~/.claude/CLAUDE.md", data["prompt"])
        self.assertIn("/api/context/onboarding?agent_id=codex", data["prompt"])

        uppercase = self.client.get("/api/onboarding/Codex").get_json()
        self.assertEqual(uppercase["profile"]["agent_id"], "codex")
        self.assertIn("/api/context/onboarding?agent_id=codex", uppercase["prompt"])

        generic = self.client.get("/api/onboarding/orbital").get_json()
        self.assertEqual(generic["profile"]["agent_id"], "orbital")
        self.assertIn("Do not create configuration files for unrelated agent ecosystems", generic["prompt"])

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
        self.assertIn("function getHashState()", html)
        self.assertIn("window.location.hash = buildHash(name);", html)
        self.assertIn("chat/' + encodeURIComponent(chatState.activeChannel)", html)


if __name__ == "__main__":
    unittest.main()
