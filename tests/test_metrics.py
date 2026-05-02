from __future__ import annotations

import json

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from conftest import start_backend, start_proxy


@pytest.mark.asyncio
async def test_environment_metrics_exposed_for_success_and_error(tmp_path):
    backend = await start_backend(
        "metrics-be",
        {
            "echo": {
                "description": "Echo",
                "params": {"msg": {"type": str, "required": True}},
                "handler": lambda kw: kw["msg"],
            }
        },
    )
    config = {
        "environments": {
            "prod": {"description": "Prod", "url": backend.url}
        },
        "metrics": {
            "enabled": True,
            "path": "/metrics",
            "user_level_metrics": False,
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    proxy = start_proxy(config_path)
    try:
        async with Client(proxy.url) as client:
            result = await client.call_tool("echo", {"env": "prod", "msg": "hello"})
            assert result.content[0].text == "hello"
            with pytest.raises(ToolError):
                await client.call_tool("echo", {"env": "nope", "msg": "bad"})

        async with httpx.AsyncClient() as http_client:
            metrics = await http_client.get(f"http://127.0.0.1:{proxy.port}/metrics", timeout=10)
            assert metrics.status_code == 200
            body = metrics.text
            assert 'mcp_env_mux_environment_requests_total{env="prod"}' in body
            assert 'mcp_env_mux_environment_request_success_total{env="prod"}' in body
            assert 'mcp_env_mux_environment_request_errors_total{env="prod",error_type="rbac_denied"}' not in body
            assert 'mcp_env_mux_environment_request_errors_total{env="prod",error_type="invalid_env"}' not in body
            assert 'mcp_env_mux_tool_response_size_bytes_bucket' in body
            assert 'mcp_env_mux_environment_response_size_bytes_bucket' in body
    finally:
        proxy.stop()
