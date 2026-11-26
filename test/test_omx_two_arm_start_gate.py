"""Two-arm policy start gate (2026-11-26): each arm's measured state must lie in its own checkpoint's trained range, before every chunk."""
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from test_omx_two_arm_policy_pipeline import FakeCell, PlanarKin, _base_lib, guard_mod, pol_mod  # noqa: E402
import cell_policy_start_gate as sg  # noqa: E402

HOME_A, HOME_B = [-40.0, -40.0, 40.0, 40.0, 0.0, 50.0], [40.0, -40.0, 40.0, 40.0, 0.0, 50.0]


class Shadow:
    image_views, sim_rule = {"top": (24, 32)}, None

    def __init__(self, target):
        self.target, self.inferred = target, 0

    def inputs(self, state, frames, goal=None):
        return {}, {}

    def infer(self, obs, state=None):
        self.inferred += 1
        return SimpleNamespace(chunk=[list(self.target)] * 2, rtt_s=0.01)


def gate(home, override=None):
    """A gate whose trained range is home +-5 units, optionally with one joint's (low, high) replaced."""
    low, high = np.asarray(home, dtype=float) - 5.0, np.asarray(home, dtype=float) + 5.0
    for joint, (lo, hi) in (override or {}).items():
        low[joint], high[joint] = lo, hi
    return sg.StateGate({"min": low, "max": high})


def run(tmp_path, gates, *, dry_run, max_chunks=1):
    kins = {"a": PlanarKin(0.10), "b": PlanarKin(0.10)}
    guard = guard_mod.TwoArmChunkGuard(kins, {"a": (0.0, 0.0, -0.25), "b": (0.0, 0.0, 0.25)}, {"a": 0.074, "b": 0.074}, margin_m=0.05, min_z_m=-0.05, mid_y_band=0.02)
    cells, shadows = {"a": FakeCell(HOME_A), "b": FakeCell(HOME_B)}, {"a": Shadow(HOME_A), "b": Shadow(HOME_B)}
    auths = {k: (lambda _lib, _st, _seq, _k=k: {"session_id": f"s-{_k}", "library_sha256": "f" * 64}) for k in ("a", "b")}
    result = pol_mod.run_two_arm_policy(
        cells, shadows, {"a": _base_lib(HOME_A), "b": _base_lib(HOME_B)}, guard,
        {"src": "belt", "dst": "temp_a:r1-s1-t1"}, {"src": "temp_b:r1-s1-t1", "dst": "temp_b:r2-s1-t1"}, tmp_path,
        max_chunks=max_chunks, dry_run=dry_run, authorizers=None if dry_run else auths, state_gates=gates)
    return result, cells, shadows


def test_an_arm_outside_its_own_checkpoint_range_stops_both_arms_before_any_chunk(tmp_path):
    gates = {"a": gate(HOME_A), "b": gate(HOME_B, {1: (-70.0, -50.0)})}  # arm_b was trained with the lift folded, not at -40
    result, cells, shadows = run(tmp_path, gates, dry_run=False)
    assert result["result"] == "refused" and sg.RANGE_CODE in result["stopped_reason"] and "shoulder_lift" in result["stopped_reason"]
    assert result["stopped_reason"].startswith("b:") and shadows["b"].inferred == 0
    assert all("human-hold" in cell.commands for cell in cells.values())  # the existing stop path: coupled human-hold
    assert not any("load" in c or "run policy" in c for c in cells["b"].commands)  # arm_a may already be running its own chunk


def test_each_arm_is_judged_against_its_own_statistics(tmp_path):
    swapped = {"a": gate(HOME_B), "b": gate(HOME_A)}  # a's range holds b's state only: the pan differs by 80 units
    result, _cells, _shadows = run(tmp_path, swapped, dry_run=False)
    assert result["result"] == "refused" and sg.RANGE_CODE in result["stopped_reason"]


def test_trained_states_run_every_chunk_and_a_dry_run_is_gated_too(tmp_path):
    gates = {"a": gate(HOME_A), "b": gate(HOME_B)}
    result, cells, _ = run(tmp_path / "live", gates, dry_run=False, max_chunks=2)
    assert result["result"] == "chunks_done" and all(r["chunks_done"] == 2 for r in result["arms"].values())
    bad, _cells, _ = run(tmp_path / "dry", {"a": gate(HOME_A, {0: (0.0, 5.0)}), "b": gate(HOME_B)}, dry_run=True)
    assert bad["result"] == "refused" and sg.RANGE_CODE in bad["stopped_reason"]


def test_no_gates_keeps_the_runner_as_it_was(tmp_path):
    result, _cells, shadows = run(tmp_path, None, dry_run=True)
    assert result["result"] == "dry_run" and shadows["a"].inferred == 1
