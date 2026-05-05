from __future__ import annotations

import httpx
import pytest

from conftest import start_backend, start_proxy, write_config


@pytest.mark.asyncio
async def test_healthz_and_readyz_return_success_after_startup(tmp_path):
    backend = await start_backend(
        "health-be",
        {
            "echo": {
                "description": "Echo",
                "params": {"msg": {"type": str, "required": True}},
                "handler": lambda kw: kw["msg"],
            }
        },
    )
    config_path = write_config(
        {"prod": {"description": "Prod", "url": backend.url}},
        tmp_path,
    )
    proxy = start_proxy(config_path)
    try:
        base = f"http://127.0.0.1:{proxy.port}"
        async with httpx.AsyncClient() as client:
            health = await client.get(f"{base}/healthz", timeout=10)
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}

            ready = await client.get(f"{base}/readyz", timeout=10)
            assert ready.status_code == 200
            body = ready.json()
            assert body["status"] == "ready"
            assert body["environment_count"] == 1
            assert body["merged_tool_count"] == 1
            assert body["redis"] == {
                "enabled": False,
                "verified": False,
                "host": None,
                "port": None,
            }
    finally:
        proxy.stop()
