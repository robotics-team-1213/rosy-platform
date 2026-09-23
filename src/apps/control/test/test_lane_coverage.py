"""All-lane coverage tour (mission plan stage 2, step 1)."""

import pytest
from control.sensing.lane_coverage import (
    coverage_route,
    covered,
    directed_keys,
    endpoints,
    is_legal,
    start_road,
    tour_length,
)
from lane_scenarios import GRAPH

START = tuple(GRAPH["parking"]["points"][0])
#: The eight directed segments of map_v2_fleet (mission plan).
TARGET = {"west:f", "west:r", "east:f", "east:r",
          "ring_n:f", "ring_w:f", "ring_s:f", "ring_e:f"}
#: Brute-force bound: tours of up to this many keys are enumerated.
BRUTE_MAX_KEYS = 15


def test_the_parking_junction_is_on_west():
    assert start_road(GRAPH, START) == "west"


def test_the_directed_keys_are_the_eight_targets():
    assert set(directed_keys(GRAPH)) == TARGET


def test_the_tour_covers_every_directed_segment():
    keys = coverage_route(GRAPH, START)
    assert covered(GRAPH, keys) == TARGET


def test_the_tour_is_legal_and_starts_and_ends_on_west():
    keys = coverage_route(GRAPH, START)
    assert is_legal(GRAPH, keys)
    assert keys[0].split(":")[0] == "west" and keys[-1].split(":")[0] == "west"
    for a, b in zip(keys, keys[1:]):
        assert endpoints(GRAPH, a)[1] == endpoints(GRAPH, b)[0]
        assert a.split(":")[0] != b.split(":")[0]


def test_the_tour_is_deterministic():
    assert coverage_route(GRAPH, START) == coverage_route(GRAPH, START)


def test_legality_rejects_a_u_turn_a_reversed_ring_and_a_gap():
    assert not is_legal(GRAPH, ["west:f", "west:r"])
    assert not is_legal(GRAPH, ["ring_n:r", "west:r"])
    assert not is_legal(GRAPH, ["west:f", "east:f"])
    assert is_legal(GRAPH, ["west:f", "ring_w:f", "west:f"])


def _brute_force_minimum():
    """Shortest covering tour by exhaustive enumeration of every legal key
    sequence up to BRUTE_MAX_KEYS long that starts and ends on west."""
    keys = directed_keys(GRAPH)
    best = [None]

    def extend(seq):
        if len(seq) > 1 and seq[-1].startswith("west:") and covered(GRAPH, seq) == TARGET:
            length = tour_length(GRAPH, seq, START)
            if best[0] is None or length < best[0][0] - 1e-9:
                best[0] = (length, list(seq))
        if len(seq) >= BRUTE_MAX_KEYS:
            return
        for nxt in keys:
            if is_legal(GRAPH, seq[-1:] + [nxt]):
                extend(seq + [nxt])

    for first in ("west:f", "west:r"):
        extend([first])
    return best[0]


def test_the_tour_is_minimal_against_brute_force():
    length, _ = _brute_force_minimum()
    keys = coverage_route(GRAPH, START)
    assert len(keys) <= BRUTE_MAX_KEYS
    assert tour_length(GRAPH, keys, START) == pytest.approx(length, abs=1e-6)


def test_the_tour_length_is_reported():
    keys = coverage_route(GRAPH, START)
    length = tour_length(GRAPH, keys, START)
    # Lower bound: both roads both ways plus the ring once.
    roads = 2 * (GRAPH["segments"]["west"]["length_m"] + GRAPH["segments"]["east"]["length_m"])
    ring = sum(GRAPH["segments"][n]["length_m"] for n in ("ring_n", "ring_w", "ring_s", "ring_e"))
    assert roads + ring <= length < roads + 2.5 * ring
    assert keys == ["west:f", "ring_w:f", "ring_s:f", "east:r", "ring_n:f", "west:r",
                    "ring_s:f", "ring_e:f", "east:f", "ring_e:f", "ring_n:f", "ring_w:f",
                    "west:f"]
    assert length == pytest.approx(16.874, abs=0.01)


def test_a_start_off_every_two_way_road_is_refused():
    with pytest.raises(ValueError, match="two-way road"):
        coverage_route(GRAPH, (5.0, 5.0))
