import logging

import pytest
from click.testing import CliRunner

import http_runner
from brewfather_mcp.server import mcp


@pytest.fixture
def isolated_state(monkeypatch):
    """main() changes the root logger and the shared FastMCP settings; restore both."""
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    for name in ("host", "port", "log_level", "transport_security"):
        monkeypatch.setattr(mcp.settings, name, getattr(mcp.settings, name))
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    yield
    root.handlers, root.level = saved_handlers, saved_level


def test_log_level_option_sets_the_root_logger_level(isolated_state):
    # FastMCP installs a root handler at INFO when server.py is imported, so a plain
    # basicConfig call here would do nothing and --log-level would have no effect.
    result = CliRunner().invoke(http_runner.main, ["--log-level", "DEBUG"])
    assert result.exit_code == 0, result.output
    assert logging.getLogger().level == logging.DEBUG
