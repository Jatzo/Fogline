"""Tests for the integer, randomness, state and ledger foundations."""

import pytest

from fogline import intmath, ledger, rng
from fogline.config import Config
from fogline.state import StateError, canonical_json, loads, parse_tile_key, state_hash, tile_key


# intmath

@pytest.mark.parametrize("a,b,expected", [(7, 2, 3), (-7, 2, -4), (6, 3, 2), (0, 5, 0)])
def test_floor_div_rounds_towards_minus_infinity(a, b, expected):
    assert intmath.floor_div(a, b) == expected


@pytest.mark.parametrize("a,b,expected", [(7, 2, 4), (-7, 2, -3), (6, 3, 2), (1, 25, 1), (0, 25, 0)])
def test_ceil_div_rounds_towards_plus_infinity(a, b, expected):
    assert intmath.ceil_div(a, b) == expected


def test_per_mille_applies_rate_and_rounds_down():
    assert intmath.per_mille(55, 250) == 13
    assert intmath.per_mille(1000, 1500) == 1500
    assert intmath.per_mille(-3, 500) == -2


def test_division_by_zero_is_refused():
    with pytest.raises(ZeroDivisionError):
        intmath.ceil_div(1, 0)


# rng

def test_stream_known_answers_pin_the_python_random_algorithm():
    # If CPython ever changes randrange, this fails and stored runs would no longer replay.
    sequence = rng.stream(1, "events", 0, "world", "test")
    assert [sequence.randrange(1_000_000) for _ in range(5)] == [866521, 827960, 491217, 385226, 374240]


def test_same_key_gives_the_same_draws():
    a = rng.stream(42, "combat", 10, "ironhold", "roll")
    b = rng.stream(42, "combat", 10, "ironhold", "roll")
    assert [a.randrange(10**9) for _ in range(20)] == [b.randrange(10**9) for _ in range(20)]


@pytest.mark.parametrize("field_index", range(5))
def test_changing_any_key_part_changes_the_draws(field_index):
    base = [42, "combat", 10, "ironhold", "roll"]
    other = list(base)
    other[field_index] = {0: 43, 1: "unrest", 2: 11, 3: "verdance", 4: "loot"}[field_index]
    a = rng.stream(*base)
    b = rng.stream(*other)
    assert [a.randrange(10**9) for _ in range(5)] != [b.randrange(10**9) for _ in range(5)]


def test_unknown_system_and_missing_purpose_are_refused():
    with pytest.raises(ValueError):
        rng.stream(1, "weather", 0, "world", "x")
    with pytest.raises(ValueError):
        rng.stream(1, "events", 0, "world", "")


def test_chance_is_integer_and_bounded():
    stream = rng.stream(1, "unrest", 0, "ironhold", "riot")
    hits = sum(rng.chance(stream, 100) for _ in range(10_000))
    assert 800 < hits < 1200
    assert not any(rng.chance(stream, 0) for _ in range(100))
    assert all(rng.chance(stream, 1000) for _ in range(100))


# state

def test_canonical_json_sorts_keys_and_round_trips_to_the_same_hash():
    value = {"b": [1, 2, {"z": None, "a": True}], "a": "text", "tiles": {tile_key(3, 4): 7}}
    text = canonical_json(value)
    assert text.startswith('{"a":"text"')
    assert state_hash(loads(text)) == state_hash(value)


def test_floats_are_refused_on_the_way_out_and_in():
    with pytest.raises(StateError):
        canonical_json({"x": 1.5})
    with pytest.raises(StateError):
        loads('{"x": 1.5}')


def test_non_string_keys_and_tuples_are_refused():
    with pytest.raises(StateError):
        canonical_json({1: "a"})
    with pytest.raises(StateError):
        canonical_json({"t": (1, 2)})


def test_tile_keys_round_trip():
    assert parse_tile_key(tile_key(12, -3)) == (12, -3)


# ledger

def test_ledger_changes_stock_and_records_totals_by_rule():
    stocks: dict[str, int] = {"food": 10}
    totals: dict[str, int] = {}
    log: list = []
    ledger.apply(stocks, totals, log, "verdance", "food", 5, ledger.Rule.PRODUCTION, 3)
    ledger.apply(stocks, totals, log, "verdance", "food", -4, ledger.Rule.EATING, 3)
    assert stocks["food"] == 11
    assert totals == {"verdance:food:production": 5, "verdance:food:eating": -4}
    assert ledger.net_change(totals, "verdance", "food") == 1
    assert log[0] == {"tick": 3, "owner": "verdance", "stock": "food", "delta": 5, "rule": "production"}


def test_ledger_refuses_to_go_below_zero_and_leaves_stock_unchanged():
    stocks = {"metal": 2}
    totals: dict[str, int] = {}
    with pytest.raises(ledger.LedgerError):
        ledger.apply(stocks, totals, None, "verdance", "metal", -3, ledger.Rule.TOOL_WEAR, 0)
    assert stocks == {"metal": 2} and totals == {}


def test_ledger_refuses_unknown_stock_unnamed_rule_and_non_int_delta():
    with pytest.raises(ledger.LedgerError):
        ledger.apply({}, {}, None, "x", "gold", 1, ledger.Rule.PRODUCTION, 0)
    with pytest.raises(ledger.LedgerError):
        ledger.apply({}, {}, None, "x", "food", 1, "production", 0)
    with pytest.raises(ledger.LedgerError):
        ledger.apply({}, {}, None, "x", "food", 1.0, ledger.Rule.PRODUCTION, 0)


# config

def test_config_is_plain_and_hashes_stably():
    config = Config()
    assert config.config_hash() == Config().config_hash()
    assert len(config.civs) == 5
    assert config.civ("dunerunners").short_of == ("food", "timber")


def test_config_starting_stocks_cannot_be_changed_in_place():
    with pytest.raises(TypeError):
        Config().civ("ironhold").start_stock["food"] = 0


def test_nan_in_saved_state_is_refused():
    with pytest.raises(StateError):
        loads('{"x": NaN}')


def test_changing_a_number_changes_the_config_hash():
    assert Config().config_hash() != Config(spoilage=6).config_hash()
