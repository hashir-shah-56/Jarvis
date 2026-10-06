"""Structured security records exclude sensitive values and capability IDs."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from agent.permissions import PermissionDecision
from core.models import ExecutionResult
from security.audit import AuditError, AuditEvent, AuditTrail, get_audit_records
from security.gateway import SecurityGateway
from security.policies import PermissionPolicy
from tools.registry import REGISTRY, RegisteredTool, ToolRegistry


class AuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = AuditTrail()
        self.clock = Mock(return_value=10.0)
        self.operation = Mock(return_value=ExecutionResult(True, "Completed"))
        entries = [RegisteredTool(REGISTRY.get(item["name"]).metadata, self.operation) for item in REGISTRY.list_metadata()]
        self.registry = ToolRegistry(entries)
        self.gateway = SecurityGateway(registry=self.registry, audit=self.audit, clock=self.clock)

    def test_allowed_and_confirmed_execution_event_order(self) -> None:
        self.gateway.request_execution("system.get_cpu_info", {})
        result = self.gateway.request_execution("file.create_directory", {"path": "private-path"})
        self.gateway.confirm_execution(result.data["confirmation_id"])
        records = self.audit.snapshot()
        self.assertEqual([record["event"] for record in records], [
            "request_allowed", "execution_attempted", "execution_completed",
            "confirmation_required", "confirmation_accepted", "execution_attempted", "execution_completed",
        ])
        for record in records:
            self.assertEqual(set(record), {"timestamp", "event", "tool_name", "risk_level", "decision", "error_id"})
            self.assertEqual(datetime.fromisoformat(record["timestamp"]).utcoffset().total_seconds(), 0)
            self.assertIn(record["tool_name"], {"system.get_cpu_info", "file.create_directory"})
        self.assertEqual(records[0]["decision"], "allow")
        self.assertEqual(records[3]["decision"], "require_confirmation")
        self.assertEqual(records[3]["error_id"], "CONFIRMATION_REQUIRED")

    def test_denial_rejection_expiration_and_failure_are_recorded(self) -> None:
        denied = SecurityGateway(registry=self.registry, audit=self.audit,
            policy=PermissionPolicy(frozenset({"system.get_cpu_info"})))
        denied.request_execution("system.get_cpu_info", {})
        result = self.gateway.request_execution("file.create_directory", {"path": "private"})
        self.gateway.reject_confirmation(result.data["confirmation_id"])
        result = self.gateway.request_execution("file.create_directory", {"path": "private"})
        self.clock.return_value = 310.0
        self.gateway.confirm_execution(result.data["confirmation_id"])
        self.gateway.confirm_execution("unknown-private-id")
        self.gateway.request_execution("unknown-private-name", {})
        self.operation.return_value = ExecutionResult(False, "Unavailable", error_id="ACCESS_DENIED")
        self.gateway.request_execution("system.get_cpu_info", {})
        events = [record["event"] for record in self.audit.snapshot()]
        for expected in ("permission_denied", "confirmation_rejected", "confirmation_expired", "confirmation_invalid", "request_rejected", "execution_failed"):
            self.assertIn(expected, events)
        self.assertEqual(self.audit.snapshot()[-1]["error_id"], "ACCESS_DENIED")

    def test_sensitive_values_never_enter_memory_or_jsonl_audit(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "security-audit.jsonl"
            audit = AuditTrail(path)
            service = SecurityGateway(registry=self.registry, audit=audit)
            secret = "DISTINCTIVE_FAKE_SECRET_927"
            requests = (
                ("file.create_directory", {"path": "C:/private/" + secret}),
                ("browser.open_url", {"url": "https://example.com/private?token=" + secret}),
                ("browser.search_web", {"query": secret + " query"}),
            )
            identifiers = []
            for name, arguments in requests:
                result = service.request_execution(name, arguments)
                if result.error_id == "CONFIRMATION_REQUIRED":
                    identifiers.append(result.data["confirmation_id"])
                    service.reject_confirmation(identifiers[-1])
            service.request_execution(secret, {"arbitrary": secret})
            self.operation.side_effect = RuntimeError(secret)
            service.request_execution("system.get_cpu_info", {})
            content = path.read_text(encoding="utf-8")
            self.assertEqual([json.loads(line) for line in content.splitlines()], audit.snapshot())
            for value in (secret, "C:/private", "https://", "Traceback", *identifiers):
                self.assertNotIn(value, content)
                self.assertNotIn(value, json.dumps(audit.snapshot()))

    def test_raw_result_errors_and_messages_are_not_audit_fields(self) -> None:
        self.operation.return_value = ExecutionResult(False, "private-message", {"secret": "private-data"}, "private-error")
        self.gateway.request_execution("system.get_cpu_info", {})
        content = json.dumps(self.audit.snapshot())
        self.assertNotIn("private", content)
        self.assertIsNone(self.audit.snapshot()[-1]["error_id"])

    def test_invalid_metadata_and_event_values_are_not_logged(self) -> None:
        metadata = replace(REGISTRY.get("system.get_cpu_info").metadata,
                           name="https://private/path", risk_level="private-risk")
        self.audit.record(AuditEvent.PERMISSION_DENIED, metadata, "private-decision", "private-error")
        self.assertNotIn("private", json.dumps(self.audit.snapshot()))
        with self.assertRaisesRegex(AuditError, "^SECURITY_AUDIT_FAILED$"):
            self.audit.record("private-event")

    def test_records_are_detached_and_bounded(self) -> None:
        for _ in range(1005):
            self.audit.record(AuditEvent.CONFIRMATION_INVALID)
        snapshot = self.audit.snapshot()
        self.assertEqual(len(snapshot), 1000)
        snapshot[0]["event"] = "tampered"
        snapshot.clear()
        self.assertEqual(len(self.audit.snapshot()), 1000)
        self.assertEqual(self.audit.snapshot()[0]["event"], "confirmation_invalid")

    def test_file_is_append_only_and_construction_has_no_file_side_effect(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "audit.jsonl"
            audit = AuditTrail(path)
            self.assertFalse(path.exists())
            audit.record(AuditEvent.REQUEST_ALLOWED)
            original = path.read_text(encoding="utf-8")
            AuditTrail(path).record(AuditEvent.PERMISSION_DENIED)
            self.assertTrue(path.read_text(encoding="utf-8").startswith(original))
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

    def test_file_write_failure_blocks_execution_without_leaking_path(self) -> None:
        with TemporaryDirectory() as temporary:
            audit = AuditTrail(Path(temporary) / "missing-private-parent" / "audit.jsonl")
            service = SecurityGateway(registry=self.registry, audit=audit)
            result = service.request_execution("system.get_cpu_info", {})
            self.assertEqual(result.error_id, "SECURITY_AUDIT_FAILED")
            self.assertNotIn("private", result.message)
            self.operation.assert_not_called()
            self.assertEqual(audit.snapshot()[0]["event"], "request_allowed")

    def test_concurrent_jsonl_records_are_complete(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "audit.jsonl"
            audit = AuditTrail(path)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda _: audit.record(AuditEvent.REQUEST_ALLOWED), range(40)))
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 40)
            self.assertEqual(records, audit.snapshot())

    def test_default_review_api_returns_only_sanitized_records(self) -> None:
        self.audit.record(AuditEvent.PERMISSION_DENIED, decision=PermissionDecision.DENY)
        with patch("security.audit._DEFAULT_AUDIT", self.audit):
            self.assertEqual(get_audit_records(), self.audit.snapshot())
