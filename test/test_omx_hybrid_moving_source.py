"""A moving source (belt) has no fixed pick: the hybrid taught-goal check must not crash on it (2026-11-27, arm A).

The policy grasps the box on the belt and the handoff lifts from the measured hold, so only a source with a fixed
pick is compared with the library's pick; destination and tier are always checked.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_policy_handoff as ph  # noqa: E402

SHIP = {"place": [0.1254, 0.0191], "surface_z": -0.004, "yaw_deg": 0.0, "tier_step_m": 0.0345, "map_from": "pallet",
        "stacks": True, "status": "measured"}
LIB = {"source": {"pick": {"x": 0.158, "y": -0.13, "z": -0.0571}, "place": {"x": 0.1254, "y": 0.0191, "z": 0.074}}, "chunks": {}}
PAST_SOURCE = "missing a folded carry chunk"  # the next check: destination, tier and source passed


def _cfg(belt_pick=None):
    belt = {"surface_z": -0.0661, "place": [0.0, 0.1], "yaw_deg": 0.0}
    if belt_pick is not None:
        belt["pick"] = belt_pick
    return {"sites": {"belt": belt, "pallet": {"surface_z": -0.004, "place": [0.115, 0.034], "yaw_deg": 0.0}, "ship-h1r0": SHIP}}


def test_moving_source_without_a_fixed_pick_passes_on_destination_and_tier():
    with pytest.raises(ValueError, match=PAST_SOURCE):
        ph.validate_taught_goal(_cfg(), "belt", "ship-h1r0-l2", "ship-h1r0-l2", LIB)


def test_fixed_source_pick_is_still_compared():
    with pytest.raises(ValueError, match=PAST_SOURCE):
        ph.validate_taught_goal(_cfg([0.158, -0.13]), "belt", "ship-h1r0-l2", "ship-h1r0-l2", LIB)
    with pytest.raises(ValueError, match="does not match the job source"):
        ph.validate_taught_goal(_cfg([0.10, -0.20]), "belt", "ship-h1r0-l2", "ship-h1r0-l2", LIB)


def test_destination_off_by_10_mm_still_refused():
    lib = {**LIB, "source": {**LIB["source"], "place": {"x": 0.128, "y": 0.029, "z": 0.074}}}
    with pytest.raises(ValueError, match="destination pose and tier"):
        ph.validate_taught_goal(_cfg(), "belt", "ship-h1r0-l2", "ship-h1r0-l2", lib)
