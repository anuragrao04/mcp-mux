"""
Shared fixtures for mcp-env-mux E2E tests.

Provides helpers to spin up mock MCP backend servers using FastMCP,
write proxy config files, and launch the mcp-env-mux proxy process.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import TextIO
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastmcp import Client, FastMCP


# ---------------------------------------------------------------------------
# Port allocation
# ---------------------------------------------------------------------------

def find_free_port() -> int:
    """Find and return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Mock backend server helpers
# ---------------------------------------------------------------------------

@dataclass
class MockBackend:
    """A running mock MCP backend server."""

    name: str
    server: FastMCP
    port: int
    url: str
    _task: asyncio.Task | None = field(default=None, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)


def create_backend_server(name: str, tools: dict[str, dict[str, Any]]) -> FastMCP:
    """
    Create a FastMCP server with the given tools.

    Each entry in `tools` maps a tool name to its definition:
        {
            "description": "...",
            "params": {"param_name": {"type": <python_type>, "required": bool, "default": <value>}},
            "handler": callable(kwargs) -> Any,
        }
    """
    server = FastMCP(name)

    for tool_name, tool_def in tools.items():
        description = tool_def.get("description", f"Tool {tool_name}")
        handler = tool_def.get("handler")
        params = tool_def.get("params", {})

        # Build the function dynamically so FastMCP discovers its schema
        _register_tool(server, tool_name, description, params, handler)

    return server


def _register_tool(
    server: FastMCP,
    name: str,
    description: str,
    params: dict,
    handler: callable | None,
):
    """Register a tool on a FastMCP server with the given parameter schema."""
    # We use exec to build a function with the right signature so that
    # FastMCP's schema introspection picks up the parameter names/types.
    param_parts = []
    for pname, pdef in params.items():
        ptype = pdef["type"].__name__
        if not pdef.get("required", True):
            default = pdef.get("default", None)
            param_parts.append(f"{pname}: {ptype} = {default!r}")
        else:
            param_parts.append(f"{pname}: {ptype}")

    sig = ", ".join(param_parts)
    fn_name = f"_tool_{name}"

    # The handler receives all kwargs and returns whatever it wants
    func_code = f"""
def {fn_name}({sig}) -> str:
    kwargs = {{{', '.join(f'"{p}": {p}' for p in params)}}}
    return _handler(kwargs)
"""
    local_ns: dict[str, Any] = {"_handler": handler or (lambda kw: json.dumps(kw))}
    exec(func_code, local_ns, local_ns)  # noqa: S102
    fn = local_ns[fn_name]
    fn.__doc__ = description
    fn.__name__ = name
    fn.__qualname__ = name

    server.tool(name=name)(fn)


async def start_backend(
    name: str,
    tools: dict[str, dict[str, Any]],
    port: int | None = None,
) -> MockBackend:
    """Create and start a mock MCP backend, returning a MockBackend handle."""
    port = port or find_free_port()
    server = create_backend_server(name, tools)
    url = f"http://127.0.0.1:{port}/mcp"

    thread = threading.Thread(
        target=server.run,
        kwargs={"transport": "http", "host": "127.0.0.1", "port": port},
        daemon=True,
    )
    thread.start()
    # Give the server a moment to bind
    await asyncio.sleep(0.5)

    return MockBackend(name=name, server=server, port=port, url=url, _thread=thread)


# ---------------------------------------------------------------------------
# Config file helpers
# ---------------------------------------------------------------------------

def write_config(
    environments: dict[str, dict[str, Any]],
    tmpdir: Path | str,
) -> Path:
    """Write a proxy config JSON file and return its path."""
    config = {"environments": environments}
    path = Path(tmpdir) / "config.json"
    path.write_text(json.dumps(config, indent=2))
    return path


# ---------------------------------------------------------------------------
# Proxy process helpers
# ---------------------------------------------------------------------------

@dataclass
class ProxyProcess:
    """A running mcp-env-mux proxy."""

    process: subprocess.Popen
    port: int
    url: str
    config_path: Path
    stdout_path: Path | None = None
    stderr_path: Path | None = None

    def stop(self):
        self.process.send_signal(signal.SIGTERM)
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    @property
    def returncode(self) -> int | None:
        return self.process.returncode


def start_proxy(
    config_path: Path,
    port: int | None = None,
    extra_args: list[str] | None = None,
    wait_for_ready: bool = True,
    env_vars: dict[str, str] | None = None,
    capture_logs: bool = False,
) -> ProxyProcess:
    """
    Start the mcp-env-mux proxy as a subprocess.

    Returns a ProxyProcess handle. The caller is responsible for calling .stop().
    """
    port = port or find_free_port()
    url = f"http://127.0.0.1:{port}/mcp"

    cmd = [
        sys.executable, "-m", "mcp_env_mux.cli",
        "--config", str(config_path),
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
    if extra_args:
        cmd.extend(extra_args)

    env = {**os.environ, **(env_vars or {})}

    stdout_target: int | TextIO = subprocess.PIPE
    stderr_target: int | TextIO = subprocess.PIPE
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    stdout_handle: TextIO | None = None
    stderr_handle: TextIO | None = None
    if capture_logs:
        log_dir = Path(tempfile.mkdtemp(prefix="mcp-env-mux-logs-"))
        stdout_path = log_dir / "stdout.log"
        stderr_path = log_dir / "stderr.log"
        stdout_handle = stdout_path.open("w")
        stderr_handle = stderr_path.open("w")
        stdout_target = stdout_handle
        stderr_target = stderr_handle

    proc = subprocess.Popen(
        cmd,
        stdout=stdout_target,
        stderr=stderr_target,
        env=env,
        cwd=str(Path(__file__).resolve().parent.parent),
    )

    if stdout_handle is not None:
        stdout_handle.close()
    if stderr_handle is not None:
        stderr_handle.close()

    if wait_for_ready:
        _wait_for_port(port, timeout=10, process=proc)

    return ProxyProcess(
        process=proc,
        port=port,
        url=url,
        config_path=config_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def run_test_schema(
    config_path: Path,
    env_vars: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """
    Run mcp-env-mux in --test-schema mode and return the completed process.
    """
    cmd = [
        sys.executable, "-m", "mcp_env_mux.cli",
        "--config", str(config_path),
        "--test-schema",
    ]

    env = {**os.environ, **(env_vars or {})}

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=str(Path(__file__).resolve().parent.parent),
    )


def _wait_for_port(port: int, timeout: float = 10, process: subprocess.Popen | None = None):
    """Block until a TCP port is accepting connections or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # Check if process died
        if process and process.poll() is not None:
            stdout = process.stdout.read().decode() if process.stdout else ""
            stderr = process.stderr.read().decode() if process.stderr else ""
            raise RuntimeError(
                f"Proxy exited with code {process.returncode} before becoming ready.\n"
                f"stdout: {stdout}\nstderr: {stderr}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"Port {port} not ready after {timeout}s")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_path_factory_unique(tmp_path):
    """Provide a unique temp directory for each test."""
    return tmp_path


@pytest.fixture
def free_port():
    """Return a free port."""
    return find_free_port
