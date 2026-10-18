"""Cloudflare Worker entry point. The logic lives in brewfather_mcp; this file only wires it up."""

import os
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint, asgi

# Imports stay at module level: Cloudflare snapshots the Worker's memory at deploy time,
# but only for what the entry module imports. Importing inside the handler costs ~2 s of
# CPU on every cold start.
from brewfather_mcp import server
from brewfather_mcp.auth import is_authorized
from brewfather_mcp.logconfig import install_noise_filter
from brewfather_mcp.worker_support import configure_stateless, fresh_asgi_app

configure_stateless(server.mcp)
install_noise_filter()

CREDENTIAL_NAMES = ("BREWFATHER_API_USER_ID", "BREWFATHER_API_KEY")


class Default(WorkerEntrypoint):
    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        # Secrets live on `env`, not in os.environ. The API client reads os.environ on
        # first use, so a missing secret becomes a clear error on the first tool call.
        for name in CREDENTIAL_NAMES:
            value = getattr(env, name, None)
            if value:
                os.environ[name] = str(value)

    async def fetch(self, request):
        # Fail closed: without a valid MCP_AUTH_TOKEN nobody gets in, on any path.
        token = getattr(self.env, "MCP_AUTH_TOKEN", None)
        if not is_authorized(request.headers.get("authorization"), token):
            return Response('{"error": "Unauthorized"}', status=401)

        if urlparse(request.url).path == "/mcp":
            return await asgi.fetch(fresh_asgi_app(server.mcp), request, self.env)
        return Response("Not found", status=404)
