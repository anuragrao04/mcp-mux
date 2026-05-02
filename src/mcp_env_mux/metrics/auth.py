from __future__ import annotations

from mcp_env_mux.metrics.registry import Metrics


def record_auth(metrics: Metrics | None, *, token_type: str, result: str, reason: str) -> None:
    if metrics is None or not metrics.enabled:
        return
    metrics.auth_requests_total.labels(token_type=token_type, result=result, reason=reason).inc()


def record_rbac_decision(
    metrics: Metrics | None,
    *,
    tool: str,
    env: str,
    decision: str,
    principal_type: str,
) -> None:
    if metrics is None or not metrics.enabled:
        return
    metrics.rbac_decisions_total.labels(
        tool=tool,
        env=env,
        decision=decision,
        principal_type=principal_type,
    ).inc()
