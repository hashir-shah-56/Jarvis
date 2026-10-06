"""Permission decisions consume trusted metadata and can only restrict policy."""

import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

from agent.permissions import PermissionDecision
from core.models import RiskLevel
from security.permissions import evaluate_permission
from security.policies import PermissionPolicy
from tools.registry import REGISTRY


class PermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata = REGISTRY.get("system.get_cpu_info").metadata

    def test_default_decision_for_every_risk(self) -> None:
        for risk, expected in (
            (RiskLevel.READ_ONLY, PermissionDecision.ALLOW),
            (RiskLevel.LOW, PermissionDecision.ALLOW),
            (RiskLevel.MEDIUM, PermissionDecision.REQUIRE_CONFIRMATION),
            (RiskLevel.HIGH, PermissionDecision.REQUIRE_CONFIRMATION),
        ):
            with self.subTest(risk=risk):
                self.assertIs(evaluate_permission(replace(self.metadata, risk_level=risk)), expected)

    def test_explicit_denial_overrides_all_risks(self) -> None:
        policy = PermissionPolicy(frozenset({self.metadata.name}))
        for risk in RiskLevel:
            self.assertIs(evaluate_permission(replace(self.metadata, risk_level=risk), policy), PermissionDecision.DENY)

    def test_policy_does_not_deny_other_names(self) -> None:
        self.assertIs(evaluate_permission(self.metadata, PermissionPolicy(frozenset({"file.move_path"}))), PermissionDecision.ALLOW)

    def test_invalid_metadata_and_unknown_risk_deny(self) -> None:
        for metadata in (
            None, {}, "read_only", replace(self.metadata, name=""),
            replace(self.metadata, description=None),
            replace(self.metadata, arguments_schema={}),
            *(replace(self.metadata, risk_level=value) for value in (None, "read_only", "unknown", 0, True)),
        ):
            with self.subTest(metadata=metadata):
                self.assertIs(evaluate_permission(metadata), PermissionDecision.DENY)

    def test_missing_or_invalid_policy_denies(self) -> None:
        for policy in (None, {}, "allow", True):
            self.assertIs(evaluate_permission(self.metadata, policy), PermissionDecision.DENY)

    def test_policy_evaluation_exception_denies(self) -> None:
        with patch("security.permissions._check_schema", side_effect=RuntimeError("secret-policy")):
            self.assertIs(evaluate_permission(self.metadata), PermissionDecision.DENY)

    def test_policy_is_immutable_and_has_no_risk_downgrade_setting(self) -> None:
        policy = PermissionPolicy(frozenset({"file.move_path"}))
        with self.assertRaises(FrozenInstanceError):
            policy.denied_tools = frozenset()
        with self.assertRaises(ValueError):
            PermissionPolicy({"file.move_path"})
        with self.assertRaises(TypeError):
            PermissionPolicy(high_requires_confirmation=False)

    def test_evaluation_has_no_tool_or_confirmation_side_effects(self) -> None:
        with patch("security.gateway._invoke_tool") as invoke, patch("security.gateway.secrets.token_urlsafe") as token:
            for risk in RiskLevel:
                evaluate_permission(replace(self.metadata, risk_level=risk))
        invoke.assert_not_called()
        token.assert_not_called()
