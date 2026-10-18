import logging
import subprocess
import sys
import os

import anyio
import pytest

from brewfather_mcp.logconfig import (
    DropClosedResourceNoise,
    configure_file_logging,
    install_noise_filter,
)

NOISY_LOGGER = "mcp.server.streamable_http"


def make_record(name: str, exc: BaseException | None) -> logging.LogRecord:
    exc_info = (type(exc), exc, None) if exc is not None else None
    return logging.LogRecord(name, logging.ERROR, __file__, 1, "Error in message router", None, exc_info)


class TestDropClosedResourceNoise:
    def test_filter_drops_closed_resource_error_from_streamable_http_logger(self):
        record = make_record(NOISY_LOGGER, anyio.ClosedResourceError())
        assert DropClosedResourceNoise().filter(record) is False

    def test_filter_keeps_other_exceptions_from_that_logger(self):
        record = make_record(NOISY_LOGGER, RuntimeError("real problem"))
        assert DropClosedResourceNoise().filter(record) is True

    def test_filter_keeps_closed_resource_error_from_other_loggers(self):
        record = make_record("brewfather_mcp.api", anyio.ClosedResourceError())
        assert DropClosedResourceNoise().filter(record) is True

    def test_filter_keeps_records_without_exception_info(self):
        record = make_record(NOISY_LOGGER, None)
        assert DropClosedResourceNoise().filter(record) is True

    def test_install_noise_filter_is_idempotent(self):
        logger = logging.getLogger(NOISY_LOGGER)
        before = list(logger.filters)
        try:
            install_noise_filter()
            install_noise_filter()
            added = [f for f in logger.filters if isinstance(f, DropClosedResourceNoise)]
            assert len(added) == 1
        finally:
            logger.filters = before


class TestConfigureFileLogging:
    @pytest.fixture
    def clean_root(self):
        root = logging.getLogger()
        saved_handlers, saved_level = list(root.handlers), root.level
        root.handlers = []
        yield root
        for handler in root.handlers:
            handler.close()
        root.handlers, root.level = saved_handlers, saved_level

    def test_configure_file_logging_twice_adds_one_file_handler(self, clean_root, tmp_path):
        path = str(tmp_path / "app.log")
        configure_file_logging(path)
        configure_file_logging(path)
        assert len(clean_root.handlers) == 1
        assert isinstance(clean_root.handlers[0], logging.FileHandler)

    def test_configure_file_logging_replaces_handlers_installed_earlier(self, clean_root, tmp_path):
        # FastMCP() installs a RichHandler on the root logger when server.py is imported.
        clean_root.addHandler(logging.StreamHandler(sys.stdout))
        path = str(tmp_path / "app.log")
        configure_file_logging(path)
        assert [type(h) for h in clean_root.handlers] == [logging.FileHandler]
        logging.getLogger("brewfather_mcp.test").info("hello")
        clean_root.handlers[0].flush()
        assert "hello" in (tmp_path / "app.log").read_text()


def test_importing_server_does_not_add_a_file_handler():
    env = {**os.environ, "PYTHONPATH": "src", "BREWFATHER_API_USER_ID": "", "BREWFATHER_API_KEY": ""}
    code = (
        "import logging, brewfather_mcp.server;"
        "print(any(isinstance(h, logging.FileHandler) for h in logging.getLogger().handlers))"
    )
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
