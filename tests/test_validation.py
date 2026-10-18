import pytest

from brewfather_mcp.types import InventoryCategory
from brewfather_mcp.validation import (
    validate_batch_update,
    validate_inventory_fields,
    validate_recipe_payload,
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


def test_recipe_create_minimal():
    assert validate_recipe_payload({"name": "Test"}, creating=True) == {"name": "Test"}


@pytest.mark.parametrize("data", [{}, {"name": ""}, {"name": "  "}, {"name": None}])
def test_recipe_create_requires_name(data):
    with pytest.raises(ValueError):
        validate_recipe_payload(data, creating=True)


@pytest.mark.parametrize(
    "data",
    [
        {"_id": "x"},
        {"data": {}},
        {"createdAt": "x"},
        {"og": 1.05},
        {"ibu": 30},
        {"type": "Brew in a Bag"},
        {"batchSize": 0.1},
        {"efficiency": 20},
        {"mashEfficiency": 101},
        {"batchSize": True},
        {"hops": "Citra"},
        {"hops": ["Citra"]},
        {"ibuFormula": "magic"},
    ],
)
def test_recipe_rejects(data):
    with pytest.raises(ValueError):
        validate_recipe_payload({"name": "Test", **data}, creating=True)


def test_recipe_update_rejects_empty_ingredient_array():
    for field in ("fermentables", "hops", "miscs", "yeasts"):
        with pytest.raises(ValueError, match="erase"):
            validate_recipe_payload({field: []}, creating=False)
    data = {"hops": [{"name": "Citra", "amount": 20}]}
    assert validate_recipe_payload(data, creating=False) == data


def test_recipe_create_allows_empty_ingredient_array():
    data = {"name": "Test", "hops": []}
    assert validate_recipe_payload(data, creating=True) == data


def test_recipe_update_clear_author():
    assert validate_recipe_payload({"author": None}, creating=False) == {"author": None}


def test_recipe_update_name_cannot_be_cleared():
    with pytest.raises(ValueError):
        validate_recipe_payload({"name": None}, creating=False)


def test_recipe_update_empty():
    with pytest.raises(ValueError):
        validate_recipe_payload({}, creating=False)


@pytest.mark.parametrize("field", ["fermentables", "hops", "miscs", "yeasts"])
def test_recipe_update_rejects_null_ingredient_array(field):
    with pytest.raises(ValueError, match="erase"):
        validate_recipe_payload({field: None}, creating=False)


@pytest.mark.parametrize("name", ["", "   "])
def test_recipe_update_rejects_blank_name(name):
    with pytest.raises(ValueError):
        validate_recipe_payload({"name": name}, creating=False)


def test_recipe_rejects_unhashable_enum_value():
    with pytest.raises(ValueError):
        validate_recipe_payload({"type": {}}, creating=False)
    with pytest.raises(ValueError):
        validate_recipe_payload({"ibuFormula": ["tinseth"]}, creating=False)


def test_inventory_rejects_unhashable_enum_value():
    with pytest.raises(ValueError):
        validate_inventory_fields(InventoryCategory.HOPS, {"type": ["Pellet"]})


# --- null only for fields the API documents as nullable ---


@pytest.mark.parametrize(
    "category, field",
    [
        (InventoryCategory.HOPS, "type"),
        (InventoryCategory.HOPS, "alpha"),
        (InventoryCategory.HOPS, "use"),
        (InventoryCategory.FERMENTABLES, "type"),
        (InventoryCategory.FERMENTABLES, "color"),
        (InventoryCategory.YEASTS, "form"),
        (InventoryCategory.YEASTS, "unit"),
        (InventoryCategory.MISCS, "unit"),
        (InventoryCategory.MISCS, "use"),
    ],
)
def test_inventory_rejects_null_for_non_nullable_field(category, field):
    with pytest.raises(ValueError, match="cannot be cleared"):
        validate_inventory_fields(category, {field: None})


@pytest.mark.parametrize(
    "category, field",
    [
        (InventoryCategory.HOPS, "beta"),
        (InventoryCategory.HOPS, "origin"),
        (InventoryCategory.FERMENTABLES, "supplier"),
        (InventoryCategory.FERMENTABLES, "grainCategory"),
        (InventoryCategory.YEASTS, "laboratory"),
        (InventoryCategory.YEASTS, "notes"),
        (InventoryCategory.MISCS, "concentration"),
    ],
)
def test_inventory_allows_null_for_nullable_field(category, field):
    assert validate_inventory_fields(category, {field: None}) == {field: None}


@pytest.mark.parametrize("field", ["type", "batchSize", "efficiency", "boilTime", "notes"])
def test_recipe_rejects_null_for_non_optional_field(field):
    with pytest.raises(ValueError, match="cannot be cleared"):
        validate_recipe_payload({field: None}, creating=False)


@pytest.mark.parametrize("field", ["author", "style", "styleConformity"])
def test_recipe_allows_null_for_optional_field(field):
    assert validate_recipe_payload({field: None}, creating=False) == {field: None}


def test_recipe_allows_empty_string_to_clear_text():
    assert validate_recipe_payload({"notes": ""}, creating=False) == {"notes": ""}


def test_grain_category_allowlist():
    fields = {"grainCategory": "Crystal/Caramel"}
    assert validate_inventory_fields(InventoryCategory.FERMENTABLES, fields) == fields
    with pytest.raises(ValueError):
        validate_inventory_fields(InventoryCategory.FERMENTABLES, {"grainCategory": "Toasted"})
