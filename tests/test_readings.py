from types import SimpleNamespace

import pytest

from brewfather_mcp.readings import downsample_readings, parse_day


def reading(time, temp=None, sg=None, target_temp=None):
    return SimpleNamespace(time=time, temp=temp, sg=sg, target_temp=target_temp)


def test_downsample_averages_each_bucket():
    readings = [reading(0, 18, 1.050), reading(10, 20, 1.040), reading(100, 22, 1.010)]
    buckets = downsample_readings(readings, points=2)
    assert [b.count for b in buckets] == [2, 1]
    assert buckets[0].temp == 19 and buckets[0].sg == pytest.approx(1.045)
    assert buckets[1].sg == 1.010


def test_downsample_drops_empty_buckets_and_missing_fields():
    readings = [reading(0, temp=18), reading(1000, sg=1.020)]
    buckets = downsample_readings(readings, points=10)
    assert len(buckets) == 2
    assert buckets[0].sg is None and buckets[1].temp is None


def test_downsample_filters_by_range():
    readings = [reading(0, 1), reading(50, 2), reading(100, 3)]
    buckets = downsample_readings(readings, points=5, since_ms=40, until_ms=60)
    assert len(buckets) == 1 and buckets[0].temp == 2


def test_downsample_empty_input():
    assert downsample_readings([], points=5) == []


def test_parse_day():
    assert parse_day(None) is None
    assert parse_day("2026-01-02", end_of_day=True) - parse_day("2026-01-02") == 86399000
    with pytest.raises(ValueError):
        parse_day("02/01/2026")
