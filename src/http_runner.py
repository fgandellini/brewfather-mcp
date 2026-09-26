"""HTTP/SSE runner for the Brewfather MCP server."""

import asyncio
import hmac
import logging
from typing import Optional

import click
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from brewfather_mcp.server import mcp

logger = logging.getLogger(__name__)


class BearerAuthMiddleware:
    """Rejects any HTTP request missing a matching `Authorization: Bearer <token>` header."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.expected = f"Bearer {token}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        provided = headers.get(b"authorization", b"").decode("latin-1")
        if not hmac.compare_digest(provided, self.expected):
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, help="Port to listen on")
@click.option("--log-level", default="INFO", help="Logging level")
@click.option(
    "--allowed-host",
    "allowed_hosts",
    multiple=True,
    envvar="ALLOWED_HOSTS",
    default=["localhost:*", "127.0.0.1:*"],
    help="Allowed Host header value (repeatable). Also read from ALLOWED_HOSTS "
    "as a comma-separated list.",
)
@click.option(
    "--auth-token",
    envvar="MCP_AUTH_TOKEN",
    default=None,
    help="If set, requires this token in an 'Authorization: Bearer <token>' header "
    "on every request. Also read from MCP_AUTH_TOKEN.",
)
def main(
    host: str,
    port: int,
    log_level: str,
    allowed_hosts: tuple[str, ...],
    auth_token: Optional[str],
) -> None:
    """Run the Brewfather MCP server over HTTP (Streamable HTTP transport)."""

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info(f"Starting Brewfather MCP HTTP server on {host}:{port}")

    # Configure server settings
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.settings.log_level = log_level.upper() # type: ignore

    # ALLOWED_HOSTS may arrive as a single comma-separated env value
    resolved_hosts = [h for entry in allowed_hosts for h in entry.split(",") if h]
    resolved_origins = [
        f"{scheme}://{h}" for h in resolved_hosts for scheme in ("http", "https")
    ]
    mcp.settings.transport_security.allowed_hosts = resolved_hosts
    mcp.settings.transport_security.allowed_origins = resolved_origins
    logger.info(f"Allowed hosts: {resolved_hosts}")
    logger.info(f"Allowed origins: {resolved_origins}")

    app = mcp.streamable_http_app()
    if auth_token:
        app = BearerAuthMiddleware(app, auth_token)
        logger.info("Bearer token authentication enabled")
    else:
        logger.warning("MCP_AUTH_TOKEN not set - server is running without authentication")

    # Run the server with Streamable HTTP transport
    import uvicorn

    try:
        uvicorn.run(app, host=host, port=port, log_level=log_level.lower())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


def run_http_server(
    host: str = "0.0.0.0", 
    port: int = 8000, 
    log_level: str = "INFO"
) -> None:
    """Programmatic way to run the HTTP server."""
    main(host, port, log_level)


if __name__ == "__main__":
    main()