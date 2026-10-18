import pytest

from brewfather_mcp.types import InventoryCategory
from brewfather_mcp.validation import (
    validate_batch_update,
    validate_inventory_fields,
)


def test_batch_update_valid():
    values = {"measuredOg": 1.055, "status": "Fermenting"}
    assert validate_batch_update(values) == values


def test_batch_update_clear():
    assert validate_batch_update({}, ["measuredFg"]) == {"measuredFg": None}


@pytest.mark.parametrize(
    "values",
    [
        {"measuredOg": 2.0},
        {"measuredOg": 0.05},
        {"measuredMashPh": 14.5},
        {"measuredBatchSize": -1},
        {"carbonationTemp": 101},
        {"status": "Done"},
        {"measuredOg": True},
        {"measuredOg": float("nan")},
        {"measuredOg": float("inf")},
        {"measuredOg": "1.05"},
        {"colour": 1},
    ],
)
def test_batch_update_rejects(values):
    with pytest.raises(ValueError):
        validate_batch_update(values)


@pytest.mark.parametrize(
    "values, clear_fields",
    [
        ({"measuredOg": 1.05}, ["measuredOg"]),
        ({}, ["status"]),
        ({}, ["nope"]),
    ],
)
def test_batch_update_clear_conflicts(values, clear_fields):
    with pytest.raises(ValueError):
        validate_batch_update(values, clear_fields)


def test_batch_update_empty():
    with pytest.raises(ValueError):
        validate_batch_update({})


def test_inventory_valid_hop():
    fields = {"name": "Citra", "alpha": 12.0, "type": "Pellet"}
    assert validate_inventory_fields(InventoryCategory.HOPS, fields) == fields


def test_inventory_allows_null_to_clear():
    fields = {"supplier": None}
    assert validate_inventory_fields(InventoryCategory.FERMENTABLES, fields) == fields


@pytest.mark.parametrize(
    "category, fields",
    [
        (InventoryCategory.HOPS, {"alphaa": 1}),
        (InventoryCategory.HOPS, {"type": "Powder"}),
        (InventoryCategory.HOPS, {"use": "Whirlpool"}),
        (InventoryCategory.YEASTS, {"form": "Cube"}),
        (InventoryCategory.YEASTS, {"flocculation": "Max"}),
        (InventoryCategory.FERMENTABLES, {"type": "Fruit"}),
        (InventoryCategory.MISCS, {"type": "Metal"}),
        (InventoryCategory.HOPS, {"_id": "x"}),
        (InventoryCategory.HOPS, {"createdAt": "x"}),
        (InventoryCategory.HOPS, {"inventory_adjust": 5}),
        (InventoryCategory.HOPS, {"alpha": float("nan")}),
        (InventoryCategory.HOPS, {"alpha": True}),
        (InventoryCategory.HOPS, {"alpha": "12"}),
        (InventoryCategory.HOPS, {"hidden": "yes"}),
        (InventoryCategory.HOPS, {"name": ""}),
        (InventoryCategory.HOPS, {}),
    ],
)
def test_inventory_rejects(category, fields):
    with pytest.raises(ValueError):
        validate_inventory_fields(category, fields)
