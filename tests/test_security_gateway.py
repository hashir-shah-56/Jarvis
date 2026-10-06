"""Exact-action authorization, replay protection, isolation, and failures."""

import inspect
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import Mock, patch

from agent.permissions import PermissionDecision
from core.models import ExecutionResult, RiskLevel
from security import gateway
from security.audit import AuditError, AuditTrail
from security.gateway import SecurityGateway
from security.policies import PermissionPolicy
from tools import executor
from tools.registry import REGISTRY, RegisteredTool, ToolRegistry


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = ExecutionResult(True, "Completed")
        self.operations = {}
        entries = []
        for item in REGISTRY.list_metadata():
            tool = REGISTRY.get(item["name"])
            operation = Mock(return_value=self.result)
            self.operations[item["name"]] = operation
            entries.append(RegisteredTool(tool.metadata, operation))
        self.registry = ToolRegistry(entries)
        self.clock = Mock(return_value=100.0)
        self.audit = AuditTrail()
        self.gateway = SecurityGateway(registry=self.registry, audit=self.audit, clock=self.clock)

    def pending(self, name="file.create_directory", arguments=None):
        arguments = {"path": "private-original-path"} if arguments is None else arguments
        result = self.gateway.request_execution(name, arguments)
        self.assertEqual(result.error_id, "CONFIRMATION_REQUIRED")
        self.assertFalse(result.success)
        self.operations[name].assert_not_called()
        return result.data["confirmation_id"]

    def assert_no_calls(self):
        for operation in self.operations.values():
            operation.assert_not_called()

    def test_read_only_and_low_are_allowed_automatically(self) -> None:
        for name, arguments in (("system.get_cpu_info", {}), ("app.open_application", {"alias": "notepad"})):
            self.assertIs(self.gateway.request_execution(name, arguments), self.result)
            self.operations[name].assert_called_once_with(**arguments)
        self.assertEqual(self.gateway._pending, {})

    def test_all_medium_actions_wait_for_confirmation(self) -> None:
        self.pending()
        self.pending("file.rename_path", {"path": "old", "new_name": "new"})
        self.pending("file.move_path", {"source": "old", "destination": "new"})
        self.assert_no_calls()

    def test_high_risk_waits_for_explicit_confirmation(self) -> None:
        tool = self.registry.get("file.create_directory")
        high = ToolRegistry((RegisteredTool(replace(tool.metadata, risk_level=RiskLevel.HIGH), tool.implementation),))
        self.gateway = SecurityGateway(registry=high)
        identifier = self.pending()
        self.assertIs(self.gateway.confirm_execution(identifier), self.result)
        tool.implementation.assert_called_once_with(path="private-original-path")

    def test_explicit_denial_never_creates_confirmation(self) -> None:
        self.gateway = SecurityGateway(registry=self.registry, audit=self.audit,
            policy=PermissionPolicy(frozenset({"file.create_directory", "system.get_cpu_info"})))
        with patch("security.gateway.secrets.token_urlsafe") as token:
            for name, args in (("file.create_directory", {"path": "private"}), ("system.get_cpu_info", {})):
                self.assertEqual(self.gateway.request_execution(name, args).error_id, "PERMISSION_DENIED")
            token.assert_not_called()
        self.assertEqual(self.gateway._pending, {})
        self.assert_no_calls()
        self.assertEqual([r["event"] for r in self.audit.snapshot()], ["permission_denied"] * 2)

    def test_invalid_requests_fail_before_policy_or_confirmation(self) -> None:
        cases = [
            (None, {}, "INVALID_TOOL_NAME"), ("", {}, "INVALID_TOOL_NAME"),
            ("os.system", {}, "TOOL_NOT_FOUND"),
            ("file.create_directory", {}, "INVALID_TOOL_ARGUMENTS"),
            ("file.create_directory", None, "INVALID_TOOL_ARGUMENTS"),
            ("file.create_directory", {"path": []}, "INVALID_TOOL_ARGUMENTS"),
            ("file.create_directory", {"path": ""}, "INVALID_TOOL_ARGUMENTS"),
        ]
        with patch("security.gateway.evaluate_permission") as evaluate, patch("security.gateway.secrets.token_urlsafe") as token:
            for name, arguments, error in cases:
                self.assertEqual(self.gateway.request_execution(name, arguments).error_id, error)
            evaluate.assert_not_called()
            token.assert_not_called()
        self.assertEqual(self.gateway._pending, {})
        self.assert_no_calls()

    def test_request_cannot_override_risk_or_supply_approval_or_id(self) -> None:
        for key, value in (("risk", "read_only"), ("confirmed", True), ("user_approved", True), ("confirmation_id", "x" * 43)):
            result = self.gateway.request_execution("file.create_directory", {"path": "private", key: value})
            self.assertEqual(result.error_id, "INVALID_TOOL_ARGUMENTS")
        with self.assertRaises(TypeError):
            self.gateway.request_execution("file.create_directory", {"path": "private"}, confirmed=True)
        self.assert_no_calls()
        self.assertEqual(self.gateway._pending, {})

    def test_invalid_registered_risk_denies(self) -> None:
        tool = self.registry.get("file.create_directory")
        for risk in (None, "read_only", "unknown"):
            registry = ToolRegistry((RegisteredTool(replace(tool.metadata, risk_level=risk), tool.implementation),))
            service = SecurityGateway(registry=registry)
            self.assertEqual(service.request_execution(tool.metadata.name, {"path": "private"}).error_id, "PERMISSION_DENIED")
            self.assertEqual(service._pending, {})
        self.assert_no_calls()

    def test_policy_exceptions_and_unknown_decisions_deny(self) -> None:
        for options in ({"side_effect": RuntimeError("private-policy")}, {"return_value": None}, {"return_value": "allow"}):
            with patch("security.gateway.evaluate_permission", **options):
                self.assertEqual(self.gateway.request_execution("file.create_directory", {"path": "private"}).error_id, "PERMISSION_DENIED")
        self.assert_no_calls()
        self.assertEqual(self.gateway._pending, {})

    def test_opaque_random_id_and_conservative_display(self) -> None:
        first = self.pending()
        second = self.pending()
        self.assertRegex(first, r"^[A-Za-z0-9_-]{43}$")
        self.assertNotEqual(first, second)
        with patch("security.gateway.secrets.token_urlsafe", wraps=gateway.secrets.token_urlsafe) as token:
            result = self.gateway.request_execution("file.create_directory", {"path": "secret-path"})
            token.assert_called_once_with(32)
        self.assertEqual(result.data["expires_in_seconds"], 300)
        self.assertEqual(result.data["description"], self.registry.get("file.create_directory").metadata.description)
        self.assertNotIn("secret-path", json.dumps(result.data))
        self.assertEqual(result.data["risk_level"], "medium")

    def test_confirmation_executes_original_arguments_despite_mutation(self) -> None:
        arguments = {"source": "private-original", "destination": "private-target"}
        identifier = self.pending("file.move_path", arguments)
        arguments.update(source="different", destination="different", confirmed=True)
        self.assertIs(self.gateway.confirm_execution(identifier), self.result)
        self.operations["file.move_path"].assert_called_once_with(source="private-original", destination="private-target")

    def test_nested_schema_objects_are_snapshotted_and_non_json_values_rejected(self) -> None:
        tool = self.registry.get("file.create_directory")
        schema = {"type": "object", "properties": {"details": {
            "type": "object", "properties": {"name": {"type": "string"}},
            "required": ["name"], "additionalProperties": False,
        }}, "required": ["details"], "additionalProperties": False}
        registry = ToolRegistry((RegisteredTool(replace(tool.metadata, arguments_schema=schema), tool.implementation),))
        self.gateway = SecurityGateway(registry=registry)
        for value in (object(), Path("private"), {"bad"}, b"private", ["private"]):
            self.assertEqual(self.gateway.request_execution(tool.metadata.name, {"details": {"name": value}}).error_id, "INVALID_TOOL_ARGUMENTS")
        args = {"details": {"name": "original"}}
        identifier = self.pending(arguments=args)
        args["details"]["name"] = "changed"
        self.gateway.confirm_execution(identifier)
        tool.implementation.assert_called_once_with(details={"name": "original"})

    def test_confirmation_api_accepts_only_id_not_replacement_action(self) -> None:
        identifier = self.pending()
        self.assertEqual(list(inspect.signature(self.gateway.confirm_execution).parameters), ["confirmation_id"])
        for changes in ({"tool_name": "file.move_path"}, {"arguments": {"path": "other"}}, {"confirmed": True}):
            with self.assertRaises(TypeError):
                self.gateway.confirm_execution(identifier, **changes)
        self.assert_no_calls()
        self.assertIs(self.gateway.confirm_execution(identifier), self.result)

    def test_unknown_malformed_consumed_and_rejected_ids_share_not_found(self) -> None:
        for identifier in (None, "", [], {}, 2, True, "x" * 43, "x" * 10000, "private/path", "☃" * 43):
            self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "CONFIRMATION_NOT_FOUND")
        self.assert_no_calls()

    def test_ttl_boundary_and_replay_after_expiration(self) -> None:
        identifier = self.pending()
        self.clock.return_value = 400.0
        self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "CONFIRMATION_EXPIRED")
        self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "CONFIRMATION_NOT_FOUND")
        self.assertEqual(self.gateway._pending, {})
        self.assert_no_calls()

    def test_just_before_expiry_is_valid_despite_wall_clock_changes(self) -> None:
        identifier = self.pending()
        self.clock.return_value = 399.999
        with patch("time.time", return_value=-999999):
            self.assertIs(self.gateway.confirm_execution(identifier), self.result)

    def test_success_consumes_confirmation(self) -> None:
        identifier = self.pending()
        self.assertIs(self.gateway.confirm_execution(identifier), self.result)
        self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "CONFIRMATION_NOT_FOUND")
        self.operations["file.create_directory"].assert_called_once()

    def test_failure_exception_and_wrong_result_still_consume_confirmation(self) -> None:
        operation = self.operations["file.create_directory"]
        for value in (ExecutionResult(False, "Unavailable", error_id="ACCESS_DENIED"), None, "private-result", RuntimeError("private-exception")):
            operation.reset_mock()
            operation.side_effect = value if isinstance(value, Exception) else None
            operation.return_value = value
            identifier = self.pending()
            result = self.gateway.confirm_execution(identifier)
            self.assertFalse(result.success)
            self.assertNotIn("private", result.message)
            self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "CONFIRMATION_NOT_FOUND")
            operation.assert_called_once()

    def test_rejection_discards_action(self) -> None:
        identifier = self.pending()
        self.assertTrue(self.gateway.reject_confirmation(identifier).success)
        self.assertEqual(self.gateway.reject_confirmation(identifier).error_id, "CONFIRMATION_NOT_FOUND")
        self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "CONFIRMATION_NOT_FOUND")
        self.assert_no_calls()

    def test_rejection_of_expired_and_malformed_ids_is_safe(self) -> None:
        identifier = self.pending()
        self.clock.return_value = 400.0
        self.assertEqual(self.gateway.reject_confirmation(identifier).error_id, "CONFIRMATION_EXPIRED")
        self.assertEqual(self.gateway.reject_confirmation([]).error_id, "CONFIRMATION_NOT_FOUND")
        self.assert_no_calls()

    def test_two_pending_actions_remain_independent(self) -> None:
        first = self.pending()
        second = self.pending("file.rename_path", {"path": "old", "new_name": "new"})
        self.gateway.confirm_execution(second)
        self.operations["file.rename_path"].assert_called_once_with(path="old", new_name="new")
        self.operations["file.create_directory"].assert_not_called()
        self.gateway.reject_confirmation(first)
        self.assertEqual(self.gateway.confirm_execution(first).error_id, "CONFIRMATION_NOT_FOUND")

    def test_isolated_gateway_cannot_use_another_gateways_id(self) -> None:
        identifier = self.pending()
        other = SecurityGateway(registry=self.registry)
        self.assertEqual(other.confirm_execution(identifier).error_id, "CONFIRMATION_NOT_FOUND")
        self.assertIs(self.gateway.confirm_execution(identifier), self.result)

    def test_policy_is_rechecked_and_denial_consumes_pending_action(self) -> None:
        identifier = self.pending()
        with patch("security.gateway.evaluate_permission", return_value=PermissionDecision.DENY):
            self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "PERMISSION_DENIED")
        self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "CONFIRMATION_NOT_FOUND")
        self.assert_no_calls()

    def test_stored_binding_is_not_re_resolved_to_a_different_tool(self) -> None:
        identifier = self.pending()
        with patch.object(self.gateway, "_registry") as registry:
            self.assertIs(self.gateway.confirm_execution(identifier), self.result)
            registry.get.assert_not_called()
        self.operations["file.create_directory"].assert_called_once()

    def test_concurrent_confirmations_execute_at_most_once(self) -> None:
        identifier = self.pending()
        barrier = Barrier(8)
        def confirm(_):
            barrier.wait(timeout=5)
            return self.gateway.confirm_execution(identifier)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(confirm, range(8)))
        self.assertEqual(sum(result.success for result in results), 1)
        self.assertEqual(sum(result.error_id == "CONFIRMATION_NOT_FOUND" for result in results), 7)
        self.operations["file.create_directory"].assert_called_once()

    def test_confirmation_and_rejection_race_has_one_winner(self) -> None:
        identifier = self.pending()
        barrier = Barrier(2)
        def run(method):
            barrier.wait(timeout=5)
            return method(identifier)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, (self.gateway.confirm_execution, self.gateway.reject_confirmation)))
        self.assertEqual(sum(result.success for result in results), 1)
        self.assertEqual(sum(result.error_id == "CONFIRMATION_NOT_FOUND" for result in results), 1)
        self.assertLessEqual(self.operations["file.create_directory"].call_count, 1)

    def test_pending_capacity_and_expiry_cleanup_are_bounded(self) -> None:
        with patch("security.gateway._MAX_PENDING", 2):
            first = self.pending()
            self.pending()
            self.assertEqual(self.gateway.request_execution("file.create_directory", {"path": "third"}).error_id, "CONFIRMATION_UNAVAILABLE")
            self.assertEqual(len(self.gateway._pending), 2)
            self.clock.return_value = 400.0
            self.pending()
        self.assertEqual(len(self.gateway._pending), 1)
        self.assertEqual(self.gateway.confirm_execution(first).error_id, "CONFIRMATION_NOT_FOUND")
        self.assert_no_calls()

    def test_token_collision_never_overwrites_existing_action(self) -> None:
        identifier = self.pending()
        with patch("security.gateway.secrets.token_urlsafe", return_value=identifier):
            result = self.gateway.request_execution("file.create_directory", {"path": "replacement"})
        self.assertEqual(result.error_id, "CONFIRMATION_UNAVAILABLE")
        self.gateway.confirm_execution(identifier)
        self.operations["file.create_directory"].assert_called_once_with(path="private-original-path")

    def test_clock_failure_fails_closed_and_consumes_taken_id(self) -> None:
        for value in (99.0, float("nan"), float("inf"), True):
            self.clock.return_value = 100.0
            identifier = self.pending()
            self.clock.return_value = value
            self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "TOOL_EXECUTION_FAILED")
            self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "CONFIRMATION_NOT_FOUND")
        self.assert_no_calls()

    def test_entropy_source_failure_creates_no_confirmation(self) -> None:
        with patch("security.gateway.secrets.token_urlsafe", side_effect=RuntimeError("secret-entropy")):
            result = self.gateway.request_execution("file.create_directory", {"path": "private"})
        self.assertEqual(result.error_id, "TOOL_EXECUTION_FAILED")
        self.assertEqual(self.gateway._pending, {})
        self.assert_no_calls()

    def test_audit_failure_before_execution_fails_closed(self) -> None:
        with patch.object(self.audit, "record", side_effect=AuditError()):
            for name, args in (("system.get_cpu_info", {}), ("file.create_directory", {"path": "private"})):
                self.assertEqual(self.gateway.request_execution(name, args).error_id, "SECURITY_AUDIT_FAILED")
        self.assert_no_calls()
        self.assertEqual(self.gateway._pending, {})

    def test_audit_failure_after_confirmation_still_consumes_id(self) -> None:
        identifier = self.pending()
        with patch.object(self.audit, "record", side_effect=AuditError()):
            self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "SECURITY_AUDIT_FAILED")
        self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "CONFIRMATION_NOT_FOUND")
        self.assert_no_calls()

    def test_completion_audit_failure_cannot_replay_action(self) -> None:
        identifier = self.pending()
        with patch.object(self.audit, "record", side_effect=[None, None, AuditError()]):
            result = self.gateway.confirm_execution(identifier)
        self.assertEqual(result.error_id, "SECURITY_AUDIT_FAILED")
        self.assertIn("check action state", result.message)
        self.assertEqual(self.gateway.confirm_execution(identifier).error_id, "CONFIRMATION_NOT_FOUND")
        self.operations["file.create_directory"].assert_called_once()

    def test_public_executor_and_gateway_share_security_and_trusted_apis(self) -> None:
        with patch.object(gateway, "_DEFAULT_GATEWAY", self.gateway):
            result = executor.execute_tool("file.create_directory", {"path": "private"})
            self.assertEqual(result.error_id, "CONFIRMATION_REQUIRED")
            self.assert_no_calls()
            self.assertIs(gateway.confirm_execution(result.data["confirmation_id"]), self.result)
            result = gateway.request_execution("file.rename_path", {"path": "old", "new_name": "new"})
            self.assertTrue(gateway.reject_confirmation(result.data["confirmation_id"]).success)
        self.operations["file.rename_path"].assert_not_called()

    def test_confirmation_is_not_a_registered_tool(self) -> None:
        self.assertEqual(len(REGISTRY.list_metadata()), 16)
        for name in ("confirm_execution", "security.confirm_execution", "reject_confirmation", "security.reject_confirmation"):
            self.assertFalse(REGISTRY.contains(name))
            self.assertEqual(self.gateway.request_execution(name, {}).error_id, "TOOL_NOT_FOUND")

    def test_confirmed_real_tool_retains_stage_2_no_overwrite_check(self) -> None:
        service = SecurityGateway()
        with TemporaryDirectory() as temporary:
            existing = Path(temporary) / "existing"
            existing.mkdir()
            result = service.request_execution("file.create_directory", {"path": str(existing)})
            self.assertEqual(result.error_id, "CONFIRMATION_REQUIRED")
            confirmed = service.confirm_execution(result.data["confirmation_id"])
            self.assertEqual(confirmed.error_id, "DESTINATION_EXISTS")
            self.assertTrue(existing.is_dir())
