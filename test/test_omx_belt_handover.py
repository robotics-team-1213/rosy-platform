"""The belt handover accepts one evidenced box at a time."""

from pathlib import Path
import random
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))

from cell_belt_handover import BeltHandover, Hold  # noqa: E402


EMPTY = {"occupancy": "empty", "reason": "region_clear"}
OCCUPIED = {"occupancy": "occupied", "reason": "container_in_region"}
UNKNOWN = {"occupancy": "unknown", "reason": "stale_frame"}


def assert_hold(reason, fn, *args):
    with pytest.raises(Hold) as exc:
        fn(*args)
    assert exc.value.reason == reason


def test_happy_chain_and_event_log():
    now = [10.0]
    belt = BeltHandover(5, clock=lambda: now[0])
    generation = belt.reserve("box-1", EMPTY)
    assert generation == 1
    belt.placed(generation, "box-1")
    belt.arrived(generation, "box-1", OCCUPIED)
    belt.grasped(generation, "box-1")
    belt.cleared(generation, EMPTY)
    assert (belt.state, belt.cargo, belt.generation) == ("empty", None, 1)
    assert [entry["event"] for entry in belt.events] == ["reserve", "placed", "arrived", "grasped", "cleared"]
    assert all(set(entry) == {"event", "generation", "cargo", "t", "reason"} for entry in belt.events)
    assert all(entry["generation"] == 1 and entry["cargo"] == "box-1" and entry["t"] == 10.0
               and entry["reason"] == "" for entry in belt.events)
    assert belt.reserve("box-2", EMPTY) == 2


@pytest.mark.parametrize("reading,reason", [(UNKNOWN, "reading_stale_frame"),
                                            (OCCUPIED, "belt_occupied")])
def test_reserve_needs_empty_reading(reading, reason):
    belt = BeltHandover(5)
    assert_hold(reason, belt.reserve, "box", reading)
    assert (belt.state, belt.cargo, belt.generation, belt.events) == ("empty", None, 0, [])


@pytest.mark.parametrize("reading,reason", [(UNKNOWN, "reading_stale_frame"),
                                            (EMPTY, "belt_empty")])
def test_arrival_needs_occupied_reading(reading, reason):
    belt = BeltHandover(5)
    gen = belt.reserve("box", EMPTY)
    belt.placed(gen, "box")
    assert_hold(reason, belt.arrived, gen, "box", reading)
    assert belt.state == "placed"


@pytest.mark.parametrize("reading,reason", [(UNKNOWN, "reading_stale_frame"),
                                            (OCCUPIED, "belt_occupied")])
def test_clear_needs_empty_reading(reading, reason):
    belt = BeltHandover(5)
    gen = belt.reserve("box", EMPTY)
    belt.placed(gen, "box")
    belt.arrived(gen, "box", OCCUPIED)
    belt.grasped(gen, "box")
    assert_hold(reason, belt.cleared, gen, reading)
    assert (belt.state, belt.cargo) == ("picked", "box")


def test_stale_generation_and_cargo_mismatch():
    belt = BeltHandover(5)
    gen = belt.reserve("box", EMPTY)
    assert_hold("stale_generation", belt.placed, gen - 1, "box")
    assert_hold("cargo_mismatch", belt.placed, gen, "other")
    belt.placed(gen, "box")
    assert_hold("stale_generation", belt.arrived, gen + 1, "box", OCCUPIED)
    assert_hold("cargo_mismatch", belt.arrived, gen, "other", OCCUPIED)
    belt.arrived(gen, "box", OCCUPIED)
    assert_hold("stale_generation", belt.grasped, gen - 1, "box")
    assert_hold("cargo_mismatch", belt.grasped, gen, "other")
    belt.grasped(gen, "box")
    assert_hold("stale_generation", belt.cleared, gen - 1, EMPTY)
    belt.cleared(gen, EMPTY)
    belt.reserve("next", EMPTY)
    assert_hold("stale_generation", belt.placed, gen, "box")


def test_repeated_accepted_events_are_no_ops_even_after_later_transitions():
    belt = BeltHandover(5)
    gen = belt.reserve("box", EMPTY)
    belt.placed(gen, "box")
    belt.arrived(gen, "box", OCCUPIED)
    belt.placed(gen, "box")
    belt.grasped(gen, "box")
    belt.arrived(gen, "box", UNKNOWN)
    belt.cleared(gen, EMPTY)
    belt.grasped(gen, "box")
    belt.cleared(gen, UNKNOWN)
    assert belt.state == "empty" and len(belt.events) == 5


def test_all_events_out_of_order():
    belt = BeltHandover(5)
    assert_hold("state_empty", belt.placed, 0, None)
    assert_hold("state_empty", belt.arrived, 0, None, OCCUPIED)
    assert_hold("state_empty", belt.grasped, 0, None)
    assert_hold("state_empty", belt.cleared, 0, EMPTY)
    gen = belt.reserve("box", EMPTY)
    assert_hold("state_reserved", belt.reserve, "other", EMPTY)
    assert_hold("state_reserved", belt.arrived, gen, "box", OCCUPIED)
    assert_hold("state_reserved", belt.grasped, gen, "box")
    assert_hold("state_reserved", belt.cleared, gen, EMPTY)
    belt.placed(gen, "box")
    assert_hold("state_placed", belt.reserve, "other", EMPTY)
    assert_hold("state_placed", belt.grasped, gen, "box")
    assert_hold("state_placed", belt.cleared, gen, EMPTY)
    belt.arrived(gen, "box", OCCUPIED)
    assert_hold("state_at_end", belt.reserve, "other", EMPTY)
    assert_hold("state_at_end", belt.cleared, gen, EMPTY)
    belt.grasped(gen, "box")
    assert_hold("state_picked", belt.reserve, "other", EMPTY)
    assert_hold("state_picked", belt.resolve, "operator", "note")
    belt.cleared(gen, EMPTY)
    assert_hold("state_empty", belt.resolve, "operator", "note")


def test_missing_after_window_and_person_only_resolution():
    now = [0.0]
    belt = BeltHandover(5, clock=lambda: now[0])
    gen = belt.reserve("box", EMPTY)
    belt.placed(gen, "box")
    now[0] = 5.0
    assert belt.check() == "placed"
    now[0] = 5.1
    assert belt.check() == "missing"
    assert belt.check() == "missing" and [e["event"] for e in belt.events].count("missing") == 1
    assert_hold("state_missing", belt.reserve, "next", EMPTY)
    assert_hold("state_missing", belt.arrived, gen, "box", OCCUPIED)
    assert_hold("state_missing", belt.grasped, gen, "box")
    assert_hold("state_missing", belt.cleared, gen, EMPTY)
    belt.resolve("alice", "belt inspected")
    assert belt.state == "empty" and belt.cargo is None
    assert belt.events[-2]["reason"] == "timeout"
    assert belt.events[-1] == {"event": "resolve", "generation": gen, "cargo": "box", "t": 5.1,
                               "reason": "belt inspected", "operator": "alice", "note": "belt inspected"}
    assert_hold("state_empty", belt.resolve, "alice", "again")


def test_seeded_event_sequence_never_creates_a_second_box():
    rng = random.Random(37)
    belt = BeltHandover(5, clock=lambda: 0.0)
    states = {"empty", "reserved", "placed", "at_end", "picked", "missing"}
    for _ in range(1000):
        cargo = rng.choice(["a", "b"])
        gen = rng.choice([belt.generation, belt.generation - 1, belt.generation + 1])
        event = rng.choice(["reserve", "placed", "arrived", "grasped", "cleared", "check", "resolve"])
        try:
            if event == "reserve":
                belt.reserve(cargo, rng.choice([EMPTY, OCCUPIED, UNKNOWN]))
            elif event == "placed":
                belt.placed(gen, cargo)
            elif event == "arrived":
                belt.arrived(gen, cargo, rng.choice([EMPTY, OCCUPIED, UNKNOWN]))
            elif event == "grasped":
                belt.grasped(gen, cargo)
            elif event == "cleared":
                belt.cleared(gen, rng.choice([EMPTY, OCCUPIED, UNKNOWN]))
            elif event == "check":
                belt.check()
            else:
                belt.resolve("operator", "inspected")
        except Hold:
            pass
        assert belt.state in states
        assert (belt.cargo is None) == (belt.state == "empty")
        assert len({entry["cargo"] for entry in belt.events if entry["generation"] == belt.generation}) <= 1
