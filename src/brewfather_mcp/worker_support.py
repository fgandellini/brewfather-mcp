from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp


def configure_stateless(mcp: FastMCP) -> None:
    """Settings for serving MCP from a Worker: no sessions, plain JSON replies."""
    mcp.settings.stateless_http = True
    mcp.settings.json_response = True
    mcp.settings.streamable_http_path = "/mcp"
    # Newer SDKs answer 421 to any Host header but localhost. The Worker is public.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )


def fresh_asgi_app(mcp: FastMCP) -> ASGIApp:
    """Return a new ASGI app with its own session manager.

    The Workers ASGI adapter runs the app's lifespan on every request, and the SDK's
    session manager can run only once, so a reused app fails from the second request on.
    """
    mcp._session_manager = None
    return mcp.streamable_http_app()
