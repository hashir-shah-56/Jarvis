"""Trusted, deny-only policy configuration; no settings can downgrade risk."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionPolicy:
    """Deny named tools in addition to the mandatory risk-based policy.

    Construct only in trusted setup. No request or environment flag can turn
    MEDIUM/HIGH into automatic authorization.
    """

    denied_tools: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if type(self.denied_tools) is not frozenset or any(
            type(name) is not str or not name for name in self.denied_tools
        ):
            raise ValueError("INVALID_PERMISSION_POLICY")


DEFAULT_POLICY = PermissionPolicy()
