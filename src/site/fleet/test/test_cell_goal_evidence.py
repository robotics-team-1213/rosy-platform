"""C4b G6: a sim_model_pose producer's evidence, judged by Fleet, confirms one ledger step."""

from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
for relative in ("modules/execution/src", "deploy/robot/omx"):
    if str(ROOT / relative) not in sys.path:
        sys.path.insert(0, str(ROOT / relative))

from fleet.server.cell_goal_evidence import CellStepGoalEvidence  # noqa: E402
from fleet.server.cell_job_store import CellJobStore  # noqa: E402
from fleet.server.goal_evidence_registry import load_goal_evidence_registry  # noqa: E402
from rosy.execution.site.item_pose import ItemPoseTolerance  # noqa: E402
from sim_item_pose_producer import SimItemPoseProducer  # noqa: E402

from test_cell_job_store import _create, _grant, _stores  # noqa: E402

TARGET = {"x": 0.4, "y": 0.5, "z": 0.3, "roll": 0.0, "pitch": 0.0, "yaw": 1.57}  # _step place pose


class Poses:
    def __init__(self, pose):
        self.value = dict(pose)

    def pose(self, model_name):
        return self.value


class Gripper:
    state = "OPEN"

    def released(self):
        return self.state, "gripper-readback-7"


def _setup(tmp_path, *, profile_source="sim_model_pose"):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    ready = store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    store.start_step("cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
                     grant=_grant(ready, 0))
    store.record_action_result("cell-mission-1", step_index=0, event_id="device:0", action_id="action-0",
                               attempt_id="attempt-0", outcome="SUCCEEDED", result={})
    config = tmp_path / "producers.yaml"
    config.write_text(yaml.safe_dump({"producers": [{
        "producer_id": "sim-model-pose", "token_env": "SIM_POSE_TOKEN", "workcell_id": "omx_01",
        "predicate_id": "item_at_pose", "object_id": "cell-item", "destination_id": "cell-place",
        "evidence_source": profile_source, "max_age_s": 5.0, "grace_s": 30.0,
        "evaluator_revisions": ["gz-model-pose-v1"], "valid_until": "2099-01-01T00:00:00+00:00",
    }]}), encoding="utf-8")
    registry = load_goal_evidence_registry(config, environ={"SIM_POSE_TOKEN": "sim-secret"},
                                           deployment_profile="simulation")
    document = yaml.safe_load((ROOT / "deploy/robot/omx/sim/item_pose_goal.yaml").read_text(encoding="utf-8"))
    service = CellStepGoalEvidence(store, registry, ItemPoseTolerance.from_mapping(document), now=lambda: 101.0)
    return store, service


def _evidence(pose=TARGET, gripper=None):
    return SimItemPoseProducer("sim-model-pose", Poses(pose), gripper or Gripper(), clock=lambda: 100.0).evidence(
        mission_id="cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
        model_name="block_0")


def test_evidence_at_the_target_confirms_the_step_and_readies_the_next(tmp_path):
    store, service = _setup(tmp_path)
    result = service.submit("sim-secret", _evidence())
    job = store.get("cell-mission-1")
    assert result["satisfied"] is True
    assert [step["status"] for step in job["steps"]] == ["GOAL_CONFIRMED", "READY"]
    recorded = job["steps"][0]["goal_evidence"]
    assert recorded["predicate"]["item_id"] == "cell-mission-1:0"
    assert recorded["predicate"]["tolerance"]["xy_m"] == 0.005


def test_off_target_or_closed_gripper_evidence_does_not_advance(tmp_path):
    store, service = _setup(tmp_path)
    moved = service.submit("sim-secret", _evidence({**TARGET, "x": 0.41}))
    gripper = Gripper()
    gripper.state = "CLOSED"
    held = service.submit("sim-secret", _evidence(gripper=gripper))
    assert moved["satisfied"] is False and "xy" in moved["reasons"]
    assert held["satisfied"] is False and "gripper" in held["reasons"]
    assert store.get("cell-mission-1")["steps"][0]["status"] == "ACTION_SUCCEEDED"


def test_wrong_token_or_attempt_is_refused(tmp_path):
    _, service = _setup(tmp_path)
    with pytest.raises(PermissionError):
        service.submit("other-secret", _evidence())
    stale_attempt = {**_evidence(), "attempt_id": "attempt-old"}
    with pytest.raises(PermissionError):
        service.submit("sim-secret", stale_attempt)
    with pytest.raises(ValueError):
        service.submit("sim-secret", {**_evidence(), "satisfied": True})
