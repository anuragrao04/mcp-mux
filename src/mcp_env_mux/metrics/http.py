from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.requests import Request
from starlette.responses import Response

from mcp_env_mux.metrics.registry import Metrics


def register_metrics_route(server, metrics: Metrics) -> None:
    @server.custom_route(metrics.config.path, methods=["GET"], include_in_schema=False)
    async def metrics_endpoint(request: Request) -> Response:  # noqa: ARG001
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)
