from datetime import datetime, timezone

import pytest

from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.task_store import FleetTaskStore
from core_common.protocol.schemas import FleetActionGrant

from fleet.server.mission_dispatcher import MissionDispatcher
from fleet.server.local_action_transport import (
    LocalActionRejected, LocalActionUnavailable, UnixLocalActionTransport,
)


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


class Transport:
    def __init__(self, *, fail_submit=False, missing_on_get=False):
        self.fail_submit = fail_submit
        self.missing_on_get = missing_on_get
        self.submissions = []
        self.lookups = []

    def submit(self, grant):
        parsed = FleetActionGrant.model_validate(grant)
        self.submissions.append(parsed)
        if self.fail_submit:
            raise TimeoutError("acceptance receipt was lost")
        return {"state": "ACCEPTED", "receipt": _receipt(parsed, "ACCEPTED", 1)}

    def get(self, grant):
        self.lookups.append((grant.workcell_id, grant.instance_id,
                             grant.action_id, grant.attempt_id))
        if self.missing_on_get:
            return None
        grant = self.submissions[-1]
        return {"state": "RUNNING", "receipt": _receipt(grant, "RUNNING", 2)}


def _receipt(grant, state, event_id):
    return {
        "mission_id": grant.mission_id, "step_id": grant.step_id,
        "action_id": grant.action_id, "attempt_id": grant.attempt_id,
        "workcell_id": grant.workcell_id, "instance_id": grant.instance_id,
        "request_digest": grant.request_digest,
        "authority_epoch": grant.authority_epoch,
        "dispatch_generation": grant.dispatch_generation,
        "state": state, "journal_event_id": event_id,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "driver_goal_id": "ros-goal-1" if state in {"ACCEPTED", "RUNNING"} else None,
        "reason": None,
        "phase_summaries": [],
    }


def _ready_mission(tmp_path, *, dispatch_enabled=True):
    path = tmp_path / "fleet.sqlite3"
    task_store = FleetTaskStore(path)
    control = task_store.dispatch_control()
    generation = control["generation"]
    if dispatch_enabled:
        generation = task_store.rearm_dispatch(
            expected_generation=generation, actor_id="operator-1",
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
    return task_store, service, created["mission"], generation


def test_admitted_mission_dispatches_one_fenced_action_and_readback_never_resubmits(tmp_path):
    task_store, service, mission, generation = _ready_mission(tmp_path)
    now = datetime.now(timezone.utc)
    transport = Transport()
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
        now=lambda: now,
    )

    accepted = dispatcher.dispatch_next()
    reconciled = dispatcher.dispatch_next()

    assert len(transport.submissions) == 1
    assert len(transport.lookups) == 1
    grant = transport.submissions[0]
    assert grant.mission_id == mission["mission_id"]
    assert grant.step_id == mission["step_id"]
    assert grant.authority_epoch == task_store.dispatch_control()["authority_epoch"]
    assert grant.dispatch_generation == generation
    assert grant.issued_at == now and grant.expires_at > now
    assert accepted["state"] == "ACCEPTED"
    assert reconciled["state"] == "RUNNING"
    assert service.get(mission["mission_id"])["status"] == "RUNNING"


def test_unknown_submit_is_held_and_reconciled_without_automatic_replay(tmp_path):
    task_store, service, mission, _ = _ready_mission(tmp_path)
    transport = Transport(fail_submit=True, missing_on_get=True)
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    )

    uncertain = dispatcher.dispatch_next()
    reconciled = dispatcher.dispatch_next()

    assert uncertain["state"] == "UNKNOWN"
    assert reconciled["state"] == "HOLD"
    assert len(transport.submissions) == 1
    assert len(transport.lookups) == 1
    assert service.get(mission["mission_id"])["status"] == "HOLD"
    assert service.get(mission["mission_id"])["reconciliation_pending"] == 0
    assert task_store.resource_claims(resource_kind="object", resource_id="block-1")


def test_running_mission_after_process_restart_uses_persisted_grant_for_readback(tmp_path):
    task_store, service, mission, _ = _ready_mission(tmp_path)
    transport = Transport()
    first = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    )
    first.dispatch_next()
    persisted = service.get(mission["mission_id"])
    assert persisted["action_grant"]["request_digest"] == transport.submissions[0].request_digest

    restarted_transport = Transport()
    restarted_transport.submissions = transport.submissions
    restarted = MissionDispatcher(
        service, task_store, restarted_transport, {"omx-1": "omx-1-control"},
    )
    result = restarted.dispatch_next()

    assert result["state"] == "RUNNING"
    assert restarted_transport.submissions == transport.submissions
    assert len(restarted_transport.lookups) == 1


def test_closed_generation_prevents_any_local_submit(tmp_path):
    task_store, service, mission, _ = _ready_mission(tmp_path)
    transport = Transport()
    task_store.trip_stop_latch(actor_id="operator-1")
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    )

    result = dispatcher.dispatch_next()

    assert result["state"] == "HOLD"
    assert transport.submissions == []
    assert service.get(mission["mission_id"])["status"] == "HOLD"


def test_local_transport_requires_v2_phase_summary_and_exact_fence_bound_receipt(tmp_path):
    task_store, service, mission, _ = _ready_mission(tmp_path)
    transport = Transport()
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    )
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    receipt = _receipt(grant, "ACCEPTED", 9)
    parser = UnixLocalActionTransport(tmp_path)

    parsed = parser._parse_receipt(grant, {"version": 2, "status": 200, "receipt": receipt})
    assert parsed.request_digest == grant.request_digest
    missing_summary = {key: value for key, value in receipt.items() if key != "phase_summaries"}
    with pytest.raises(LocalActionUnavailable, match="version"):
        parser._parse_receipt(grant, {"version": 1, "status": 200, "receipt": receipt})
    with pytest.raises(LocalActionUnavailable, match="missing phase summaries"):
        parser._parse_receipt(grant, {"version": 2, "status": 200, "receipt": missing_summary})
    wrong_fence = {**receipt, "dispatch_generation": grant.dispatch_generation + 1}
    with pytest.raises(LocalActionUnavailable, match="does not match"):
        parser._parse_receipt(grant, {"version": 2, "status": 200, "receipt": wrong_fence})


def test_duplicate_terminal_receipt_and_late_running_readback_do_not_regress_mission(tmp_path):
    task_store, service, mission, _ = _ready_mission(tmp_path)
    transport = Transport()
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    )
    dispatcher.dispatch_next()
    grant = FleetActionGrant.model_validate(service.get(mission["mission_id"])["action_grant"])
    terminal_document = _receipt(grant, "SUCCEEDED", 7)
    observed_at = datetime.now(timezone.utc).isoformat()
    terminal_document["phase_summaries"] = [
        {"phase_id": phase_id, "ordinal": ordinal, "state": "SUCCEEDED",
         "journal_event_id": ordinal + 1, "observed_at": observed_at}
        for ordinal, phase_id in enumerate(("approach", "grasp", "transfer", "release"))
    ]
    terminal = dispatcher._verified_receipt(grant, terminal_document)
    stale_running = dispatcher._verified_receipt(grant, _receipt(grant, "RUNNING", 2))

    dispatcher._apply_receipt(grant, terminal)
    duplicate = dispatcher._apply_receipt(grant, terminal)
    stale = dispatcher._apply_receipt(grant, stale_running)

    history = service.history(mission["mission_id"])
    device_results = [event for event in history if event["event_source"] == "device_action"]
    assert duplicate["state"] == "ACTION_SUCCEEDED"
    assert stale["state"] == "RUNNING"  # Readback is advisory and does not mutate Fleet.
    assert service.get(mission["mission_id"])["status"] == "ACTION_SUCCEEDED"
    assert len(device_results) == 1


def test_explicit_local_4xx_refusal_is_failed_without_automatic_retry(tmp_path):
    task_store, service, mission, _ = _ready_mission(tmp_path)

    class RejectingTransport(Transport):
        def submit(self, grant):
            self.submissions.append(FleetActionGrant.model_validate(grant))
            raise LocalActionRejected("ACTION_SCOPE_MISMATCH: rejected before acceptance")

    transport = RejectingTransport()
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    )

    result = dispatcher.dispatch_next()
    retried = dispatcher.dispatch_next()
    current = service.get(mission["mission_id"])

    assert result["state"] == "HOLD"
    assert current["reason"] == "ACTION_FAILED"
    assert current["reconciliation_pending"] == 0
    assert retried is None
    assert len(transport.submissions) == 1
