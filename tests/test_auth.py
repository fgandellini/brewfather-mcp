import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from brewfather_mcp.auth import is_authorized
from http_runner import BearerAuthMiddleware


def test_is_authorized_accepts_exact_bearer():
    assert is_authorized("Bearer s3cret", "s3cret") is True


@pytest.mark.parametrize(
    "authorization, token",
    [
        (None, "s3cret"),
        ("", "s3cret"),
        ("Bearer wrong", "s3cret"),
        ("bearer s3cret", "s3cret"),
        ("Basic s3cret", "s3cret"),
        ("Bearer s3cret ", "s3cret"),
        ("Bearer s3cret", ""),
        ("Bearer s3cret", None),
        ("Bearer ", ""),
        ("", ""),
        (None, None),
        ("Bearer é", "s3cret"),
        ("Bearer \ud800", "s3cret"),
    ],
)
def test_is_authorized_rejects(authorization, token):
    assert is_authorized(authorization, token) is False


def test_middleware_returns_401_without_token_and_passes_with_it():
    async def hello(request):
        return PlainTextResponse("hello")

    app = BearerAuthMiddleware(Starlette(routes=[Route("/", hello)]), "s3cret")
    client = TestClient(app)

    denied = client.get("/")
    assert denied.status_code == 401
    assert denied.json() == {"error": "Unauthorized"}

    allowed = client.get("/", headers={"Authorization": "Bearer s3cret"})
    assert allowed.status_code == 200
    assert allowed.text == "hello"
