"""Stage 6 boundary: enforce the execution pipeline outside the LLM.

Future flow: plan -> registered tool -> permission decision -> security
validation -> execution -> sanitized result. Missing/uncertain authorization
must fail closed. Confirmations must apply to the exact approved action.
There is no dispatcher or execution path in Stage 1.
"""
