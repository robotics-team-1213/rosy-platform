"""Actual pre-motion and post-placement entrypoints with instrument observations supplied by fixtures."""
from pathlib import Path
import sys
import time

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in ("deploy/robot/omx", "middleware/devices/omx/adapter"):
    sys.path.insert(0, str(ROOT / folder))

import cell_route_depth as route
import cell_zone_verification as zones


SRC, DST = "tmp-a-1-l1", "ship-h1r0-l0"
SRC_ROI, DST_ROI = [0, 0, 40, 40], [50, 60, 90, 100]
TEMP, SHIP = {"floor": [[0, 80, 40, 100]], "floor_depth_mm": [500]}, {"floor": [[50, 0, 90, 40]], "floor_depth_mm": [550]}


@pytest.fixture
def instruments(monkeypatch):
    class Cell:
        cameras = {"top": True, "side": True}

        def frame_receipt(self, camera, **kwargs):
            return {"image": np.zeros((4, 4, 3)), "source_stamp": time.time(), "camera": camera}

    cfg = {"arm_id": "arm_a", "sites": {SRC: {"place": [0, 0], "layer": 1, "surface_z": 0, "zone_rois": TEMP},
                                        DST: {"place": [1, 1], "layer": 0, "surface_z": 0}},
           "zone_rois": {**SHIP, "top": {"tmp-a-1": SRC_ROI, "ship-h1r0": DST_ROI}}}
    state = {"src_before": 2, "src_after": 1, "dst_before": 0, "dst_after": 1, "phase": 0,
             "edge": 2, "gate": "PASS"}

    def depth(config, after):
        state["phase"] += 1
        return np.ones((4, 4)), {"exposure_wall_estimate_s": time.time(), "raw_sha256": str(state["phase"])}, None

    def read(depth, colour, roi, floor, expected, *, floor_depth_mm):
        site = "src" if roi == SRC_ROI else "dst"
        assert roi == (SRC_ROI if site == "src" else DST_ROI)
        support = TEMP if site == "src" else SHIP
        assert (floor, floor_depth_mm) == (support["floor"], support["floor_depth_mm"])
        observed = state[site + ("_before" if state["phase"] == 1 else "_after")]
        return {"ok": True, "occupied": bool(observed), "tier_ok": observed == expected,
                "tier": expected, "local_edge_px": state["edge"], "median_rel_mm": observed * 30}

    def stack(**kwargs):
        dest = read(None, None, DST_ROI, SHIP["floor"], 1, floor_depth_mm=SHIP["floor_depth_mm"])
        return {"verified": True, "pick_slot": {"vacated": True}, "depth_reference": dest,
                "z_gate": {"verdict": state["gate"]}}

    monkeypatch.setattr(zones, "_depth_after", depth)
    monkeypatch.setattr(route.cell_depth_slots, "depth_reference", read)
    monkeypatch.setattr(zones, "verify_stack_outcome_z_mm", stack)
    return Cell(), cfg, state


@pytest.mark.parametrize("change,passes", [({}, True), ({"src_after": 2}, False), ({"src_after": 0}, False),
                                          ({"dst_after": 0}, False), ({"gate": "UNKNOWN"}, False),
                                          ({"edge": None}, False)])
def test_measure_requires_both_transitions(instruments, change, passes):
    cell, cfg, state = instruments
    before, error = route.policy_before(cell, cfg, SRC, DST)
    assert error is None
    state.update(change)
    row = {}
    tried = {"verify": {"verified": True, "inside": True}, "transfer": {}}
    zones.record(row, tried, cell, before, cfg, DST, SRC, DST_ROI)
    measured = row["zone_verification"]
    assert measured["verified"] is passes
    assert row["verify"]["verified"] is passes
    assert measured["pick_slot"]["vacated"] is (state["src_after"] == 1 and state["edge"] is not None)


@pytest.mark.parametrize("change", [{"src_before": 1}, {"dst_before": 1}, {"edge": None}])
def test_refuses_before_motion(instruments, change):
    cell, cfg, state = instruments
    state.update(change)
    before, error = route.policy_before(cell, cfg, SRC, DST)
    assert before is None and error


def test_reassessment_without_depth_and_top_only_refuse(instruments):
    cell, cfg, _ = instruments
    assert not zones.measure(cell, {"_reused": True, "image": object()}, cfg, DST, SRC, DST_ROI)["verified"]
    before, error = route.capture_before(cell, cfg, SRC, DST)
    assert error is None
    del cell.cameras["side"]
    assert not zones.measure(cell, before, cfg, DST, SRC, DST_ROI)["verified"]
    assert route.capture_before(cell, cfg, SRC, DST)[1]


def test_changed_source_roi_refuses(instruments):
    cell, cfg, _ = instruments
    before, error = route.capture_before(cell, cfg, SRC, DST)
    assert error is None
    cfg["zone_rois"]["top"]["tmp-a-1"] = [0, 0, 32, 32]
    assert not zones.measure(cell, before, cfg, DST, SRC, DST_ROI)["verified"]


def test_current_rgb_can_still_be_too_far_from_depth():
    now = time.time()
    top = {"source_stamp": now}
    depth = {"exposure_wall_estimate_s": now - 0.4, "raw_sha256": "burst"}
    assert route._receipt(top, top, depth, now - 0.5, now) is None


def test_dispatch_rechecks_exposure_after_delay(instruments, monkeypatch):
    cell, cfg, _ = instruments
    before, error = route.capture_before(cell, cfg, SRC, DST)
    assert not error
    calls = []
    cell.act = lambda command: calls.append(command) or {"ok": True}
    runner = route.motion_cell(cell, before)
    assert runner.act("checked s h load path")["ok"]
    monkeypatch.setattr(time, "time", lambda: before["source_stamp"] + 3)
    assert not runner.act("checked s h run policy")["ok"]
    assert runner.act("human-hold")["ok"]
    assert calls == ["checked s h load path", "human-hold"]


@pytest.mark.parametrize("settled, remaining, expected", [(True, 1, "placed"), (True, 2, "placement_unverified"),
                                                        (False, 1, "placement_unverified")])
def test_taught_placement_requires_confirmed_park_and_route_depth(instruments, settled, remaining, expected):
    cell, cfg, state = instruments
    before, error = route.capture_before(cell, cfg, SRC, DST)
    assert not error
    state["src_after"] = remaining
    result = {"result": "placed", "steps": [{"command": "park", "ok": True, "settled": settled}]}
    route.policy_result(cell, before, cfg, SRC, DST, result)
    assert result["result"] == expected
    assert result["parked"] is settled
