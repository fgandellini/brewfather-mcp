"""Downsampling of batch readings into a fixed number of time buckets."""

from dataclasses import dataclass
from datetime import datetime
from statistics import mean

from brewfather_mcp.utils import local_zone


@dataclass
class ReadingBucket:
    start_ms: int
    count: int
    temp: float | None
    target_temp: float | None
    sg: float | None


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def downsample_readings(
    readings, points: int, since_ms: int | None = None, until_ms: int | None = None
) -> list[ReadingBucket]:
    """Split the time span of the readings into equal buckets and average each one.

    Empty buckets are dropped. Readings outside since_ms/until_ms are ignored.
    """
    selected = [
        r
        for r in readings
        if (since_ms is None or r.time >= since_ms) and (until_ms is None or r.time <= until_ms)
    ]
    if not selected or points < 1:
        return []
    first = min(r.time for r in selected)
    last = max(r.time for r in selected)
    width = max((last - first + 1) / points, 1)

    groups: dict[int, list] = {}
    for reading in selected:
        index = min(int((reading.time - first) / width), points - 1)
        groups.setdefault(index, []).append(reading)

    return [
        ReadingBucket(
            start_ms=int(first + index * width),
            count=len(group),
            temp=_avg([r.temp for r in group if r.temp is not None]),
            target_temp=_avg([r.target_temp for r in group if r.target_temp is not None]),
            sg=_avg([r.sg for r in group if r.sg is not None]),
        )
        for index, group in sorted(groups.items())
    ]


def parse_day(value: str | None, end_of_day: bool = False) -> int | None:
    """Parse a YYYY-MM-DD day in the local zone into milliseconds.

    Raises ValueError for any other format.
    """
    if not value:
        return None
    day = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=local_zone())
    if end_of_day:
        day = day.replace(hour=23, minute=59, second=59)
    return int(day.timestamp() * 1000)
