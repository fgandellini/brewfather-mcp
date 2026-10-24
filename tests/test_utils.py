import asyncio
from datetime import datetime, timezone
from typing import Any, Coroutine
from unittest.mock import AsyncMock

import pytest
from brewfather_mcp.utils import (
    convert_timestamp_to_iso8601,
    format_day,
    format_day_or_time,
    format_time,
    get_in_batches,
)
from pydantic import BaseModel, RootModel


# Mock the models that would be used
class InventoryItem(BaseModel):
    id: str
    name: str = ""


@pytest.mark.asyncio
async def test_get_in_batches_empty_list():
    """Test function with an empty list."""
    mock_async_fn = AsyncMock()
    empty_list = RootModel[list[InventoryItem]](root=[])

    result = await get_in_batches(10, mock_async_fn, empty_list)

    assert result == []
    mock_async_fn.assert_not_called()


@pytest.mark.asyncio
async def test_get_in_batches_single_batch():
    """Test function with items that fit within a single batch."""
    batch_size = 5
    items = [InventoryItem(id=f"id_{i}") for i in range(3)]
    main_iterable = RootModel[list[InventoryItem]](root=items)

    async def mock_getter(item_id: str) -> InventoryItem:
        return InventoryItem(id=item_id, name=f"Item {item_id}")

    result = await get_in_batches(batch_size, mock_getter, main_iterable)

    assert len(result) == 3
    assert all(isinstance(item, InventoryItem) for item in result)
    assert [item.id for item in result] == ["id_0", "id_1", "id_2"]
    assert [item.name for item in result] == ["Item id_0", "Item id_1", "Item id_2"]


@pytest.mark.asyncio
async def test_get_in_batches_multiple_batches():
    """Test function with items that require multiple batches."""
    batch_size = 2
    items = [InventoryItem(id=f"id_{i}") for i in range(5)]
    main_iterable = RootModel[list[InventoryItem]](root=items)

    call_order = []

    async def mock_getter(item_id: str) -> InventoryItem:
        # Track the order of calls
        call_order.append(item_id)
        # Simulate different processing times
        await asyncio.sleep(0.01 if item_id == "id_2" else 0.001)
        return InventoryItem(id=item_id, name=f"Item {item_id}")

    # Act
    result = await get_in_batches(batch_size, mock_getter, main_iterable)

    # Assert
    assert len(result) == 5
    # Verify all items are processed
    assert sorted([item.id for item in result]) == [
        "id_0",
        "id_1",
        "id_2",
        "id_3",
        "id_4",
    ]
    # Verify items are processed in batches
    assert len(call_order) == 5


@pytest.mark.asyncio
async def test_get_in_batches_exact_batch_size():
    """Test function with items that exactly match the batch size."""
    batch_size = 3
    items = [InventoryItem(id=f"id_{i}") for i in range(6)]
    main_iterable = RootModel[list[InventoryItem]](root=items)

    processed_batches = []
    currently_processing = set()

    async def mock_getter(item_id: str) -> InventoryItem:
        # Add to currently processing set
        currently_processing.add(item_id)
        # Small delay to ensure concurrent execution within a batch
        await asyncio.sleep(0.05)
        # Record the batch before removing from processing
        if len(currently_processing) == batch_size:
            processed_batches.append(set(currently_processing))
        currently_processing.remove(item_id)
        return InventoryItem(id=item_id, name=f"Processed {item_id}")

    result = await get_in_batches(batch_size, mock_getter, main_iterable)

    assert len(result) == 6
    assert sorted([item.id for item in result]) == [
        "id_0",
        "id_1",
        "id_2",
        "id_3",
        "id_4",
        "id_5",
    ]
    # We should have had 2 full batches with batch_size items
    assert len(processed_batches) == 2


@pytest.mark.asyncio
async def test_get_in_batches_error_handling():
    """Test how the function handles errors in the async function."""
    batch_size = 3
    items = [InventoryItem(id=f"id_{i}") for i in range(5)]
    main_iterable = RootModel[list[InventoryItem]](root=items)

    async def mock_getter(item_id: str) -> InventoryItem:
        if item_id == "id_2":
            raise ValueError("Error processing id_2")
        return InventoryItem(id=item_id, name=f"Item {item_id}")

    with pytest.raises(ValueError, match="Error processing id_2"):
        await get_in_batches(batch_size, mock_getter, main_iterable)


@pytest.mark.asyncio
async def test_get_in_batches_preserves_order():
    """Test that the function preserves the order of results based on input order."""
    batch_size = 2
    items = [
        InventoryItem(id="id_C"),
        InventoryItem(id="id_A"),
        InventoryItem(id="id_D"),
        InventoryItem(id="id_B"),
    ]
    main_iterable = RootModel[list[InventoryItem]](root=items)

    async def mock_getter(item_id: str) -> InventoryItem:
        # Simulate varying processing times
        delay = 0.02 if item_id in ["id_A", "id_D"] else 0.01
        await asyncio.sleep(delay)
        return InventoryItem(id=item_id, name=f"Item {item_id}")

    result = await get_in_batches(batch_size, mock_getter, main_iterable)

    # The order of results should match the order of tasks, which is based on the input order
    assert [item.id for item in result] == ["id_C", "id_A", "id_D", "id_B"]


# Values from real batches. Brewfather stores a picked day as midnight in the user's zone.
ROME_MIDNIGHT_CEST_MS = 1792792800000  # 2026-10-24 00:00 Rome, 2026-10-23 22:00 UTC
ROME_MIDNIGHT_CET_MS = 1774047600000  # 2026-03-21 00:00 Rome, 2026-03-20 23:00 UTC
STATUS_CHANGE_MS = 1784488729153  # 2026-07-19 21:18:49 Rome


@pytest.fixture
def rome(monkeypatch):
    monkeypatch.delenv("BREWFATHER_MCP_TIMEZONE", raising=False)


def test_format_time_uses_rome_by_default(rome):
    assert format_time(STATUS_CHANGE_MS) == "2026-07-19 21:18:49 CEST"


def test_format_time_shows_winter_offset(rome):
    assert format_time(ROME_MIDNIGHT_CET_MS) == "2026-03-21 00:00:00 CET"


def test_format_time_accepts_seconds_and_datetimes(rome):
    aware = datetime(2026, 7, 19, 19, 18, 49, tzinfo=timezone.utc)
    assert format_time(1784488729) == "2026-07-19 21:18:49 CEST"
    assert format_time(aware) == "2026-07-19 21:18:49 CEST"
    # A datetime with no zone is UTC, the zone of every API value.
    assert format_time(aware.replace(tzinfo=None)) == "2026-07-19 21:18:49 CEST"


def test_format_time_without_seconds(rome):
    assert format_time(STATUS_CHANGE_MS, seconds=False) == "2026-07-19 21:18 CEST"


def test_format_time_follows_configured_zone(monkeypatch):
    monkeypatch.setenv("BREWFATHER_MCP_TIMEZONE", "UTC")
    assert format_time(ROME_MIDNIGHT_CEST_MS) == "2026-10-23 22:00:00 UTC"


def test_format_day_gives_the_local_day(rome):
    assert format_day(ROME_MIDNIGHT_CEST_MS) == "2026-10-24"


def test_format_day_or_time_drops_a_midnight_time(rome):
    assert format_day_or_time(ROME_MIDNIGHT_CEST_MS) == "2026-10-24"
    assert format_day_or_time(ROME_MIDNIGHT_CET_MS) == "2026-03-21"


def test_format_day_or_time_keeps_a_real_time(rome):
    assert format_day_or_time(STATUS_CHANGE_MS) == "2026-07-19 21:18:49 CEST"


def test_convert_timestamp_to_iso8601_handles_empty_values(rome):
    assert convert_timestamp_to_iso8601(None) is None
    assert convert_timestamp_to_iso8601(ROME_MIDNIGHT_CEST_MS) == "2026-10-24"
