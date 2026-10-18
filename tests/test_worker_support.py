import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from brewfather_mcp.worker_support import configure_stateless, fresh_asgi_app

WORKER_URL = "https://brewfather-mcp.example.workers.dev"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


@pytest.fixture
def mcp_server() -> FastMCP:
    return FastMCP("test")


def test_configure_stateless_sets_the_stateless_json_settings(mcp_server):
    configure_stateless(mcp_server)
    assert mcp_server.settings.stateless_http is True
    assert mcp_server.settings.json_response is True
    assert mcp_server.settings.streamable_http_path == "/mcp"


def test_configured_app_accepts_a_workers_dev_host(mcp_server):
    # Newer SDKs turn on DNS-rebinding protection for localhost servers and answer 421
    # to any other Host header. The Worker is public and protected by its bearer token.
    configure_stateless(mcp_server)
    with TestClient(fresh_asgi_app(mcp_server), base_url=WORKER_URL) as client:
        response = client.post("/mcp", json=INITIALIZE, headers=HEADERS)
    assert response.status_code == 200


def test_fresh_asgi_app_serves_two_sequential_requests(mcp_server):
    configure_stateless(mcp_server)
    for _ in range(2):
        # The `with` block runs ASGI lifespan, as the Workers adapter does on every request.
        with TestClient(fresh_asgi_app(mcp_server), base_url=WORKER_URL) as client:
            response = client.post("/mcp", json=INITIALIZE, headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "test"


def test_reusing_one_app_fails_on_the_second_lifespan(mcp_server):
    # Pins why fresh_asgi_app exists. If a future SDK allows this, delete the workaround.
    configure_stateless(mcp_server)
    app = mcp_server.streamable_http_app()
    with TestClient(app, base_url=WORKER_URL):
        pass
    with pytest.raises(RuntimeError, match="only be called once"):
        with TestClient(app, base_url=WORKER_URL):
            pass


def test_apps_built_back_to_back_each_serve_their_own_request(mcp_server):
    # One Worker isolate serves overlapping requests. The adapter starts an app's lifespan
    # in a background task, so a second request can build its app before the first app's
    # lifespan has started. Each app must still run its own session manager.
    configure_stateless(mcp_server)
    first = fresh_asgi_app(mcp_server)
    second = fresh_asgi_app(mcp_server)
    for app in (first, second):
        with TestClient(app, base_url=WORKER_URL) as client:
            response = client.post("/mcp", json=INITIALIZE, headers=HEADERS)
        assert response.status_code == 200
