"""Validation of data sent to the Brewfather API.

The API silently accepts unknown fields, so every write is checked here first.
All functions raise ValueError with a message that is safe to show to the user.
"""

import math

from brewfather_mcp.types.batch import BatchStatus
from brewfather_mcp.types.inventory import InventoryCategory

SG_RANGE = (0.1, 1.9)
VOLUME_RANGE = (0.0, None)

BATCH_UPDATE_RANGES: dict[str, tuple[float | None, float | None]] = {
    "measuredMashPh": (0.0, 14.0),
    "measuredBoilSize": VOLUME_RANGE,
    "measuredFirstWortGravity": SG_RANGE,
    "measuredPreBoilGravity": SG_RANGE,
    "measuredPostBoilGravity": SG_RANGE,
    "measuredKettleSize": VOLUME_RANGE,
    "measuredOg": SG_RANGE,
    "measuredFermenterTopUp": VOLUME_RANGE,
    "measuredBatchSize": VOLUME_RANGE,
    "measuredFg": SG_RANGE,
    "measuredBottlingSize": VOLUME_RANGE,
    "carbonationTemp": (-50.0, 100.0),
}


def require_number(
    name: str,
    value: object,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Return value as a float, or raise ValueError if it is not a valid number in range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}, got {value}")
    return float(value)


def parse_inventory_kind(kind: str) -> InventoryCategory:
    """Convert a user-supplied inventory kind (hops, fermentables, ...) to its category."""
    try:
        return InventoryCategory(kind)
    except ValueError:
        valid = [c.value for c in InventoryCategory]
        raise ValueError(f"kind must be one of {valid}, got {kind!r}") from None


def validate_batch_update(
    values: dict[str, object], clear_fields: list[str] | None = None
) -> dict[str, object]:
    """Build a validated PATCH body for a batch. Fields in clear_fields are sent as null."""
    clear_fields = clear_fields or []
    allowed = {"status", *BATCH_UPDATE_RANGES}

    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(
            f"unknown batch field(s) {unknown}; allowed: {sorted(allowed)}"
        )

    body: dict[str, object] = {}
    for name, value in values.items():
        if name == "status":
            valid = [s.value for s in BatchStatus]
            if value not in valid:
                raise ValueError(f"status must be one of {valid}, got {value!r}")
            body[name] = value
        else:
            minimum, maximum = BATCH_UPDATE_RANGES[name]
            body[name] = require_number(name, value, minimum, maximum)

    for name in clear_fields:
        if name == "status":
            raise ValueError("status cannot be cleared")
        if name not in BATCH_UPDATE_RANGES:
            raise ValueError(
                f"cannot clear {name!r}; clearable fields: {sorted(BATCH_UPDATE_RANGES)}"
            )
        if name in body:
            raise ValueError(f"{name} is both set and listed in clear_fields")
        body[name] = None

    if not body:
        raise ValueError("no update parameters provided")
    return body


# --- Inventory items -------------------------------------------------------
# Field names and enum values come from https://docs.brewfather.app/api/types.md
# and https://docs.brewfather.app/api/enums.md. Stock is not writable here (use
# `inventory`/`inventory_adjust` through set_inventory), and neither are the
# recipe-only quantities (amount, percentage, ibu) or server-managed fields.

_STR = "str"
_NUM = "num"
_BOOL = "bool"
_OBJ = "obj"

_TIME_UNITS = {"min", "day", "days"}
_ADDITION_USES = {
    "Boil", "Mash", "Steep", "Primary", "Secondary", "Bottling", "Sparge", "Flameout",
}

INVENTORY_FIELDS: dict[InventoryCategory, dict[str, object]] = {
    InventoryCategory.FERMENTABLES: {
        "name": _STR,
        "type": {"Grain", "Sugar", "Liquid Extract", "Dry Extract", "Adjunct", "Other"},
        "grainCategory": _STR,
        "color": _NUM,
        "lovibond": _NUM,
        "use": _ADDITION_USES,
        "time": _NUM,
        "timeUnit": _TIME_UNITS,
        "origin": _STR,
        "supplier": _STR,
        "potential": _NUM,
        "moisture": _NUM,
        "diastaticPower": _NUM,
        "protein": _NUM,
        "attenuation": _NUM,
        "notFermentable": _BOOL,
        "costPerAmount": _NUM,
        "notes": _STR,
        "hidden": _BOOL,
    },
    InventoryCategory.HOPS: {
        "name": _STR,
        "alpha": _NUM,
        "use": {"Boil", "Dry Hop", "Mash", "First Wort", "Aroma"},
        "time": _NUM,
        "timeUnit": _TIME_UNITS,
        "type": {"Pellet", "Whole", "Cryo", "Plug", "ISOExtract", "CO2Extract"},
        "beta": _NUM,
        "hsi": _NUM,
        "origin": _STR,
        "usage": {"Aroma", "Bittering", "Both"},
        "temp": _NUM,
        "year": _NUM,
        "oil": _NUM,
        "myrcene": _NUM,
        "humulene": _NUM,
        "caryophyllene": _NUM,
        "farnesene": _NUM,
        "geraniol": _NUM,
        "linalool": _NUM,
        "aroma": _OBJ,
        "costPerAmount": _NUM,
        "notes": _STR,
        "hidden": _BOOL,
    },
    InventoryCategory.YEASTS: {
        "name": _STR,
        "type": {"Ale", "Lager", "Hybrid", "Wheat", "Wine", "Champagne", "Other"},
        "form": {"Dry", "Liquid", "Slant", "Culture", "Slurry"},
        "unit": {"g", "ml", "pkg", "billion cells", "oz"},
        "laboratory": _STR,
        "productId": _STR,
        "flocculation": {"Low", "Medium-Low", "Medium", "Medium-High", "High", "Very High"},
        "attenuation": _NUM,
        "minAttenuation": _NUM,
        "maxAttenuation": _NUM,
        "minTemp": _NUM,
        "maxTemp": _NUM,
        "maxAbv": _NUM,
        "notes": _STR,
        "bestFor": _STR,
        "starter": _BOOL,
        "starterSize": _NUM,
        "costPerAmount": _NUM,
        "hidden": _BOOL,
    },
    InventoryCategory.MISCS: {
        "name": _STR,
        "type": {"Spice", "Fining", "Water Agent", "Herb", "Flavor", "Other"},
        "use": _ADDITION_USES,
        "time": _NUM,
        "timeUnit": _TIME_UNITS,
        "unit": {
            "g", "mg", "kg", "oz", "lb", "ml", "l", "tsp", "tbsp", "cup", "pkg",
            "items", "drops", "pt", "qt", "gal",
        },
        "amountPerL": _NUM,
        "concentration": _NUM,
        "waterAdjustment": _BOOL,
        "costPerAmount": _NUM,
        "notes": _STR,
        "hidden": _BOOL,
    },
}


def validate_inventory_fields(
    category: InventoryCategory, fields: dict[str, object]
) -> dict[str, object]:
    """Validate the fields of an inventory item create or partial update.

    A value of None is allowed for every field except name; the API clears the field.
    """
    spec = INVENTORY_FIELDS[category]
    if not fields:
        raise ValueError("no fields provided")

    unknown = sorted(set(fields) - set(spec))
    if unknown:
        raise ValueError(
            f"unknown {category} field(s) {unknown}; allowed: {sorted(spec)}"
        )

    for name, value in fields.items():
        if value is None:
            if name == "name":
                raise ValueError("name cannot be empty")
            continue
        rule = spec[name]
        if rule == _STR:
            if not isinstance(value, str) or (name == "name" and not value.strip()):
                raise ValueError(f"{name} must be a non-empty text, got {value!r}")
        elif rule == _NUM:
            require_number(name, value)
        elif rule == _BOOL:
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be true or false, got {value!r}")
        elif rule == _OBJ:
            if not isinstance(value, dict):
                raise ValueError(f"{name} must be an object, got {value!r}")
        elif not isinstance(value, str) or value not in rule:
            raise ValueError(f"{name} must be one of {sorted(rule)}, got {value!r}")
    return dict(fields)


# --- Recipes -----------------------------------------------------------------
# Writable top-level recipe fields (https://docs.brewfather.app/api/types.md). Calculated
# values (og, fg, abv, ibu, color, totals, data) and server-managed fields are left out:
# the API ignores them, so accepting them would only hide mistakes.

RECIPE_TYPES = {"Extract", "Partial Mash", "All Grain"}
IBU_FORMULAS = {"tinseth", "tinseth*", "rager", "garetz", "noonan"}
INGREDIENT_ARRAYS = ("fermentables", "hops", "miscs", "yeasts")

RECIPE_FIELDS: dict[str, object] = {
    "name": _STR,
    "author": _STR,
    "type": RECIPE_TYPES,
    "teaser": _STR,
    "hidden": _BOOL,
    "style": _OBJ,
    "styleConformity": _BOOL,
    "batchSize": (0.5, None),
    "boilSize": (0.0, None),
    "boilTime": (0.0, None),
    "efficiency": (35.0, 100.0),
    "mashEfficiency": (0.0, 100.0),
    "fermentables": "list",
    "hops": "list",
    "miscs": "list",
    "yeasts": "list",
    "ibuFormula": IBU_FORMULAS,
    "carbonation": (0.0, 5.0),
    "carbonationTemp": _NUM,
    "equipment": _OBJ,
    "mash": _OBJ,
    "fermentation": _OBJ,
    "water": _OBJ,
    "notes": _STR,
    "tags": "list",
    "nutrition": _OBJ,
    "path": _STR,
}


def validate_recipe_payload(
    data: dict[str, object], *, creating: bool
) -> dict[str, object]:
    """Validate the body of a recipe create (POST) or update (PATCH)."""
    unknown = sorted(set(data) - set(RECIPE_FIELDS))
    if unknown:
        raise ValueError(
            f"unknown or read-only recipe field(s) {unknown}; allowed: {sorted(RECIPE_FIELDS)}"
        )
    if creating:
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("a recipe needs a non-empty name")
    if not data:
        raise ValueError("no fields provided")

    for field, value in data.items():
        rule = RECIPE_FIELDS[field]
        if value is None:
            if field == "name":
                raise ValueError("name cannot be cleared")
            if field in INGREDIENT_ARRAYS and not creating:
                raise ValueError(
                    f"clearing {field} would erase all {field} of the recipe; "
                    "send the full new list instead"
                )
            continue
        if rule == _STR:
            if not isinstance(value, str) or (field == "name" and not value.strip()):
                raise ValueError(f"{field} must be non-empty text, got {value!r}")
        elif rule == _BOOL:
            if not isinstance(value, bool):
                raise ValueError(f"{field} must be true or false, got {value!r}")
        elif rule == _OBJ:
            if not isinstance(value, dict):
                raise ValueError(f"{field} must be an object, got {value!r}")
        elif rule == _NUM:
            require_number(field, value)
        elif rule == "list":
            if not isinstance(value, list) or not all(isinstance(i, dict) for i in value):
                raise ValueError(f"{field} must be a list of objects")
            if field in INGREDIENT_ARRAYS and not value and not creating:
                raise ValueError(
                    f"an empty {field} list would erase all {field} of the recipe "
                    "(the API replaces the whole list); send the full new list instead"
                )
        elif isinstance(rule, tuple):
            require_number(field, value, *rule)
        elif not isinstance(value, str) or value not in rule:
            raise ValueError(f"{field} must be one of {sorted(rule)}, got {value!r}")
    return dict(data)
