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
