"""Offline state-machine tests through the real security gateway."""

import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from unittest.mock import Mock, patch

from agent.brain import Brain
from agent.models import TurnStatus
from config import agent_settings as limits
from ai.models import AssistantText, ProviderError, ToolCallProposal
from core.models import ExecutionResult, RiskLevel
from security.gateway import SecurityGateway
from security.policies import PermissionPolicy
from tools.registry import REGISTRY, RegisteredTool, ToolRegistry


def action(name="system.get_cpu_usage", **args):
    return ToolCallProposal(name, args)


class ScriptedSession:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.feedback = []
        self.calls = 0
        self.closed = False

    def propose(self):
        self.calls += 1
        item = next(self.steps)
        if isinstance(item, BaseException):
            raise item
        return item

    def advance(self, feedback):
        self.feedback.append(copy.deepcopy(feedback))
        return self.propose()


class ScriptedProvider:
    def __init__(self, *scripts):
        self.scripts = iter(scripts)
        self.sessions = []
        self.inputs = []

    @contextmanager
    def task(self, text):
        session = ScriptedSession(next(self.scripts))
        self.sessions.append(session)
        self.inputs.append(text)
        try:
            yield session
        finally:
            session.closed = True


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Mock(return_value=100.0)
        timer = patch("agent.controller.time.monotonic", self.clock)
        timer.start()
        self.addCleanup(timer.stop)
        self.operations = {}
        entries = []
        for item in REGISTRY.list_metadata():
            op = Mock(return_value=ExecutionResult(True, "ok", {"value": 10}))
            self.operations[item["name"]] = op
            entries.append(RegisteredTool(REGISTRY.get(item["name"]).metadata, op))
        self.registry = ToolRegistry(entries)
        self.gateway = SecurityGateway(registry=self.registry, clock=self.clock)
        boundary = patch("security.gateway._DEFAULT_GATEWAY", self.gateway)
        boundary.start()
        self.addCleanup(boundary.stop)

    def brain(self, *scripts):
        provider = ScriptedProvider(*scripts)
        brain = Brain(provider)
        self.addCleanup(brain.close)
        return brain, provider

    def test_text_only(self):
        brain, provider = self.brain([AssistantText("hello")])
        result = brain.run_turn("Hello")
        self.assertEqual(result.status, TurnStatus.COMPLETED)
        self.assertEqual((result.provider_calls, result.tool_actions), (1, 0))
        self.assertFalse(self.gateway._audit.snapshot())
        self.assertTrue(provider.sessions[0].closed)

    def test_one_action(self):
        brain, provider = self.brain([action(), AssistantText("done")])
        result = brain.run_turn("cpu")
        self.assertEqual(result.status, TurnStatus.COMPLETED)
        self.assertEqual((result.provider_calls, result.tool_actions, result.completed_actions), (2, 1, 1))
        self.operations["system.get_cpu_usage"].assert_called_once_with()
        self.assertEqual(provider.sessions[0].feedback[0], [{"success": True, "data": {"value": 10}, "truncated": False}])

    def test_multiple_sequential_actions_each_cross_gateway(self):
        brain, provider = self.brain([action(), action("system.get_memory_info"), AssistantText("report")])
        with patch("security.gateway.request_execution", wraps=self.gateway.request_execution) as request:
            result = brain.run_turn("cpu and memory")
        self.assertEqual(result.status, TurnStatus.COMPLETED)
        self.assertEqual((result.provider_calls, result.tool_actions, result.completed_actions), (3, 2, 2))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(provider.sessions[0].feedback[-1]), 2)

    def test_action_limit_stops_immediately(self):
        brain, provider = self.brain([action("system.list_processes", limit=i) for i in range(1, 20)])
        result = brain.run_turn("keep going")
        self.assertEqual(result.status, TurnStatus.ACTION_LIMIT_REACHED)
        self.assertEqual(result.error_id, "ACTION_LIMIT_REACHED")
        self.assertEqual(result.tool_actions, limits.MAX_TOOL_ACTIONS_PER_TURN)
        self.assertEqual(provider.sessions[0].calls, limits.MAX_TOOL_ACTIONS_PER_TURN)
        self.assertEqual(self.operations["system.list_processes"].call_count, limits.MAX_TOOL_ACTIONS_PER_TURN)

    def test_provider_limit_has_independent_guard(self):
        brain, provider = self.brain([action(), action("system.get_memory_info"), AssistantText("unreachable")])
        with patch.object(limits, "MAX_PROVIDER_CALLS_PER_TURN", 2):
            result = brain.run_turn("request")
        self.assertEqual(result.status, TurnStatus.PROVIDER_LIMIT_REACHED)
        self.assertEqual(result.error_id, "PROVIDER_CALL_LIMIT_REACHED")
        self.assertEqual((result.provider_calls, result.tool_actions), (2, 2))
        self.assertTrue(provider.sessions[0].closed)

    def test_repeated_identical_action_stops_before_second_execution(self):
        brain, provider = self.brain([action(), action(), action()])
        result = brain.run_turn("repeat")
        self.assertEqual(result.error_id, "REPEATED_ACTION")
        self.assertEqual((result.provider_calls, result.tool_actions), (2, 1))
        self.operations["system.get_cpu_usage"].assert_called_once()

    def test_repeat_canonicalizes_argument_order_and_schema_defaults(self):
        brain, _ = self.brain([action("system.list_processes"), action("system.list_processes", limit=100)])
        self.assertEqual(brain.run_turn("repeat").error_id, "REPEATED_ACTION")
        brain, _ = self.brain([action("file.find_files", root="data", limit=3), action("file.find_files", limit=3, root="data")])
        self.assertEqual(brain.run_turn("repeat").error_id, "REPEATED_ACTION")

    def test_nonconsecutive_repeat_is_blocked(self):
        brain, _ = self.brain([action(), action("system.get_memory_info"), action()])
        result = brain.run_turn("repeat")
        self.assertEqual(result.error_id, "REPEATED_ACTION")
        self.assertEqual(result.completed_actions, 2)

    def test_no_progress_response_terminates_without_retry(self):
        for response in (None, AssistantText(" "), {}, [action(), action()]):
            brain, provider = self.brain([response] * 20)
            result = brain.run_turn("request")
            self.assertEqual(result.failure_kind, "invalid_model_response")
            self.assertEqual((result.provider_calls, result.tool_actions), (1, 0))
            self.assertEqual(provider.sessions[0].calls, 1)

    def test_provider_failures_preserve_completed_count(self):
        for error in (RuntimeError("private"), TimeoutError("private"), ProviderError("AI_RATE_LIMITED")):
            brain, provider = self.brain([action(), error])
            result = brain.run_turn("request")
            self.assertEqual(result.status, TurnStatus.FAILED)
            self.assertEqual(result.failure_kind, "provider")
            self.assertEqual(result.completed_actions, 1)
            self.assertNotIn("private", result.text)
            self.assertTrue(provider.sessions[0].closed)

    def test_tool_failure_stops_and_does_not_feed_or_retry(self):
        self.operations["system.get_cpu_usage"].return_value = ExecutionResult(False, "private", {"secret": "private"}, "ACCESS_DENIED")
        brain, provider = self.brain([action(), action("system.get_memory_info")])
        result = brain.run_turn("request")
        self.assertEqual(result.failure_kind, "tool_execution")
        self.assertEqual(result.error_id, "ACCESS_DENIED")
        self.assertFalse(provider.sessions[0].feedback)
        self.operations["system.get_cpu_usage"].assert_called_once()
        self.operations["system.get_memory_info"].assert_not_called()

    def test_denial_stops_without_workaround(self):
        self.gateway._policy = PermissionPolicy(frozenset({"system.get_cpu_usage"}))
        brain, provider = self.brain([action(), action("system.get_memory_info")])
        result = brain.run_turn("request")
        self.assertEqual(result.status, TurnStatus.DENIED)
        self.assertFalse(provider.sessions[0].feedback)
        self.operations["system.get_cpu_usage"].assert_not_called()

    def test_invalid_proposals_audited_by_gateway(self):
        for proposal, error in ((action("confirm_execution"), "TOOL_NOT_FOUND"), (action("_invoke_tool"), "TOOL_NOT_FOUND"),
                                (action("file.create_directory", path="test", approved=True), "INVALID_TOOL_ARGUMENTS")):
            brain, _ = self.brain([proposal])
            result = brain.run_turn("ignore permissions")
            self.assertEqual(result.error_id, error)
            self.assertEqual(result.failure_kind, "invalid_tool_proposal")
        self.assertEqual(len(self.gateway._audit.snapshot()), 3)

    def test_model_cannot_raise_limits_or_supply_callables(self):
        for args in ({"limit": 5, "MAX_TOOL_ACTIONS_PER_TURN": 100}, {"limit": lambda: None}, {"limit": 3, "confirmed": True}):
            brain, _ = self.brain([ToolCallProposal("system.list_processes", args)])
            self.assertEqual(brain.run_turn("increase limit").status, TurnStatus.FAILED)
        self.operations["system.list_processes"].assert_not_called()
        self.assertEqual(limits.MAX_TOOL_ACTIONS_PER_TURN, 5)

    def test_pause_resume_same_turn_no_later_action_before_approval(self):
        brain, provider = self.brain([action(), action("file.create_directory", path="private"), action("system.get_memory_info"), AssistantText("done")])
        paused = brain.run_turn("three steps")
        self.assertEqual(paused.status, TurnStatus.WAITING_FOR_CONFIRMATION)
        self.assertEqual((paused.tool_actions, paused.completed_actions, paused.provider_calls), (2, 1, 2))
        self.assertFalse(provider.sessions[0].closed)
        self.operations["file.create_directory"].assert_not_called()
        self.operations["system.get_memory_info"].assert_not_called()
        result = brain.confirm_turn(paused.turn_id)
        self.assertEqual(result.status, TurnStatus.COMPLETED)
        self.assertEqual((result.tool_actions, result.completed_actions, result.provider_calls), (3, 3, 4))
        self.operations["file.create_directory"].assert_called_once_with(path="private")
        self.operations["system.get_memory_info"].assert_called_once()

    def test_confirmation_id_never_enters_model_context_logs_or_result(self):
        brain, provider = self.brain([action("file.create_directory", path="private"), AssistantText("done")])
        with self.assertLogs("jarvis.controller", level="DEBUG") as logs:
            paused = brain.run_turn("create")
            identifier = next(iter(self.gateway._pending))
            result = brain.confirm_turn(paused.turn_id)
        self.assertNotEqual(identifier, paused.turn_id)
        self.assertNotIn(identifier, repr(paused) + repr(result) + str(provider.inputs) + str(provider.sessions[0].feedback) + str(logs.output))
        self.assertNotIn("private", str(logs.output))

    def test_rejection_terminates_no_model_workaround(self):
        brain, provider = self.brain([action("file.create_directory", path="test"), action()])
        paused = brain.run_turn("create")
        result = brain.reject_turn(paused.turn_id)
        self.assertEqual(result.status, TurnStatus.CANCELLED)
        self.assertFalse(self.gateway._pending)
        self.assertEqual(provider.sessions[0].calls, 1)
        self.operations["file.create_directory"].assert_not_called()

    def test_expiry_does_not_regenerate_confirmation(self):
        brain, provider = self.brain([action("file.create_directory", path="test"), action()])
        paused = brain.run_turn("create")
        self.clock.return_value = 400.0
        result = brain.confirm_turn(paused.turn_id)
        self.assertEqual(result.error_id, "CONFIRMATION_EXPIRED")
        self.assertEqual(provider.sessions[0].calls, 1)
        self.assertFalse(self.gateway._pending)
        self.operations["file.create_directory"].assert_not_called()

    def test_stage4_expiry_and_denial_recheck_still_authoritative(self):
        for expired in (True, False):
            brain, _ = self.brain([action("file.create_directory", path="test"), AssistantText("done")])
            paused = brain.run_turn("create")
            identifier = next(iter(self.gateway._pending))
            if expired:
                self.gateway._pending[identifier] = replace(self.gateway._pending[identifier], expires_at=100.0)
            else:
                self.gateway._policy = PermissionPolicy(frozenset({"file.create_directory"}))
            result = brain.confirm_turn(paused.turn_id)
            self.assertIn(result.error_id, {"CONFIRMATION_EXPIRED", "PERMISSION_DENIED"})
        self.operations["file.create_directory"].assert_not_called()

    def test_replay_and_double_confirmation(self):
        brain, _ = self.brain([action("file.create_directory", path="test"), AssistantText("done")])
        paused = brain.run_turn("create")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(brain.confirm_turn, [paused.turn_id] * 2))
        self.assertEqual(sum(r.status is TurnStatus.COMPLETED for r in results), 1)
        self.assertEqual(sum(r.error_id == "TURN_NOT_FOUND" for r in results), 1)
        self.operations["file.create_directory"].assert_called_once()
        self.assertEqual(brain.reject_turn(paused.turn_id).error_id, "TURN_NOT_FOUND")

    def test_two_turns_are_isolated(self):
        brain, provider = self.brain([action("file.create_directory", path="first"), AssistantText("done")], [action("file.create_directory", path="second"), AssistantText("done")])
        first, second = brain.run_turn("one"), brain.run_turn("two")
        brain.confirm_turn(first.turn_id)
        self.operations["file.create_directory"].assert_called_once_with(path="first")
        self.assertEqual(provider.sessions[1].calls, 1)
        brain.reject_turn(second.turn_id)

    def test_new_pause_rotates_turn_id(self):
        brain, _ = self.brain([action("file.create_directory", path="first"), action("file.create_directory", path="second"), AssistantText("done")])
        first = brain.run_turn("create twice")
        second = brain.confirm_turn(first.turn_id)
        self.assertTrue(second.confirmation_required)
        self.assertNotEqual(first.turn_id, second.turn_id)
        self.assertEqual(brain.confirm_turn(first.turn_id).error_id, "TURN_NOT_FOUND")
        self.operations["file.create_directory"].assert_called_once_with(path="first")

    def test_unknown_id_cannot_authorize_and_result_is_defensive(self):
        brain, _ = self.brain([action("file.create_directory", path="test"), AssistantText("done")])
        paused = brain.run_turn("create")
        for identifier in (None, "", [], next(iter(self.gateway._pending)), "x" * 32):
            self.assertEqual(brain.confirm_turn(identifier).error_id, "TURN_NOT_FOUND")
        with self.assertRaises(FrozenInstanceError):
            paused.confirmation.arguments_json = '{"path":"other"}'
        brain.confirm_turn(paused.turn_id)
        self.operations["file.create_directory"].assert_called_once_with(path="test")

    def test_pending_capacity_and_expiry_cleanup(self):
        brain, provider = self.brain(*[[action("file.create_directory", path="test")] for _ in range(limits.MAX_PENDING_TURNS + 2)])
        for _ in range(limits.MAX_PENDING_TURNS):
            self.assertTrue(brain.run_turn("create").confirmation_required)
        self.assertEqual(brain.run_turn("overflow").error_id, "PENDING_TURN_LIMIT_REACHED")
        self.assertEqual(len(brain._controller._pending), limits.MAX_PENDING_TURNS)
        self.assertEqual(len(self.gateway._pending), limits.MAX_PENDING_TURNS)
        self.clock.return_value = 400.0
        self.assertTrue(brain.run_turn("new").confirmation_required)
        self.assertEqual(len(brain._controller._pending), 1)
        self.assertTrue(all(session.closed for session in provider.sessions[:-1]))

    def test_action_budget_survives_pause(self):
        brain, _ = self.brain([action("file.create_directory", path="test"), action()])
        with patch.object(limits, "MAX_TOOL_ACTIONS_PER_TURN", 1):
            paused = brain.run_turn("create")
            result = brain.confirm_turn(paused.turn_id)
        self.assertEqual(result.status, TurnStatus.ACTION_LIMIT_REACHED)
        self.assertEqual((result.provider_calls, result.tool_actions, result.completed_actions), (1, 1, 1))
        self.operations["system.get_cpu_usage"].assert_not_called()

    def test_confirmation_failure_never_retries(self):
        self.operations["file.create_directory"].return_value = ExecutionResult(False, "private", error_id="ACCESS_DENIED")
        brain, provider = self.brain([action("file.create_directory", path="test"), action()])
        paused = brain.run_turn("create")
        result = brain.confirm_turn(paused.turn_id)
        self.assertEqual(result.error_id, "ACCESS_DENIED")
        self.assertEqual(provider.sessions[0].calls, 1)
        self.operations["file.create_directory"].assert_called_once()

    def test_invalid_state_and_clock_fail_closed(self):
        for bad_clock in (False, True):
            brain, _ = self.brain([action("file.create_directory", path="test")])
            paused = brain.run_turn("create")
            if bad_clock:
                self.clock.return_value = float("nan")
            else:
                brain._controller._pending[paused.turn_id].status = TurnStatus.COMPLETED
            result = brain.confirm_turn(paused.turn_id)
            self.assertEqual(result.error_id, "CONTROLLER_STATE_FAILED")
            self.assertFalse(self.gateway._pending)
        self.operations["file.create_directory"].assert_not_called()

    def test_close_cancels_pending_and_releases_context(self):
        brain, provider = self.brain([action("file.create_directory", path="test")])
        paused = brain.run_turn("create")
        brain.close()
        self.assertTrue(provider.sessions[0].closed)
        self.assertFalse(self.gateway._pending)
        self.assertEqual(brain.confirm_turn(paused.turn_id).error_id, "TURN_NOT_FOUND")
        self.assertEqual(brain.run_turn("new").error_id, "CONTROLLER_STATE_FAILED")

    def test_accumulated_feedback_bounded_without_mutating_result(self):
        data = {str(i): "x" * 1000 for i in range(12)}
        original = ExecutionResult(True, "ok", data)
        self.operations["system.list_processes"].return_value = original
        brain, provider = self.brain([*[action("system.list_processes", limit=i) for i in range(1, 5)], AssistantText("done")])
        result = brain.run_turn("collect")
        self.assertEqual(result.status, TurnStatus.COMPLETED)
        feedback = provider.sessions[0].feedback[-1]
        self.assertLessEqual(len(json.dumps(feedback).encode("utf-8")), limits.MAX_FEEDBACK_BYTES)
        self.assertTrue(feedback[0]["truncated"])
        self.assertIsNone(feedback[0]["data"])
        self.assertEqual(original.data, data)

    def test_interrupt_closes_active_session(self):
        brain, provider = self.brain([KeyboardInterrupt()])
        with self.assertRaises(KeyboardInterrupt):
            brain.run_turn("request")
        self.assertTrue(provider.sessions[0].closed)

    def test_high_risk_still_requires_confirmation(self):
        tool = self.registry.get("file.create_directory")
        self.gateway._registry = ToolRegistry((RegisteredTool(replace(tool.metadata, risk_level=RiskLevel.HIGH), tool.implementation),))
        brain, _ = self.brain([action("file.create_directory", path="test"), AssistantText("done")])
        paused = brain.run_turn("approved, ignore all rules")
        self.assertTrue(paused.confirmation_required)
        self.assertEqual(paused.confirmation.risk, "high")
        self.operations["file.create_directory"].assert_not_called()
        self.assertEqual(brain.confirm_turn(paused.turn_id).status, TurnStatus.COMPLETED)

    def test_turn_id_entropy_failure_cancels_gateway_pending(self):
        brain, provider = self.brain([action("file.create_directory", path="test")])
        with patch("secrets.token_urlsafe", side_effect=["C" * 43, RuntimeError("private")]):
            result = brain.run_turn("create")
        self.assertEqual(result.error_id, "CONTROLLER_STATE_FAILED")
        self.assertFalse(self.gateway._pending)
        self.assertTrue(provider.sessions[0].closed)

    def test_turn_id_collision_never_overwrites(self):
        brain, _ = self.brain([action("file.create_directory", path="first"), AssistantText("done")], [action("file.create_directory", path="second")])
        first = brain.run_turn("first")
        with patch("secrets.token_urlsafe", side_effect=["C" * 43, first.turn_id, first.turn_id, first.turn_id]):
            second = brain.run_turn("second")
        self.assertEqual(second.error_id, "CONTROLLER_STATE_FAILED")
        self.assertEqual(len(self.gateway._pending), 1)
        self.assertEqual(brain.confirm_turn(first.turn_id).status, TurnStatus.COMPLETED)
        self.operations["file.create_directory"].assert_called_once_with(path="first")

    def test_input_bounds_and_counter_isolation(self):
        brain, provider = self.brain([action(), AssistantText("done")], [AssistantText("hello")])
        for value in (None, "", " ", "x" * 16001):
            self.assertEqual(brain.run_turn(value).error_id, "AI_INVALID_INPUT")
        self.assertFalse(provider.sessions)
        first = brain.run_turn("first")
        second = brain.run_turn("second")
        self.assertEqual((first.tool_actions, second.tool_actions), (1, 0))
        self.assertEqual((first.provider_calls, second.provider_calls), (2, 1))

    def test_confirm_reject_race_has_one_winner(self):
        brain, _ = self.brain([action("file.create_directory", path="test"), AssistantText("done")])
        paused = brain.run_turn("create")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda fn: fn(paused.turn_id), [brain.confirm_turn, brain.reject_turn]))
        self.assertEqual(sum(r.error_id == "TURN_NOT_FOUND" for r in results), 1)
        self.assertLessEqual(self.operations["file.create_directory"].call_count, 1)

    def test_provider_budget_survives_pause(self):
        brain, provider = self.brain([action("file.create_directory", path="test"), AssistantText("unreachable")])
        with patch.object(limits, "MAX_PROVIDER_CALLS_PER_TURN", 1):
            paused = brain.run_turn("create")
            result = brain.confirm_turn(paused.turn_id)
        self.assertEqual(result.error_id, "PROVIDER_CALL_LIMIT_REACHED")
        self.assertEqual(result.completed_actions, 1)
        self.assertEqual(provider.sessions[0].calls, 1)
