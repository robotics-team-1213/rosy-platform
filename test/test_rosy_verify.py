"""verify_after: the camera decides; a job exit code alone is never success."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import rosy_cli as cli  # noqa: E402
import rosy_observe as obs  # noqa: E402
import rosy_verify as vf  # noqa: E402

CASES = ROOT / "test" / "fixtures" / "llm_loop"
EMPTY = {"result": "stopped: no usable object", "attempts": [{"observed": 0, "refused": [], "error": "no usable object"}]}


def blob(x: float, y: float, obj: str | None = "container-2", why: str = "neighbour clearance: 30.0 / 40.0 mm free beside it") -> dict[str, Any]:
    return {"centre_mm": [x, y], "object": obj, "colour": "red", "why": why}


def sr(*refused: dict[str, Any]) -> dict[str, Any]:
    return {"result": "stopped: no usable object", "attempts": [{"observed": len(refused), "refused": list(refused), "error": "no usable object"}]}


def raw_of(belt: dict[str, Any], pallet: dict[str, Any], dt: float = 0.0, **over: Any) -> dict[str, Any]:
    raw = copy.deepcopy(json.loads((CASES / "belt_middle_box.json").read_text(encoding="utf-8"))["raw"])
    raw["dry_runs"] = [{"site": "belt", "results": [{"ok": True, "structured_result": belt}]},
                       {"site": "pallet", "results": [{"ok": True, "structured_result": pallet}]}]
    raw["fetched_at"] += dt
    for f in raw["frames"].values():
        f["fetched_at"] += dt
        f["source_stamp"] += dt
    raw.update(over)
    return obs.assemble(raw)


PLANNED = json.loads((CASES / "belt_middle_box.json").read_text(encoding="utf-8"))["raw"]["dry_runs"][0]["results"][0]["structured_result"]
STEP = {"verb": "pick", "arm": "arm_b", "target": "c1", "dest": "pallet", "reason": "t"}
BEFORE = raw_of(PLANNED, EMPTY)  # c1 = planned container-2 at (186.3, 178.4), place (153.0, -128.0)
OTHER = blob(200.0, 150.0, "container-3")


def test_picked_and_placed_is_verified_and_exit_code_is_only_echoed():
    after = raw_of(EMPTY, sr(blob(155.0, -126.0)), dt=10)
    out = vf.verify_after(BEFORE, after, STEP, job_exit=0)
    assert out["verdict"] == "VERIFIED" and out["ok"] and out["job_exit_ignored"] == 0
    assert out["checks"]["arrived"]["position_checked"] and out["checks"]["arrived"]["distance_to_plan_mm"] < 5


def test_exit_zero_but_box_still_on_the_belt_is_not_moved():
    out = vf.verify_after(BEFORE, raw_of(PLANNED, EMPTY, dt=10), STEP, job_exit=0)
    assert (out["verdict"], out["ok"]) == ("NOT_MOVED", False) and "alternate_target" in out["next"] and "retry_same" not in out["next"]


def test_source_cleared_but_not_at_destination_is_misplaced():
    far = vf.verify_after(BEFORE, raw_of(EMPTY, sr(blob(100.0, -60.0)), dt=10), STEP)
    assert far["verdict"] == "MISPLACED" and far["next"] == ["ask_human"]
    wrong_id = vf.verify_after(BEFORE, raw_of(EMPTY, sr(blob(153.0, -128.0, "container-3")), dt=10), STEP)
    assert wrong_id["verdict"] == "MISPLACED"
    assert vf.verify_after(BEFORE, raw_of(EMPTY, EMPTY, dt=10), STEP)["verdict"] == "MISPLACED"


def test_another_box_that_moved_is_collateral_even_if_the_pick_worked():
    before = raw_of({**PLANNED, "attempts": [{**PLANNED["attempts"][0], "refused": [OTHER]}]}, EMPTY)
    moved = raw_of(sr(blob(200.0, 125.0, "container-3")), sr(blob(153.0, -128.0)), dt=10)
    out = vf.verify_after(before, moved, STEP)
    assert out["verdict"] == "COLLATERAL" and out["checks"]["others_unmoved"]["moved_or_gone"] == ["c2"]
    kept = raw_of(sr(blob(202.0, 151.0, "container-3")), sr(blob(153.0, -128.0)), dt=10)
    assert vf.verify_after(before, kept, STEP)["verdict"] == "VERIFIED"


def test_arm_state_and_unobservable_after_come_first():
    ready = {"arms": {"arm_b": {"folded": False, "incident_held": False, "human_hold_latched": False, "fault": False, "dirty": False, "active_job_id": None}}}
    out = vf.verify_after(BEFORE, raw_of(EMPTY, sr(blob(153.0, -128.0)), dt=10, readiness=ready), STEP)
    assert out["verdict"] == "ARM_NOT_SAFE" and out["next"] == ["ask_human"]
    stale = vf.verify_after(BEFORE, BEFORE, STEP)
    assert stale["verdict"] == "UNOBSERVABLE" and "not newer" in stale["checks"]["why"]
    dark_raw = {"schema": obs.SCHEMA, "arm": "arm_b", "observable": False, "reason": "DARK_FRAME:top:0.0", "observed_at": 5e9, "observation_id": "d"}
    assert vf.verify_after(BEFORE, dark_raw, STEP)["verdict"] == "UNOBSERVABLE"


def test_destination_not_observed_is_inconclusive_never_verified():
    after = raw_of(EMPTY, EMPTY, dt=10)
    after["runs"] = [r for r in after["runs"] if r["site"] != "pallet"]
    assert vf.verify_after(BEFORE, after, STEP)["verdict"] == "INCONCLUSIVE"


def test_push_is_verified_by_a_small_shift_and_nothing_else_moving():
    edge = json.loads((CASES / "belt_edge_box.json").read_text(encoding="utf-8"))["raw"]["dry_runs"][0]["results"][0]["structured_result"]
    before = raw_of(edge, EMPTY)
    step = {"verb": "push", "arm": "arm_b", "target": "c1", "reason": "t"}
    shifted = raw_of(sr(blob(191.0, 165.0, None, "no catalogue match")), EMPTY, dt=10)
    assert vf.verify_after(before, shifted, step)["verdict"] == "VERIFIED"
    assert vf.verify_after(before, raw_of(edge, EMPTY, dt=10), step)["verdict"] == "NOT_MOVED"


def test_cli_verify_exit_code(tmp_path):
    for name, obj in (("b.json", BEFORE), ("a.json", raw_of(EMPTY, sr(blob(153.0, -128.0)), dt=10)), ("s.json", STEP), ("n.json", raw_of(PLANNED, EMPTY, dt=10))):
        (tmp_path / name).write_text(json.dumps(obj), encoding="utf-8")
    base = ["verify", "--before", str(tmp_path / "b.json"), "--step", str(tmp_path / "s.json"), "--job-exit", "0"]
    assert cli.main([*base, "--after", str(tmp_path / "a.json")]) == 0
    assert cli.main([*base, "--after", str(tmp_path / "n.json")]) == 1
