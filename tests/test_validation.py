import pytest

from brewfather_mcp.validation import validate_batch_update


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
