"""The cell task worker never calls the real arm on a refused handoff, and unknown sites are refused."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_fleet_pipeline as cfp  # noqa: E402
import cell_task_worker as ctw  # noqa: E402

LOCKED = {"wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0}


def _run(tmp_path: Path, handoff: dict, tier: int = 1):
    hw_calls: list[dict] = []
    posted: list[dict] = []

    def _req(method: str, path: str, body):
        if method == "GET":
            return {"tasks": [{"task_id": "t-1", "cell_id": handoff.get("cell_id", "cell_s"), "tier": tier}]}
        if path.endswith("/claim"):
            return {"claimed": True, "gate": {}, "handoff": {"handoff_lease_id": "lease-1", **handoff}}
        posted.append(body)
        return {"gate": {}, "task": {"status": body["phase"]}}

    def _hw(h):
        hw_calls.append(h)
        return {"arm": "arm_s", "events_count": 0, "stop_event": {}}

    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    ctw.poll_and_execute_once(pipe, request_fn=_req, live_act_fn=_hw, prep_dir=tmp_path)
    return hw_calls, posted[0]


@pytest.mark.parametrize(
    "handoff,tier,reason",
    [
        ({"cell_id": "cell_s"}, 1, "AMR_NOT_LOCKED_AT_HANDOFF"),  # interlock keys missing
        ({**LOCKED, "cell_id": "cell_s", "wheel_brake_locked": False}, 1, "AMR_NOT_LOCKED_AT_HANDOFF"),
        ({**LOCKED, "cell_id": "cell_s", "v_cmd_mps": float("nan")}, 1, "AMR_NOT_LOCKED_AT_HANDOFF"),
        ({**LOCKED, "cell_id": "cell_s", "dst_site": "bellt"}, 1, "UNKNOWN_SITE"),
        ({**LOCKED, "cell_id": "cell_ab"}, 4, "UNKNOWN_SITE"),
    ],
)
def test_refused_handoff_never_calls_the_arm(tmp_path: Path, handoff: dict, tier: int, reason: str) -> None:
    hw_calls, body = _run(tmp_path, handoff, tier)
    assert hw_calls == []
    assert body["phase"] == "ABORTED" and body["reason"] == reason
    assert body["hardware_telemetry"] is None


def test_locked_handoff_receipt_is_marked_model_only(tmp_path: Path) -> None:
    hw_calls, body = _run(tmp_path, {**LOCKED, "cell_id": "cell_s"})
    assert len(hw_calls) == 1
    assert body["receipt"]["execution"] == "model_only"


def test_pipeline_refuses_unknown_site_and_tier(tmp_path: Path) -> None:
    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    with pytest.raises(ValueError, match="unknown site"):
        pipe.run_fleet_stage(arm_id="arm_s", src_site="pinky", dst_site="bellt")
    with pytest.raises(ValueError, match="tier"):
        pipe.prestage_cell_ab_handover(tier=4)
