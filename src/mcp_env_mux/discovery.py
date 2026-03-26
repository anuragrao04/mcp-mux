"""Connect to backends and discover tools."""

from __future__ import annotations

from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from mcp_env_mux.config import Config


def _make_client(url: str, headers: dict[str, str]) -> Client:
    """Create a Client with optional headers via StreamableHttpTransport."""
    transport = StreamableHttpTransport(url=url, headers=headers or None)
    return Client(transport)


async def discover_all(config: Config) -> dict[str, list[dict[str, Any]]]:
    """Connect to each backend and discover available tools."""
    discovered: dict[str, list[dict[str, Any]]] = {}

    for env_name, env_config in config.environments.items():
        client = _make_client(env_config.url, env_config.headers)
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

    return discovered
