from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from mcp_env_mux.metrics.registry import Metrics


def record_ui_login(metrics: Metrics | None, result: str) -> None:
    if metrics is None or not metrics.enabled:
        return
    metrics.ui_logins_total.labels(result=result).inc()


def record_ui_token_mint(metrics: Metrics | None, result: str) -> None:
    if metrics is None or not metrics.enabled:
        return
    metrics.ui_token_mint_total.labels(result=result).inc()


def instrument_ui_route(metrics: Metrics | None, route: str):
    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(fn)
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            result = "success"
            try:
                return await fn(*args, **kwargs)
            except Exception:
                result = "error"
                raise
            finally:
                if metrics is not None and metrics.enabled:
                    metrics.ui_requests_total.labels(route=route, result=result).inc()
                    metrics.ui_request_duration_seconds.labels(route=route).observe(
                        time.perf_counter() - start
                    )

        return wrapped

    return decorator
