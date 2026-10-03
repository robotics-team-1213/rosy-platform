import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core_common.protocol.schemas import FleetActionGrant
from fleet.server.mission_dispatcher import MissionDispatcher
from fleet.server.goal_evidence import GoalEvidenceError
from fleet.server.goal_evidence_registry import GoalEvidenceProducer, GoalEvidenceRegistry
from fleet.server.goal_evidence_service import GoalEvidenceService
from fleet.server.goal_evidence_store import GoalEvidenceStore
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionConflict, MissionStore
from fleet.server.task_store import FleetTaskStore, InvalidTaskTransition


FIXTURES = Path(__file__).parent / "fixtures" / "platform_cell_replay"
ROOT = Path(__file__).resolve().parents[1]
OMX_ADAPTER = ROOT / "middleware" / "apps" / "device" / "omx" / "adapter"
if str(OMX_ADAPTER) not in sys.path:
    sys.path.insert(0, str(OMX_ADAPTER))

from omx_adapter.action_store import ActionConflict, ActionStore  # noqa: E402


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


def _post_action_goal_evidence(grant, observed, *, satisfied):
    return {
        "predicate_id": "block-in-tray", "object_id": "block-1", "destination_id": "tray-1",
        "evidence_source": "camera_observation", "evidence_id": "camera:normal-post-1",
        "evidence_revision": "cal-1/tf-1", "producer_id": "camera-evaluator-1",
        "observation_id": "normal-post-1", "observation_digest": "d" * 64,
        "evaluator_revision": "object-in-tray-v1", "action_id": grant.action_id,
        "attempt_id": grant.attempt_id, "gripper_state": "OPEN",
        "gripper_evidence_id": "gripper-normal-1", "gripper_evidence_revision": "gripper-v1",
        "gripper_observed_at": observed, "observed_at": observed, "satisfied": satisfied,
    }


class LostSubmitReceiptTransport:
    def __init__(self, action_path, *, lose_submit_receipt=True):
        self.action_path = action_path
        self.action_store = ActionStore(action_path)
        self.grant = None
        self.submissions = []
        self.lookups = []
        self.lose_submit_receipt = lose_submit_receipt

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
        if self.lose_submit_receipt:
            raise TimeoutError("local acceptance and completion outlived the lost receipt")
        return _receipt(grant, state="SUCCEEDED", journal_event_id=8)

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
    before_reconcile = service.store.mission_events_after(
        mission["mission_id"], after_event_id=0, limit=200,
    )
    unknown_watermark = before_reconcile["snapshot_event_id"]

    # Reopen both Fleet stores to exercise SQLite recovery, then reconcile the
    # same persisted attempt after the site process has restarted.
    restarted_tasks = FleetTaskStore(path)
    restarted_service = MissionService(MissionStore(path))
    reconciled = MissionDispatcher(
        restarted_service, restarted_tasks, transport, {"omx-1": "omx-1-control"},
    ).dispatch_next()
    current = restarted_service.get(mission["mission_id"])
    after_reconcile = restarted_service.store.mission_events_after(
        mission["mission_id"], after_event_id=unknown_watermark, limit=200,
    )

    assert initial["state"] == "UNKNOWN"
    assert reconciled["attempt_id"] == original_grant["attempt_id"]
    assert reconciled["state"] == scenario["expected"]["mission_state"]
    assert current["status"] == scenario["expected"]["mission_state"]
    assert current["reason"] == "LATE_SUCCESS_REQUIRES_INDEPENDENT_GOAL_EVIDENCE"
    assert len(transport.submissions) == scenario["expected"]["automatic_resubmit_count"] + 1
    assert transport.lookups == [(original_grant["action_id"], original_grant["attempt_id"])]
    assert transport.action_store.get_action(original_grant["action_id"])["state"] == "SUCCEEDED"
    assert after_reconcile["snapshot_event_id"] > unknown_watermark
    assert [event["event_type"] for event in after_reconcile["events"]] == [
        "ACTION_PHASE_SNAPSHOT", "ACTION_PHASE_SNAPSHOT", "ACTION_PHASE_SNAPSHOT",
        "ACTION_PHASE_SNAPSHOT", "ACTION_TERMINAL_RESULT",
    ]
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
    after_goal = restarted_service.store.mission_events_after(
        mission["mission_id"], after_event_id=after_reconcile["snapshot_event_id"], limit=200,
    )
    assert after_goal["snapshot_event_id"] > after_reconcile["snapshot_event_id"]
    assert [event["event_type"] for event in after_goal["events"]] == [
        "GOAL_PREDICATE_CONFIRMED",
    ]


def test_expired_grant_does_not_release_running_action_claim_after_restart(tmp_path):
    scenario = json.loads((FIXTURES / "expired-grant-running-action.json").read_text(
        encoding="utf-8"))
    path = tmp_path / "fleet.sqlite3"
    task_store, service, mission = _ready_mission(path)
    action_path = tmp_path / "omx.sqlite3"
    action_store = ActionStore(action_path)
    now = datetime.now(timezone.utc)

    class LostRunningReceiptTransport:
        def __init__(self):
            self.grant = None
            self.submissions = []
            self.lookups = []

        def submit(self, grant):
            self.grant = FleetActionGrant.model_validate(grant)
            self.submissions.append(self.grant)
            created = action_store.create_action(
                workcell_id=grant.workcell_id, instance_id=grant.instance_id,
                principal_id="operator-1", request_key=grant.attempt_id,
                action_id=grant.action_id, action_kind=grant.action_kind,
                configuration_revision=grant.config_revision,
                observation_id=grant.source_evidence.observation_id,
                owner_generation=grant.dispatch_generation,
                payload={"request_digest": grant.request_digest},
            )
            assert created["created"] is True
            attempt = action_store.begin_submission(
                grant.action_id, expected_generation=grant.dispatch_generation,
                attempt_id=grant.attempt_id,
            )
            action_store.record_submission(
                grant.action_id, attempt["attempt_id"], accepted=True,
                driver_goal_id="ros-goal-running",
            )
            raise TimeoutError("accepted running Action outlived the lost receipt")

        def get(self, grant):
            self.lookups.append((grant.action_id, grant.attempt_id))
            assert grant == self.grant
            assert grant.expires_at < now
            local = ActionStore(action_path).get_action(grant.action_id)
            assert local["state"] == "ACCEPTED"
            receipt = _receipt(grant, state="RUNNING", journal_event_id=2)
            receipt["phase_summaries"] = []
            return receipt

    transport = LostRunningReceiptTransport()
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
        now=lambda: now, grant_ttl_s=1.0,
    )
    initial = dispatcher.dispatch_next()
    original = service.get(mission["mission_id"])["action_grant"]
    assert initial["state"] == "UNKNOWN"
    now = datetime.fromtimestamp(
        datetime.fromisoformat(original["expires_at"].replace("Z", "+00:00")).timestamp() + 1.0,
        tz=timezone.utc,
    )

    restarted_tasks = FleetTaskStore(path)
    restarted_service = MissionService(MissionStore(path))
    result = MissionDispatcher(
        restarted_service, restarted_tasks, transport, {"omx-1": "omx-1-control"},
        now=lambda: now,
    ).dispatch_next()
    current = restarted_service.get(mission["mission_id"])
    claims = restarted_tasks.resource_claims(resource_kind="object", resource_id="block-1")

    assert result["state"] == scenario["expected"]["mission_state"]
    assert current["status"] == "HOLD"
    assert result["reason"] == scenario["expected"]["reason"]
    assert len(transport.submissions) == scenario["expected"]["automatic_resubmit_count"] + 1
    assert len(transport.lookups) == 1
    assert claims and all(
        claim["phase"] == scenario["expected"]["resource_claim_phase"]
        for claim in claims
    )

    conflict = restarted_service.propose(
        mission_id="mission-2", principal_id="operator-1", request_key="request-2",
        workcell_id="omx-1", instance_id="omx-1-control", action_kind="PICK_PLACE",
        plan=_plan(),
        goal_predicate={"predicate_id": "block-in-tray-2",
                        "condition": "object_in_destination", "object_id": "block-1",
                        "destination_id": "tray-1", "evidence_source": "camera_observation"},
    )
    assert conflict["mission"]["status"] == "PROPOSED"
    with pytest.raises(MissionConflict):
        restarted_service.admit(
            "mission-2", actor_id="operator-1",
            expected_generation=restarted_tasks.dispatch_control()["generation"],
            resources=[("workcell", "omx-1"), ("object", "block-1"),
                       ("object", "tray-1")],
        )


class InterruptedOwnerTransport:
    def __init__(self, path, scenario):
        self.store = ActionStore(path)
        self.scenario = scenario
        self.submissions = []
        self.lookups = []
        self.request = None

    def submit(self, grant):
        self.submissions.append(grant)
        self.request = {
            "workcell_id": grant.workcell_id, "instance_id": grant.instance_id,
            "principal_id": "operator-1", "request_key": grant.attempt_id,
            "action_id": grant.action_id, "action_kind": grant.action_kind,
            "configuration_revision": grant.config_revision,
            "observation_id": grant.source_evidence.observation_id,
            "owner_generation": grant.dispatch_generation,
            "payload": {"request_digest": grant.request_digest},
        }
        assert self.store.create_action(**self.request)["created"] is True
        self.store.begin_submission(
            grant.action_id, expected_generation=grant.dispatch_generation,
            attempt_id=grant.attempt_id,
        )
        self.store.record_submission(
            grant.action_id, grant.attempt_id, accepted=True,
            driver_goal_id="driver-goal-interrupted",
        )
        if self.scenario.get("workflow_state"):
            self.store.record_workflow_state(
                grant.action_id, grant.attempt_id,
                workflow_state=self.scenario["workflow_state"],
                object_may_be_held=self.scenario["object_may_be_held_before_restart"],
                evidence_refs={"phase_result_id": "last-local-phase"},
            )
        if self.scenario["cancel_requested"]:
            self.store.request_cancel(grant.action_id, grant.attempt_id)
            self.store.record_cancel_ack(grant.action_id, grant.attempt_id, acknowledged=True)
        action = self.store.get_action(grant.action_id)
        return self._readback(grant, action)

    def _readback(self, grant, action):
        receipt = _receipt(
            grant, state=action["state"],
            journal_event_id=self.store.latest_event_id(grant.action_id),
        )
        receipt["phase_summaries"] = []
        receipt["driver_goal_id"] = action["driver_goal_id"]
        receipt["reason"] = action["reason"]
        return receipt

    def get(self, grant):
        self.lookups.append((grant.action_id, grant.attempt_id))
        assert grant == self.submissions[0]
        return self._readback(grant, self.store.get_action(grant.action_id))


@pytest.mark.parametrize("scenario_name", [
    "accepted-before-owner-restart", "cancel-ack-before-owner-restart",
    "release-command-before-terminal-record",
])
def test_owner_interruption_and_site_fence_keep_physical_ownership(tmp_path, scenario_name):
    scenarios = json.loads((FIXTURES / "owner-interruptions.json").read_text(encoding="utf-8"))
    scenario = scenarios[scenario_name]
    fleet_path = tmp_path / "fleet.sqlite3"
    action_path = tmp_path / "omx.sqlite3"
    tasks, service, mission = _ready_mission(fleet_path)
    transport = InterruptedOwnerTransport(action_path, scenario)
    initial = MissionDispatcher(
        service, tasks, transport, {"omx-1": "omx-1-control"},
    ).dispatch_next()
    grant = transport.submissions[0]
    before = service.store.mission_events_after(mission["mission_id"], after_event_id=0, limit=200)
    assert initial["state"] == scenario["state_before_restart"]

    # Exercise the real owner restart transition, rather than treating reopened
    # Python objects as evidence that the controller or physical object reset.
    transport.store = ActionStore(action_path)
    assert transport.store.recover_after_restart() == [grant.action_id]
    assert transport.store.recover_after_restart() == []
    restarted_tasks = FleetTaskStore(fleet_path)
    control = restarted_tasks.close_dispatch_for_startup()
    restarted_service = MissionService(MissionStore(fleet_path))
    dispatcher = MissionDispatcher(
        restarted_service, restarted_tasks, transport, {"omx-1": "omx-1-control"},
    )
    reconciled = dispatcher.dispatch_next()
    after = restarted_service.store.mission_events_after(
        mission["mission_id"], after_event_id=before["snapshot_event_id"], limit=200,
    )
    assert reconciled["state"] == "UNKNOWN"
    assert restarted_service.get(mission["mission_id"])["status"] == "HOLD"
    assert after["snapshot_event_id"] > before["snapshot_event_id"]
    assert [event["event_type"] for event in after["events"]] == ["ACTION_TERMINAL_RESULT"]
    assert control["authority_epoch"] > grant.authority_epoch
    assert control["generation"] > grant.dispatch_generation
    assert dispatcher.dispatch_next() is None
    assert len(transport.submissions) == 1 and len(transport.lookups) == 1
    for kind, resource in (("workcell", "omx-1"), ("object", "block-1"), ("object", "tray-1")):
        claims = restarted_tasks.resource_claims(resource_kind=kind, resource_id=resource)
        assert len(claims) == 1 and claims[0]["owner_id"] == mission["mission_id"]
    assert restarted_tasks.dispatch_control()["rearm_available"] is False
    with pytest.raises(InvalidTaskTransition, match="unresolved Action"):
        restarted_tasks.rearm_dispatch(expected_generation=control["generation"], actor_id="operator-1")

    local = transport.store.get_action(grant.action_id)
    assert local["state"] == "UNKNOWN" and local["attempt_id"] == grant.attempt_id
    history = transport.store.history(grant.action_id)
    holds = [event for event in history if event["event_type"] == "ACTION_WORKFLOW_STATE"]
    assert holds[-1]["detail"]["workflow_state"] == "HOLD"
    assert holds[-1]["detail"]["object_may_be_held"] == scenario["object_may_be_held_after_restart"]
    assert not any(event["event_type"] == "DRIVER_TERMINAL_RESULT" for event in history)
    assert bool(local["cancel_acknowledged"]) == scenario["cancel_requested"]
    duplicate = transport.store.create_action(**transport.request)
    assert duplicate["created"] is False and duplicate["action"]["attempt_id"] == grant.attempt_id
    with pytest.raises(ActionConflict, match="different Action request"):
        transport.store.create_action(**{**transport.request, "payload": {"request_digest": "f" * 64}})


def test_normal_completion_requires_fresh_nonconflicting_occupancy_evidence(tmp_path):
    scenario = json.loads((FIXTURES / "normal-completion-independent-goal.json").read_text(encoding="utf-8"))
    path = tmp_path / "fleet.sqlite3"
    tasks, service, mission = _ready_mission(path)
    transport = LostSubmitReceiptTransport(tmp_path / "omx.sqlite3", lose_submit_receipt=False)
    result = MissionDispatcher(service, tasks, transport, {"omx-1": "omx-1-control"}).dispatch_next()
    assert result["state"] == scenario["expected"]["after_action"]
    restarted_tasks = FleetTaskStore(path)
    restarted = MissionService(MissionStore(path), goal_evidence_verifier=lambda _mission, _evidence: True)
    grant = transport.grant
    observed = time.time() + 1.0
    evidence = _post_action_goal_evidence(grant, observed, satisfied=False)
    unsatisfied = restarted.confirm_goal(
        mission["mission_id"], event_id="normal-goal-not-satisfied", evidence=evidence,
        now=observed + 0.1, max_age_s=0.5,
    )
    assert unsatisfied["status"] == scenario["expected"]["after_conflicting_observation"]
    assert unsatisfied["reason"] == "GOAL_NOT_SATISFIED"
    with pytest.raises(GoalEvidenceError):
        restarted.confirm_goal(
            mission["mission_id"], event_id="normal-goal-expired",
            evidence={**evidence, "satisfied": True}, now=observed + 10.0, max_age_s=0.5,
        )
    assert restarted_tasks.resource_claims(resource_kind="object", resource_id="block-1")
    final_time = observed + 11.0
    confirmed = restarted.confirm_goal(
        mission["mission_id"], event_id="normal-goal-confirmed",
        evidence={**evidence, "satisfied": True, "observation_id": "normal-post-2",
                  "evidence_id": "camera:normal-post-2", "observed_at": final_time,
                  "gripper_observed_at": final_time, "gripper_evidence_id": "gripper-normal-2"},
        now=final_time + 0.1, max_age_s=0.5,
    )
    assert confirmed["status"] == scenario["expected"]["after_independent_goal"]
    for kind, resource in (("workcell", "omx-1"), ("object", "block-1"), ("object", "tray-1")):
        assert restarted_tasks.resource_claims(resource_kind=kind, resource_id=resource) == []
    events = restarted.store.mission_events_after(mission["mission_id"], after_event_id=0, limit=200)
    assert [event["event_type"] for event in events["events"]][-3:] == [
        "GOAL_PREDICATE_UNSATISFIED", "GOAL_EVIDENCE_REJECTED", "GOAL_PREDICATE_CONFIRMED",
    ]
    assert len(transport.submissions) == 1 and transport.lookups == []


@pytest.mark.parametrize("outcome", ["FAILED", "UNKNOWN", "HOLD"])
def test_hold_reason_cannot_substitute_for_successful_action_evidence(tmp_path, outcome):
    path = tmp_path / "fleet.sqlite3"
    tasks, service, mission = _ready_mission(path)
    transport = InterruptedOwnerTransport(tmp_path / "omx.sqlite3", {
        "workflow_state": None, "cancel_requested": False,
    })
    MissionDispatcher(service, tasks, transport, {"omx-1": "omx-1-control"}).dispatch_next()
    grant = transport.submissions[0]
    service.record_action_result(
        mission["mission_id"], event_id="non-success-result", action_id=grant.action_id,
        attempt_id=grant.attempt_id, outcome=outcome, result={"reason": "test-non-success"},
    )
    service.store.hold_mission(
        mission["mission_id"], actor_id="operator-1", event_id="reason-is-not-proof",
        reason="LATE_SUCCESS_REQUIRES_INDEPENDENT_GOAL_EVIDENCE", evidence={},
    )
    observed = time.time() + 1.0
    verifier = MissionService(MissionStore(path), goal_evidence_verifier=lambda _mission, _evidence: True)
    with pytest.raises(MissionConflict, match="terminal Action success"):
        verifier.confirm_goal(
            mission["mission_id"], event_id="goal-cannot-invent-success",
            evidence=_post_action_goal_evidence(grant, observed, satisfied=True),
            now=observed + 0.1, max_age_s=0.5,
        )
    registered = _registered_goal_service(path, observed)
    result = registered.submit(
        token="fixture-producer-token", mission_id=mission["mission_id"],
        raw_evidence=_post_action_goal_evidence(grant, observed, satisfied=True),
    )
    assert result["state"] == "PENDING_ACTION_TERMINAL"
    assert service.get(mission["mission_id"])["status"] == "HOLD"
    assert tasks.resource_claims(resource_kind="object", resource_id="block-1")


def _registered_goal_service(path, observed):
    producer = GoalEvidenceProducer(
        producer_id="camera-evaluator-1", token="fixture-producer-token", workcell_id="omx-1",
        predicate_id="block-in-tray", object_id="block-1", destination_id="tray-1",
        evidence_source="camera_observation", max_age_s=0.5, grace_s=2.0,
        evaluator_revisions=("object-in-tray-v1",),
        valid_until=datetime.fromtimestamp(observed + 1000, timezone.utc),
    )
    return GoalEvidenceService(
        MissionService(MissionStore(path)), GoalEvidenceRegistry((producer,)), GoalEvidenceStore(path),
        now=lambda: observed + 0.1,
    )


@pytest.mark.parametrize("reason", [
    "GOAL_EVIDENCE_TIMEOUT", "GOAL_EVIDENCE_REJECTED", "LATE_SUCCESS_REQUIRES_INDEPENDENT_GOAL_EVIDENCE",
])
def test_registered_goal_producer_recovers_held_terminal_success(tmp_path, reason):
    path = tmp_path / "fleet.sqlite3"
    tasks, service, mission = _ready_mission(path)
    transport = LostSubmitReceiptTransport(tmp_path / "omx.sqlite3", lose_submit_receipt=False)
    MissionDispatcher(service, tasks, transport, {"omx-1": "omx-1-control"}).dispatch_next()
    service.store.hold_mission(
        mission["mission_id"], actor_id="goal-evaluator", event_id="initial-goal-hold",
        reason=reason, evidence={},
    )
    observed = time.time() + 1.0
    registered = _registered_goal_service(path, observed)
    result = registered.submit(
        token="fixture-producer-token", mission_id=mission["mission_id"],
        raw_evidence=_post_action_goal_evidence(transport.grant, observed, satisfied=True),
    )
    assert result["state"] == "GOAL_CONFIRMED"
    assert tasks.resource_claims(resource_kind="object", resource_id="block-1") == []
