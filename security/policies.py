"""Future security policy requirements; these are not executable policies.

- Never permit unrestricted arbitrary command execution.
- Use approved structured tools with least-privilege access.
- Require confirmation for destructive or sensitive operations.
- Maintain sanitized action/authorization audit logs (distinct from app logs).
- Fail closed when authorization is absent, ambiguous, or uncertain.
"""
