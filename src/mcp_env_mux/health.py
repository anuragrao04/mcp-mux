from __future__ import annotations

from dataclasses import dataclass

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


@dataclass
class ReadinessState:
    ready: bool = False
    reason: str = "startup_incomplete"
    environment_count: int = 0
    merged_tool_count: int = 0
    redis_enabled: bool = False
    redis_verified: bool = False
    redis_host: str | None = None
    redis_port: int | None = None


def register_health_routes(server: FastMCP, readiness: ReadinessState) -> None:
    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(request: Request) -> Response:  # noqa: ARG001
        return JSONResponse({"status": "ok"})

    @server.custom_route("/readyz", methods=["GET"], include_in_schema=False)
    async def readyz(request: Request) -> Response:  # noqa: ARG001
        if readiness.ready:
            return JSONResponse(
                {
                    "status": "ready",
                    "environment_count": readiness.environment_count,
                    "merged_tool_count": readiness.merged_tool_count,
                    "redis": {
                        "enabled": readiness.redis_enabled,
                        "verified": readiness.redis_verified,
                        "host": readiness.redis_host,
                        "port": readiness.redis_port,
                    },
                }
            )
        return JSONResponse(
            {
                "status": "not_ready",
                "reason": readiness.reason,
                "redis": {
                    "enabled": readiness.redis_enabled,
                    "verified": readiness.redis_verified,
                    "host": readiness.redis_host,
                    "port": readiness.redis_port,
                },
            },
            status_code=503,
        )
