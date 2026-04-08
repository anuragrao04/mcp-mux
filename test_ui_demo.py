#!/usr/bin/env python3
"""Demo: Test token minting UI without Azure AD.

Usage:
    uv run python test_ui_demo.py

This script:
1. Generates RSA keys
2. Creates a FastMCP server with auth enabled (no backends needed)
3. Creates a valid JWT token with 'admin' role
4. Starts the server and prints instructions

Then open your browser or use curl to access /ui/tokens.
"""

import asyncio
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from mcp_env_mux.auth.keys import get_public_key, load_or_generate_key
from mcp_env_mux.auth.tokens import create_user_token
from mcp_env_mux.config import AuthConfig, AzureConfig, RoleConfig
from mcp_env_mux.proxy import create_proxy_server

PORT = 8888


def build_server(private_key, public_key):
    """Build a FastMCP server with auth but no tools (demo)."""
    auth_config = AuthConfig(
        azure=AzureConfig(tenant_id="unused", client_id="unused", client_secret="unused"),
        signing_key_file="/tmp/demo.pem",
        roles={"admin": RoleConfig(allowed_envs={"*": ["*"]})},
        token_minting_roles=["admin"],
        token_max_expiry_days=180,
    )
    # No tools, no clients — demo just needs the auth routes + UI
    server = create_proxy_server(
        merged_tools=[],
        clients={},
        auth_config=auth_config,
        private_key=private_key,
        public_key=public_key,
    )
    return server


def run_server(private_key, public_key):
    """Run the FastMCP server via uvicorn in this thread."""
    server = build_server(private_key, public_key)
    # FastMCP exposes the ASGI app as .app
    app = server.http_app(path="/mcp")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


async def wait_for_server():
    """Poll until the server is accepting connections."""
    for _ in range(60):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://127.0.0.1:{PORT}/.well-known/oauth-protected-resource",
                    timeout=1,
                )
                if resp.status_code == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


async def main():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        key_file = tmp_path / "demo.pem"

        print("📝 Generating RSA keys...")
        private_key = load_or_generate_key(str(key_file))
        public_key = get_public_key(private_key)
        print("✓ Keys ready")

        print(f"\n🚀 Starting server on http://127.0.0.1:{PORT} ...")
        t = threading.Thread(target=run_server, args=(private_key, public_key), daemon=True)
        t.start()

        ready = await wait_for_server()
        if not ready:
            print("❌ Server failed to start — check for port conflicts")
            return

        print("✓ Server ready!")

        # Create a token
        token = create_user_token(private_key, "user@demo.com", ["admin"], expiry_seconds=3600)
        print(f"\n🔐 Bearer token (copy this):\n{token}\n")

        # Fetch the UI
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{PORT}/ui/tokens",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )

        if resp.status_code == 200:
            print("✓ /ui/tokens responded 200\n")
            print("=" * 70)
            print("HTML RESPONSE:")
            print("=" * 70)
            print(resp.text)
            print("=" * 70)
        else:
            print(f"❌ /ui/tokens returned {resp.status_code}:\n{resp.text}")

        print(f"""
📌 Server is running. Try it in your browser / curl:

  Open in browser (add the header via a browser extension like ModHeader):
    http://127.0.0.1:{PORT}/ui/tokens
    Header: Authorization: Bearer <token above>

  OR use curl to mint a bot token:
    curl -s -X POST http://127.0.0.1:{PORT}/ui/tokens \\
      -H 'Authorization: Bearer {token}' \\
      -H 'Content-Type: application/x-www-form-urlencoded' \\
      -d 'name=mybot&roles=admin&expiry_days=30'

  Discovery endpoints (no auth needed):
    curl http://127.0.0.1:{PORT}/.well-known/oauth-protected-resource
    curl http://127.0.0.1:{PORT}/.well-known/oauth-authorization-server

Press Ctrl+C to stop.
""")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n✓ Done.")


if __name__ == "__main__":
    asyncio.run(main())