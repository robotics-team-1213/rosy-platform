"""A human-hold latch a gone runner left behind is reported as what is there now (2026-11-27 arm_b, USB loss)."""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_job_readiness as readiness  # noqa: E402

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def _cell(tmp_path, *, torque=False, live_t, gripper_raw=2007):
    (tmp_path / "chunk-io-b").mkdir(parents=True)
    (tmp_path / "chunk-io-b" / "live.json").write_text(json.dumps(
        {"chunk": None, "fault": "human hold", "human_hold_latched": True, "state": [17.5, -3.0, 17.7, 34.9, -13.4, 55.6], "t": live_t}))
    for name in ("mh", "cal", "leases"):
        (tmp_path / name).mkdir()
    (tmp_path / "cal" / "arm_b_follower.json").write_text(json.dumps(
        {j: {"id": 11 + i, "drive_mode": 0, "homing_offset": 0, "range_min": 0, "range_max": 4095} for i, j in enumerate(JOINTS)}))
    raws = [2038, 867, 3153, 3171, 1080, gripper_raw]  # the cell's arm_b at 00:54: folded, wrist turned, torque off
    (tmp_path / "mh" / "arm_b.json").write_text(json.dumps({
        "schema_version": "rosy.motor-health.v1", "owner_id": "arm_b", "status": "active", "observed_at": time.time(),
        "stop_reasons": [], "motors": [{"id": 11 + i, "present_raw": float(r), "torque_enabled": torque, "fault": False,
                                        "hardware_error": 0} for i, r in enumerate(raws)]}))
    return SimpleNamespace(workdir=tmp_path, lock_dir=tmp_path, lease_dir=tmp_path / "leases",
                           motor_health_dir=tmp_path / "mh", calibration_dir=tmp_path / "cal")


def _summary(runner, locked=False):
    return readiness._arm_summary("arm_b", runner, time.time(), session_lock_held_fn=lambda *_: locked, inc_reason=None,
                                  active_job=None, cell_fleet={})


def test_a_left_behind_latch_reads_as_the_folded_torque_off_arm(tmp_path):
    info, blocks = _summary(_cell(tmp_path, live_t=time.time() - 5400))
    assert info["stale_latch_superseded"]["fault"] == "human hold" and info["human_hold_latched"] is False
    assert info["fault"] is None and info["folded"] is True and blocks == []


def test_a_fresh_held_or_torque_on_latch_still_blocks(tmp_path):
    for case, (kw, locked) in {"fresh": ({"live_t": time.time()}, False), "torque": ({"live_t": 0, "torque": True}, False),
                               "locked": ({"live_t": 0}, True),
                               "jaws open": ({"live_t": 0, "gripper_raw": 2400}, False)}.items():
        info, blocks = _summary(_cell(tmp_path / case, **kw), locked=locked)
        assert info["human_hold_latched"] is True and "arm_b:human_hold_latched" in blocks, case
        assert info["stale_latch_superseded"] is None, case
