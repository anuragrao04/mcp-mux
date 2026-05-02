"""CLI entrypoint for mcp-env-mux."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from mcp_env_mux.config import load_config
from mcp_env_mux.discovery import discover_all
from mcp_env_mux.logging import configure_json_logging
from mcp_env_mux.merge import validate_and_merge
from mcp_env_mux.metrics import create_metrics
from mcp_env_mux.metrics.startup import record_startup_state
from mcp_env_mux.proxy import create_proxy_server


async def _run(args: argparse.Namespace) -> int:
    configure_json_logging(logging.INFO)
    logger = logging.getLogger("mcp_env_mux")
    config = load_config(Path(args.config))
    metrics = create_metrics(config.metrics) if config.metrics is not None else None

    # Auth setup (only when auth is configured)
    private_key = None
    public_key = None
    if config.auth is not None:
        from mcp_env_mux.auth.keys import get_public_key, load_or_generate_key

        private_key = load_or_generate_key(config.auth.signing_key_file)
        public_key = get_public_key(private_key)

    logger.info("discovering_backends", extra={"environment_count": len(config.environments)})
    discovered = await discover_all(config, metrics=metrics)

    env_descriptions = {
        name: env.description for name, env in config.environments.items()
    }
    result = validate_and_merge(discovered, env_descriptions)
    logger.info(
        "merge_completed",
        extra={
            "tool_count": len(result.tools),
            "warning_count": len(result.warnings),
            "error_count": len(result.errors),
        },
    )
    record_startup_state(
        metrics,
        environment_count=len(config.environments),
        merged_tool_count=len(result.tools),
        merge_warning_count=len(result.warnings),
        merge_error_count=len(result.errors),
    )

    if args.test_schema:
        if result.errors:
            print("Errors:")
            for err in result.errors:
                print(f"  [{err.tool_name}] {err.message}")
        if result.warnings:
            print("Warnings:")
            for warn in result.warnings:
                print(f"  [{warn.tool_name}] {warn.message}")
        if not result.errors:
            print(f"OK: {len(result.tools)} tools merged successfully.")
        return 1 if result.errors else 0

    if result.errors:
        print("Fatal merge errors:", file=sys.stderr)
        for err in result.errors:
            print(f"  [{err.tool_name}] {err.message}", file=sys.stderr)
        return 1

    from mcp_env_mux.discovery import _make_client

    clients = {}
    try:
        for env_name, env_config in config.environments.items():
            client = _make_client(env_config.url, env_config.headers)
            await client.__aenter__()
            clients[env_name] = client

        server = create_proxy_server(
            result.tools,
            clients,
            auth_config=config.auth,
            private_key=private_key,
            public_key=public_key,
            metrics=metrics,
        )
        logger.info("starting_proxy", extra={"host": args.host, "port": args.port, "stateless_http": True})
        await server.run_http_async(
            host=args.host,
            port=args.port,
            stateless_http=True,
            show_banner=False,
            uvicorn_config={
                "log_config": None,
                "access_log": True,
            },
        )
    finally:
        for client in clients.values():
            await client.__aexit__(None, None, None)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP Environment Multiplexer")
    parser.add_argument("--config", required=True, help="Path to config JSON file")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument(
        "--test-schema",
        action="store_true",
        help="Discover and validate schemas, then exit",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(_run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
