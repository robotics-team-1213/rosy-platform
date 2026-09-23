"""Offline 12-scenario closed loop: same scoring as the Gazebo harness."""

import math

import pytest

from lane_scenarios import GRAPH, SCENARIOS, run_scenario
from control.sensing.lane_boundaries import LaneBoundaryTracker
from lane_sim import CAM_X


def centre_tracker():
    return LaneBoundaryTracker(camera_x_offset_m=CAM_X)


def test_twelve_scenarios_match_the_harness_definition():
    assert len(SCENARIOS) == 12
    assert sorted({s["node"] for s in SCENARIOS}) == ["NE", "NW", "SE", "SW"]


def test_runner_returns_track_and_score_keys():
    result = run_scenario(SCENARIOS[5], centre_tracker(), steps=120)
    for key in ("track", "pass", "branch_ok", "reached_end", "max_centre_dev_m",
                "wrong_way", "ring_ccw_ok", "tiers"):
        assert key in result


def test_centre_mode_reproduces_the_gazebo_baseline_shape():
    """Gazebo run 2026-09-23 (baseline.md): 0/12; 10 never start (no pair to
    seed on a bend); 05 and 11 drive the ring clockwise. The offline loop is
    the same renderer, so it must show the same two failure modes."""
    stuck, moved = [], []
    for scenario in SCENARIOS:
        result = run_scenario(scenario, centre_tracker(), steps=150)
        travelled = sum(math.dist(result["track"][i], result["track"][i + 1])
                        for i in range(len(result["track"]) - 1))
        (moved if travelled > 0.05 else stuck).append(scenario["node"] + ":" + scenario["into"])
        assert not result["pass"]
    assert len(stuck) >= 8, f"expected most starts to fail closed, stuck={stuck}"
    assert moved, "at least one scenario moved in the Gazebo baseline"
