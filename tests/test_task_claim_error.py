"""Tests for api_tasks_claim error handling (CodeQL #1)."""

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestTaskClaimErrorHandling(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
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

    def test_claim_error_does_not_leak_exception_details(self):
        """Internal exceptions must not expose stack traces to clients."""
        with patch.object(self.mem, "claim_task", side_effect=RuntimeError("db locked: /secret/path")):
            resp = self.client.post("/api/tasks/1/claim", json={"agent": "test"})

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertEqual(data["error"], "internal error")
        self.assertNotIn("db locked", data["error"])
        self.assertNotIn("/secret/path", data["error"])

    def test_claim_error_logs_internally(self):
        """The actual exception must be logged server-side."""
        with patch.object(self.mem, "claim_task", side_effect=RuntimeError("db locked")), \
             patch("daemon.log") as mock_log:
            self.client.post("/api/tasks/1/claim", json={"agent": "test"})

        mock_log.exception.assert_called_once()
        args = mock_log.exception.call_args[0]
        self.assertIn("claim task", args[0].lower())
