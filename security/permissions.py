"""Fail-closed decisions on registered metadata, independent of any AI model."""

from agent.permissions import PermissionDecision
from core.models import RiskLevel
from security.policies import DEFAULT_POLICY, PermissionPolicy
from tools.base import ToolMetadata
from tools.schema import _check_schema


def evaluate_permission(
    metadata: ToolMetadata, policy: PermissionPolicy = DEFAULT_POLICY,
) -> PermissionDecision:
    """Evaluate metadata from the trusted registry, never request-supplied risk.

    This neither invokes tools nor creates confirmations. Invalid metadata/policy
    and evaluation errors deny; the gateway enforces the returned outcome.
    """
    try:
        if (
            type(metadata) is not ToolMetadata
            or type(metadata.name) is not str or not metadata.name
            or type(metadata.description) is not str or not metadata.description
            or type(metadata.risk_level) is not RiskLevel
            or type(policy) is not PermissionPolicy
            or type(policy.denied_tools) is not frozenset
        ):
            return PermissionDecision.DENY
        _check_schema(metadata.arguments_schema)
        if metadata.arguments_schema["type"] != "object":
            return PermissionDecision.DENY
        if metadata.name in policy.denied_tools:
            return PermissionDecision.DENY
        if metadata.risk_level in (RiskLevel.READ_ONLY, RiskLevel.LOW):
            return PermissionDecision.ALLOW
        return PermissionDecision.REQUIRE_CONFIRMATION
    except Exception:
        return PermissionDecision.DENY
