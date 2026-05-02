"""Connect to backends and discover tools."""

from __future__ import annotations

from typing import Any

import time

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from mcp_env_mux.config import Config
from mcp_env_mux.metrics.helpers import classify_discovery_error
from mcp_env_mux.metrics.registry import Metrics


def _make_client(url: str, headers: dict[str, str]) -> Client:
    """Create a Client with optional headers via StreamableHttpTransport."""
    transport = StreamableHttpTransport(url=url, headers=headers or None)
    return Client(transport)


async def discover_all(
    config: Config,
    metrics: Metrics | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Connect to each backend and discover available tools."""
    discovered: dict[str, list[dict[str, Any]]] = {}

    for env_name, env_config in config.environments.items():
        client = _make_client(env_config.url, env_config.headers)
        start = time.perf_counter()
        try:
            async with client:
                tools = await client.list_tools()
                discovered[env_name] = [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "inputSchema": t.inputSchema,
                    }
                    for t in tools
                ]
        except Exception as exc:
            if metrics is not None and metrics.enabled:
                metrics.backend_discovery_errors_total.labels(
                    env=env_name,
                    error_type=classify_discovery_error(exc),
                ).inc()
                metrics.backend_discovery_duration_seconds.labels(env=env_name).observe(
                    time.perf_counter() - start
                )
            raise
        else:
            if metrics is not None and metrics.enabled:
                metrics.backend_discovery_success_total.labels(env=env_name).inc()
                metrics.backend_discovery_duration_seconds.labels(env=env_name).observe(
                    time.perf_counter() - start
                )

    return discovered
