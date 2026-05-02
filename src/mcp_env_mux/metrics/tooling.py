from __future__ import annotations

import time
from typing import Any

from mcp_env_mux.metrics.helpers import (
    classify_tool_error,
    principal_name_from_claims,
    principal_type_from_claims,
)
from mcp_env_mux.metrics.registry import Metrics


def get_request_principal() -> tuple[str, str]:
    try:
        from fastmcp.server.dependencies import get_access_token  # type: ignore[import]

        token = get_access_token()
    except Exception:
        token = None
    claims = token.claims if token else None
    return principal_name_from_claims(claims), principal_type_from_claims(claims)


async def instrument_tool_call(
    metrics: Metrics | None,
    *,
    tool: str,
    env: str,
    invoke,
):
    principal, principal_type = get_request_principal()
    start = time.perf_counter()

    if metrics is not None and metrics.enabled:
        metrics.tool_requests_total.labels(
            tool=tool,
            env=env,
            principal_type=principal_type,
        ).inc()
        metrics.tool_requests_in_flight.labels(tool=tool, env=env).inc()
        if metrics.config.user_level_metrics:
            metrics.user_tool_calls_total.labels(
                principal=principal,
                principal_type=principal_type,
            ).inc()

    try:
        result = await invoke()
    except Exception as exc:
        if metrics is not None and metrics.enabled:
            metrics.tool_request_errors_total.labels(
                tool=tool,
                env=env,
                principal_type=principal_type,
                error_type=classify_tool_error(exc),
            ).inc()
        raise
    else:
        if metrics is not None and metrics.enabled:
            metrics.tool_request_success_total.labels(
                tool=tool,
                env=env,
                principal_type=principal_type,
            ).inc()
        return result
    finally:
        if metrics is not None and metrics.enabled:
            metrics.tool_requests_in_flight.labels(tool=tool, env=env).dec()
            metrics.tool_request_duration_seconds.labels(
                tool=tool,
                env=env,
                principal_type=principal_type,
            ).observe(time.perf_counter() - start)
