import asyncio
import os
from collections.abc import Coroutine
import typing
from datetime import datetime, time, timezone
from itertools import batched
from zoneinfo import ZoneInfo

from pydantic import RootModel

if typing.TYPE_CHECKING:
    from brewfather_mcp.types import (
        InventoryItem,
    )

AnyType = str | int | float
AnyDict = dict[str, str | int | float | None]
AnyDictList = list[AnyDict]


DEFAULT_TIMEZONE = "Europe/Rome"


def local_zone() -> ZoneInfo:
    """The zone for times shown to and read from the caller (BREWFATHER_MCP_TIMEZONE)."""
    return ZoneInfo(os.environ.get("BREWFATHER_MCP_TIMEZONE") or DEFAULT_TIMEZONE)


def to_local(value: int | float | datetime) -> datetime:
    """Convert an API time to the local zone.

    Numbers are Unix timestamps in milliseconds (13 digits) or seconds. A datetime
    without a zone is UTC, like every time the API sends.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        seconds = value / 1000 if abs(value) > 1e11 else value
        dt = datetime.fromtimestamp(seconds, timezone.utc)
    return dt.astimezone(local_zone())


def format_time(value: int | float | datetime, seconds: bool = True) -> str:
    """Format an API time in the local zone, with the zone name: 2026-07-19 21:18:49 CEST."""
    return to_local(value).strftime("%Y-%m-%d %H:%M:%S %Z" if seconds else "%Y-%m-%d %H:%M %Z")


def format_day(value: int | float | datetime) -> str:
    """Format an API time as the local day only: 2026-10-24."""
    return to_local(value).strftime("%Y-%m-%d")


def format_day_or_time(value: int | float | datetime) -> str:
    """Format a day field. Brewfather stores a picked day as local midnight, so a
    midnight value shows as a day only and any other value as a full time."""
    local = to_local(value)
    if local.time() == time(0):
        return format_day(local)
    return format_time(local)


def convert_timestamp_to_iso8601(value: int | None) -> str | None:
    """Convert a Unix timestamp of a day field to a day or a time in the local zone."""
    if not value:
        return None
    return format_day_or_time(value)


async def get_in_batches[TReturn: "InventoryItem", TIterable: "InventoryItem"](
    batch_size: int,
    async_fn: typing.Callable[[str], Coroutine[typing.Any, typing.Any, TReturn]],
    main_iterable: RootModel[list[TIterable]],
) -> list[TReturn]:
    """Auxiliary function to execute function in async batches."""
    detail_results: list[TReturn] = []
    detail_tasks = [async_fn(data.id) for data in main_iterable.root]
    batches = batched(detail_tasks, batch_size)
    for batch in batches:
        detail_results.extend(await asyncio.gather(*batch))

    return detail_results


def empty_if_null(s: AnyType | None) -> str:
    if not s:
        return ""
    else:
        return s
