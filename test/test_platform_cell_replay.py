import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from core_common.protocol.schemas import FleetActionGrant
from fleet.server.mission_dispatcher import MissionDispatcher
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.task_store import FleetTaskStore


FIXTURES = Path(__file__).parent / "fixtures" / "platform_cell_replay"
ROOT = Path(__file__).resolve().parents[1]
OMX_ADAPTER = ROOT / "src" / "products" / "omx" / "adapter"
if str(OMX_ADAPTER) not in sys.path:
    sys.path.insert(0, str(OMX_ADAPTER))

from omx_adapter.action_store import ActionStore  # noqa: E402


def _plan():
    source = {
        "object_id": "block-1", "observation_id": "obs-1",
        "frame_sha256": "a" * 64, "camera_identity": "camera-top",
        "optical_frame_id": "camera_top_optical", "calibration_revision": "cal-1",
        "transform_revision": "tf-1", "capture_time_ns": 1780000000000000000,
        "selector_kind": "point", "image_bbox_xyxy": [1, 2, 3, 4],
    }
    return {
        "source_object_id": "block-1", "destination_object_id": "tray-1",
        "source_evidence": source,
        "destination_evidence": {**source, "object_id": "tray-1"},
        "observation_id": "obs-1", "capability_revision": "pick-place-v1",
        "config_revision": "cfg-1", "observation_revision": "obs-1",
    }


def _ready_mission(path):
    task_store = FleetTaskStore(path)
    control = task_store.dispatch_control()
    generation = task_store.rearm_dispatch(
        expected_generation=control["generation"], actor_id="operator-1",
    )["generation"]
    service = MissionService(MissionStore(path))
    created = service.propose(
        mission_id="mission-1", principal_id="operator-1", request_key="request-1",
        workcell_id="omx-1", instance_id="omx-1-control", action_kind="PICK_PLACE",
        plan=_plan(),
        goal_predicate={"predicate_id": "block-in-tray",
                        "condition": "object_in_destination", "object_id": "block-1",
                        "destination_id": "tray-1", "evidence_source": "camera_observation"},
    )
    service.admit("mission-1", actor_id="operator-1", expected_generation=generation,
                  resources=[("workcell", "omx-1"), ("object", "block-1"),
                             ("object", "tray-1")])
    return task_store, service, created["mission"]


def _receipt(grant, *, state, journal_event_id):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "mission_id": grant.mission_id, "step_id": grant.step_id,
        "action_id": grant.action_id, "attempt_id": grant.attempt_id,
        "workcell_id": grant.workcell_id, "instance_id": grant.instance_id,
        "request_digest": grant.request_digest,
        "authority_epoch": grant.authority_epoch,
        "dispatch_generation": grant.dispatch_generation,
        "state": state, "journal_event_id": journal_event_id,
        "observed_at": now, "driver_goal_id": "ros-goal-1", "reason": None,
        "phase_summaries": [
            {"phase_id": phase, "ordinal": ordinal, "state": "SUCCEEDED",
             "journal_event_id": ordinal + 1, "observed_at": now}
            for ordinal, phase in enumerate(("approach", "grasp", "transfer", "release"))
        ],
    }


class LostSubmitReceiptTransport:
    def __init__(self, action_path):
        self.action_path = action_path
        self.action_store = ActionStore(action_path)
        self.grant = None
        self.submissions = []
        self.lookups = []

    def submit(self, grant):
        self.grant = FleetActionGrant.model_validate(grant)
        self.submissions.append(self.grant)
        created = self.action_store.create_action(
            workcell_id=grant.workcell_id, instance_id=grant.instance_id,
            principal_id="operator-1", request_key=grant.attempt_id,
            action_id=grant.action_id, action_kind=grant.action_kind,
            configuration_revision=grant.config_revision,
            observation_id=grant.source_evidence.observation_id,
            owner_generation=grant.dispatch_generation,
            payload={"request_digest": grant.request_digest},
        )
        assert created["created"] is True
        attempt = self.action_store.begin_submission(
            grant.action_id, expected_generation=grant.dispatch_generation,
            attempt_id=grant.attempt_id,
        )
        self.action_store.record_submission(
            grant.action_id, attempt["attempt_id"], accepted=True,
            driver_goal_id="ros-goal-1",
        )
        self.action_store.record_terminal(
            grant.action_id, attempt["attempt_id"], driver_goal_id="ros-goal-1",
            outcome="SUCCEEDED", result_source="driver-result",
            result_observed_at=datetime.now(timezone.utc).isoformat(),
            result={"controller": "SUCCEEDED"},
        )
        raise TimeoutError("local acceptance and completion outlived the lost receipt")

    def get(self, grant):
        self.lookups.append((grant.action_id, grant.attempt_id))
        assert self.grant == grant
        self.action_store = ActionStore(self.action_path)
        local_action = self.action_store.get_action(grant.action_id)
        assert local_action["state"] == "SUCCEEDED"
        return _receipt(grant, state=local_action["state"], journal_event_id=8)


def test_late_success_after_site_restart_keeps_unknown_mission_held(tmp_path):
    scenario = json.loads((FIXTURES / "late-success-after-restart.json").read_text(
        encoding="utf-8"))
    path = tmp_path / "fleet.sqlite3"
    task_store, service, mission = _ready_mission(path)
    action_path = tmp_path / "omx.sqlite3"
    transport = LostSubmitReceiptTransport(action_path)
    initial = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    ).dispatch_next()
    original_grant = service.get(mission["mission_id"])["action_grant"]

    # Reopen both Fleet stores to exercise SQLite recovery, then reconcile the
    # same persisted attempt after the site process has restarted.
    restarted_tasks = FleetTaskStore(path)
    restarted_service = MissionService(MissionStore(path))
    reconciled = MissionDispatcher(
        restarted_service, restarted_tasks, transport, {"omx-1": "omx-1-control"},
    ).dispatch_next()
    current = restarted_service.get(mission["mission_id"])

    assert initial["state"] == "UNKNOWN"
    assert reconciled["attempt_id"] == original_grant["attempt_id"]
    assert reconciled["state"] == scenario["expected"]["mission_state"]
    assert current["status"] == scenario["expected"]["mission_state"]
    assert current["reason"] == "LATE_SUCCESS_REQUIRES_INDEPENDENT_GOAL_EVIDENCE"
    assert len(transport.submissions) == scenario["expected"]["automatic_resubmit_count"] + 1
    assert transport.lookups == [(original_grant["action_id"], original_grant["attempt_id"])]
    assert transport.action_store.get_action(original_grant["action_id"])["state"] == "SUCCEEDED"
    assert restarted_tasks.resource_claims(resource_kind="object", resource_id="block-1")

    goal_time = time.time() + 1.0
    confirmed = MissionService(
        MissionStore(path), goal_evidence_verifier=lambda _mission, _evidence: True,
    ).confirm_goal(
        mission["mission_id"], event_id="independent-goal-frame-2", evidence={
            "predicate_id": "block-in-tray", "object_id": "block-1",
            "destination_id": "tray-1", "evidence_source": "camera_observation",
            "evidence_id": "camera:frame-2", "evidence_revision": "cal-1/tf-1",
            "producer_id": "camera-evaluator-1", "observation_id": "obs-post-2",
            "observation_digest": "c" * 64, "evaluator_revision": "object-in-tray-v1",
            "action_id": original_grant["action_id"],
            "attempt_id": original_grant["attempt_id"],
            "gripper_state": "OPEN", "gripper_evidence_id": "gripper-readback-2",
            "gripper_evidence_revision": "gripper-v1",
            "gripper_observed_at": goal_time, "observed_at": goal_time, "satisfied": True,
        }, now=goal_time + 0.1, max_age_s=0.5,
    )
    assert confirmed["status"] == "GOAL_CONFIRMED"
    assert restarted_tasks.resource_claims(resource_kind="object", resource_id="block-1") == []
