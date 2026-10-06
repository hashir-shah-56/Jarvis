"""Deterministic bounds, secret-key exclusion and no mutation or repr calls."""

import copy
import json
import unittest

from ai.sanitize import MAX_RESULT_BYTES, sanitize_result
from core.models import ExecutionResult


class SanitizerTests(unittest.TestCase):
    def check_bound(self, data):
        original = copy.deepcopy(data)
        result = ExecutionResult(True, "not sent", data)
        safe = sanitize_result(result)
        self.assertTrue(safe["truncated"])
        self.assertLessEqual(len(json.dumps(safe).encode("utf-8")), MAX_RESULT_BYTES)
        self.assertEqual(data, original)
        return safe

    def test_many_directory_entries(self):
        safe = self.check_bound({"entries": [{"name": str(i), "type": "file"} for i in range(500)]})
        self.assertEqual(len(safe["data"]["entries"]), 50)

    def test_many_processes(self):
        self.check_bound({"processes": [{"pid": i, "name": "process"} for i in range(500)]})

    def test_depth(self):
        data = {"value": 1}
        for _ in range(30):
            data = {"nested": data}
        self.check_bound(data)

    def test_long_strings_and_global_bytes(self):
        safe = self.check_bound({"text": "x" * 5000})
        self.assertEqual(len(safe["data"]["text"]), 1024)
        self.assertIsNone(self.check_bound({str(i): "☃" * 2000 for i in range(50)})["data"])

    def test_wide_nested_node_budget(self):
        self.check_bound({"tree": [[{"name": "entry"}] * 50] * 50})

    def test_arbitrary_objects_nonfinite_and_cycles(self):
        class Secret:
            def __repr__(self):
                raise AssertionError("Never represent arbitrary objects")
        cycle = {}
        cycle["self"] = cycle
        safe = sanitize_result(ExecutionResult(True, "secret", {"object": Secret(), "nan": float("nan"), "cycle": cycle, "big": 2**500}))
        self.assertTrue(safe["truncated"])
        json.dumps(safe, allow_nan=False)
        self.assertIsNone(safe["data"]["object"])

    def test_credentials_and_confirmation_keys_removed_at_any_depth(self):
        safe = sanitize_result(ExecutionResult(True, "private-message", {"nested": {"confirmation_id": "private-id", "GEMINI_API_KEY": "private-key", "Authorization": "private-auth"}}))
        self.assertNotIn("private", json.dumps(safe))
        self.assertTrue(safe["truncated"])

    def test_failure_and_pending_data_never_copied(self):
        for error in ("CONFIRMATION_REQUIRED", "PERMISSION_DENIED"):
            safe = sanitize_result(ExecutionResult(False, "private", {"other": "private-id"}, error))
            self.assertEqual(safe, {"success": False, "data": None, "truncated": False})
