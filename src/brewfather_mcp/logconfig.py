import logging
import sys

import anyio

NOISY_LOGGER = "mcp.server.streamable_http"


def configure_file_logging(path: str) -> None:
    """Send all logs to a file. Stdio servers must not log to stdout: it carries the protocol.

    force=True because FastMCP installs its own root handler when the server module is
    imported, and a plain basicConfig would then do nothing.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        filename=path,
        filemode="a",
        force=True,
    )


def configure_stdout_logging() -> None:
    """Send all logs to stdout. For the Worker, where stdout is for logs.

    Cloudflare labels everything a Worker writes to stderr as an error, so stderr would
    show every INFO line as one. force=True for the same reason as in configure_file_logging.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
        force=True,
    )


class DropClosedResourceNoise(logging.Filter):
    """Hide the harmless "Error in message router" record logged when a request ends.

    The Worker gives every request its own session manager. Shutting it down cancels a
    task that was still reading, and the SDK logs that as an error.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != NOISY_LOGGER or not record.exc_info:
            return True
        return not isinstance(record.exc_info[1], anyio.ClosedResourceError)


def install_noise_filter() -> None:
    logger = logging.getLogger(NOISY_LOGGER)
    if not any(isinstance(f, DropClosedResourceNoise) for f in logger.filters):
        logger.addFilter(DropClosedResourceNoise())
