from datetime import datetime, timedelta, timezone

import pytest

from core_common.protocol.schemas import FleetActionGrant
from omx_adapter.action_api import ActionApi, action_grant_digest
from omx_adapter.action_runner import ActionRunner, DriverSubmission
from omx_adapter.action_store import ActionStore, InvalidActionTransition
from omx_adapter.local_stop import LocalStopController


def _grant(**changes):
    now = datetime.now(timezone.utc)
    source = {
        "object_id": "block-1", "observation_id": "obs-1",
        "frame_sha256": "b" * 64, "camera_identity": "cam-1",
        "optical_frame_id": "cam_optical", "calibration_revision": "cal-1",
        "transform_revision": "tf-1", "capture_time_ns": 1760000000000000000,
        "selector_kind": "point", "image_bbox_xyxy": [1, 2, 3, 4],
    }
    value = {
        "mission_id": "mission-1", "step_id": "step-1",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "request_digest": "0" * 64, "workcell_id": "omx-1",
        "instance_id": "omx-1-control", "action_kind": "PICK_PLACE",
        "source_evidence": source,
        "destination_evidence": {**source, "object_id": "tray-1"},
        "capability_revision": "pick-place-v1", "config_revision": "cfg-1",
        "observation_revision": "obs-1", "authority_epoch": 2,
        "dispatch_generation": 8, "issued_at": now,
        "expires_at": now + timedelta(seconds=15),
    }
    value.update(changes)
    value["request_digest"] = action_grant_digest(value)
    return value


class FakeDriver:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.submissions = []
        self.cancellations = []

    def submit(self, grant):
        self.submissions.append(grant.action_id)
        if self.fail:
            raise TimeoutError("acceptance timed out")
        return DriverSubmission(accepted=True, driver_goal_id="driver-goal-1")

    def cancel(self, action):
        self.cancellations.append(action["attempt_id"])
        return True


def _runner(tmp_path, driver=None):
    db = tmp_path / "actions.sqlite3"
    store = ActionStore(db)
    driver = driver or FakeDriver()
    stop = LocalStopController(db, workcell_id="omx-1", instance_id="omx-1-control")
    stop.rearm(authority_epoch=2, dispatch_generation=8, operator_confirmed=True,
               fleet_fence_current=lambda epoch, generation: (epoch, generation) == (2, 8))
    runner = ActionRunner(
        store, driver, workcell_id="omx-1", instance_id="omx-1-control",
        principal_for_peer=lambda uid: f"fleet-uid-{uid}", allowed_peer_uids={1001},
        current_fence=lambda epoch, generation: (epoch, generation) == (2, 8),
        capability_current=lambda grant: grant.config_revision == "cfg-1",
        submission_fence=stop,
        enabled=True,
    )
    runner.local_stop = stop
    return store, driver, runner


def test_submit_persists_fleet_ids_and_duplicate_never_replays(tmp_path):
    store, driver, runner = _runner(tmp_path)
    grant = FleetActionGrant.model_validate(_grant())

    first = runner.submit(grant, peer_uid=1001)
    duplicate = runner.submit(grant, peer_uid=1001)

    assert first["state"] == "ACCEPTED"
    assert first["action_id"] == grant.action_id
    assert first["attempt_id"] == grant.attempt_id
    assert first["mission_id"] == grant.mission_id
    assert first["step_id"] == grant.step_id
    assert first["request_digest"] == grant.request_digest
    assert first["authority_epoch"] == grant.authority_epoch
    assert first["dispatch_generation"] == grant.dispatch_generation
    assert first["journal_event_id"] >= 1
    assert duplicate["action_id"] == grant.action_id
    assert duplicate["created"] is False
    assert driver.submissions == [grant.action_id]
    assert store.history(grant.action_id)[-1]["state"] == "ACCEPTED"


def test_expired_or_stale_grant_is_rejected_before_journal_or_driver(tmp_path):
    store, driver, runner = _runner(tmp_path)
    stale = FleetActionGrant.model_validate(_grant(dispatch_generation=7))

    with pytest.raises(PermissionError, match="generation"):
        runner.submit(stale, peer_uid=1001)
    with pytest.raises(PermissionError, match="peer"):
        runner.submit(FleetActionGrant.model_validate(
            _grant(action_id="action-2", attempt_id="attempt-2")),
                      peer_uid=9)

    assert driver.submissions == []
    assert store.get_action("action-1") is None


def test_unknown_submission_is_durable_and_retry_does_not_resend(tmp_path):
    store, driver, runner = _runner(tmp_path, FakeDriver(fail=True))
    grant = FleetActionGrant.model_validate(_grant())

    result = runner.submit(grant, peer_uid=1001)
    retry = runner.submit(grant, peer_uid=1001)

    assert result["state"] == retry["state"] == "UNKNOWN"
    assert driver.submissions == [grant.action_id]
    assert store.unresolved_actions()[0]["attempt_id"] == grant.attempt_id


def test_prepared_intent_can_resume_but_submitting_intent_cannot_replay(tmp_path):
    store, driver, runner = _runner(tmp_path)
    grant = FleetActionGrant.model_validate(_grant())
    payload = grant.model_dump(mode="json")
    store.create_action(
        workcell_id=grant.workcell_id, instance_id=grant.instance_id,
        principal_id="fleet-uid-1001", request_key=grant.action_id,
        action_id=grant.action_id, action_kind=grant.action_kind,
        configuration_revision=grant.config_revision,
        observation_id=grant.observation_revision,
        owner_generation=grant.dispatch_generation, payload=payload,
    )

    resumed = runner.submit(grant, peer_uid=1001)
    assert resumed["state"] == "ACCEPTED"
    assert driver.submissions == [grant.action_id]

    second = FleetActionGrant.model_validate(
        _grant(action_id="action-2", attempt_id="attempt-2"))
    intent = store.create_action(
        workcell_id=second.workcell_id, instance_id=second.instance_id,
        principal_id="fleet-uid-1001", request_key=second.action_id,
        action_id=second.action_id, action_kind=second.action_kind,
        configuration_revision=second.config_revision,
        observation_id=second.observation_revision,
        owner_generation=second.dispatch_generation,
        payload=second.model_dump(mode="json"),
    )["action"]
    store.begin_submission(second.action_id,
                           expected_generation=second.dispatch_generation,
                           attempt_id=second.attempt_id)

    unresolved = runner.submit(second, peer_uid=1001)
    assert intent["state"] == "PREPARED"
    assert unresolved["state"] == "SUBMITTING"
    assert driver.submissions == [grant.action_id]


def test_cancel_ack_is_not_terminal_completion_or_stop_proof(tmp_path):
    store, driver, runner = _runner(tmp_path)
    grant = FleetActionGrant.model_validate(_grant())
    submitted = runner.submit(grant, peer_uid=1001)

    canceled = runner.cancel(grant.action_id, grant.attempt_id, peer_uid=1001)

    assert submitted["state"] == "ACCEPTED"
    assert canceled["state"] == "CANCEL_REQUESTED"
    assert store.get_action(grant.action_id)["cancel_acknowledged"] is True
    assert driver.cancellations == [grant.attempt_id]
    assert store.unresolved_actions()[0]["action_id"] == grant.action_id


def test_driver_terminal_state_is_attempt_scoped_and_not_mission_completion(tmp_path):
    store, _, runner = _runner(tmp_path)
    grant = FleetActionGrant.model_validate(_grant())
    runner.submit(grant, peer_uid=1001)
    running = runner.record_running(
        grant.action_id, grant.attempt_id, driver_goal_id="driver-goal-1",
        peer_uid=1001,
    )
    terminal = runner.record_terminal(
        grant.action_id, grant.attempt_id, driver_goal_id="driver-goal-1",
        outcome="SUCCEEDED", result_source="driver-readback",
        result_observed_at=datetime.now(timezone.utc).isoformat(),
        result={"controller_result": "success"}, peer_uid=1001,
    )

    assert running["state"] == "RUNNING"
    assert terminal["state"] == "SUCCEEDED"
    assert store.get_action(grant.action_id)["state"] == "SUCCEEDED"
    with pytest.raises(InvalidActionTransition, match="attempt"):
        runner.record_terminal(
            grant.action_id, "stale-attempt", driver_goal_id="driver-goal-1",
            outcome="SUCCEEDED", result_source="driver-readback",
            result_observed_at=datetime.now(timezone.utc).isoformat(),
            result={}, peer_uid=1001,
        )


def test_disabled_runner_rejects_before_action_record_or_driver_io(tmp_path):
    store = ActionStore(tmp_path / "actions.sqlite3")
    driver = FakeDriver()
    runner = ActionRunner(
        store, driver, workcell_id="omx-1", instance_id="omx-1-control",
        principal_for_peer=lambda uid: f"fleet-uid-{uid}", allowed_peer_uids={1001},
        current_fence=lambda epoch, generation: True,
        capability_current=lambda grant: True,
    )
    grant = FleetActionGrant.model_validate(_grant())

    with pytest.raises(PermissionError, match="disabled"):
        runner.submit(grant, peer_uid=1001)

    assert store.get_action(grant.action_id) is None
    assert driver.submissions == []


def test_uds_dispatch_checks_peer_and_bounds_frame(tmp_path):
    _, _, runner = _runner(tmp_path)
    api = ActionApi(runner)
    grant = FleetActionGrant.model_validate(_grant()).model_dump(mode="json")
    payload = {"version": 1, "operation": "SubmitAction", "grant": grant}

    denied = api.dispatch(payload, peer_uid=9)
    accepted = api.dispatch(payload, peer_uid=1001)
    oversized = api.dispatch({"version": 1, "operation": "GetAction",
                              "action_id": "x" * 70000}, peer_uid=1001)

    assert denied["error"]["code"] == "PEER_NOT_ALLOWED"
    assert accepted["receipt"]["state"] == "ACCEPTED", accepted
    assert oversized["error"]["code"] == "FRAME_TOO_LARGE"
    assert api.dispatch({"version": 1, "operation": "StopLocal"},
                        peer_uid=1001)["error"]["code"] == "STOP_API_NOT_CONFIGURED"
