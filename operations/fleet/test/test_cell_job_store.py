from datetime import datetime, timedelta, timezone

import pytest

from fleet.server.cell_job_store import CellJobStore
from fleet.server.step_action_kinds import step_grant_digest as cell_transfer_grant_digest
from fleet.server.mission_store import MissionConflict, MissionStore
from fleet.server.task_store import FleetTaskStore


def _stores(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskStore(path)
    control = tasks.store if hasattr(tasks, "store") else tasks
    before = control.dispatch_control()
    enabled = control.rearm_dispatch(
        expected_generation=before["generation"], actor_id="operator-1",
    )
    return path, control, MissionStore(path), enabled


def _step(index=0):
    return {
        "skill_id": "pallet.transfer",
        "version": "1.0.0",
        "inputs": {
            "item": "box", "pallet_id": "pallet-1", "layer_index": index,
            "home_pose_base": {"x_m": 0.0, "y_m": 0.0, "z_m": 0.4, "yaw_rad": 0.0},
            "source_pose_base": {"x_m": 0.1, "y_m": 0.2, "z_m": 0.3, "yaw_rad": 0.0},
            "destination_pose_base": {"x_m": 0.4, "y_m": 0.5, "z_m": 0.3, "yaw_rad": 1.57},
            "source_approach_z_base_m": 0.5,
            "destination_approach_z_base_m": 0.5,
            "carry_z_base_m": 0.6,
        },
    }


def _submission(step_count=2):
    return {
        "job_id": "e" * 64,
        "workcell_id": "omx_01",
        "instance_id": "omx_01_control",
        "recipe_digest": "a" * 64,
        "cell_digest": "b" * 64,
        "process_artifact_digest": "c" * 64,
        "job": {"steps": list(range(step_count))},
        "steps": [_step(index) for index in range(step_count)],
        "resources": [["workcell", "omx_01"], ["pallet", "pallet-1"]],
        "ledger_markers": [{"after_step_ordinal": step_count, "pallet_id": "pallet-1"}],
    }


def _grant(job, step_index, *, action_id=None, attempt_id=None):
    step = job["steps"][step_index]["step"]["inputs"]
    now = datetime.now(timezone.utc)
    payload = {
        "job_id": job["job_id"], "recipe_sha256": job["recipe_digest"],
        "cell_sha256": job["cell_digest"], "step_index": step_index,
        "item": step["item"], "pallet": step["pallet_id"],
        "layer": step["layer_index"], "frame": "robot_base",
        "home": {"x": 0.0, "y": 0.0, "z": 0.4, "yaw": 0.0},
        "pick": {"x": 0.1, "y": 0.2, "z": 0.3, "yaw": 0.0},
        "place": {"x": 0.4, "y": 0.5, "z": 0.3, "yaw": 1.57},
        "pick_approach_z": 0.5, "place_approach_z": 0.5, "carry_z": 0.6,
    }
    value = {
        "mission_id": job["mission_id"], "step_id": job["steps"][step_index]["step_id"],
        "action_id": action_id or f"action-{step_index}",
        "attempt_id": attempt_id or f"attempt-{step_index}",
        "request_digest": "0" * 64,
        "workcell_id": job["workcell_id"], "instance_id": job["instance_id"],
        "action_kind": "CELL_TRANSFER", "cell_transfer": payload,
        "capability_revision": "cell-transfer-v1", "config_revision": "cell-config-v1",
        "authority_epoch": job["authority_epoch"],
        "dispatch_generation": job["dispatch_generation"],
        "issued_at": now, "expires_at": now + timedelta(seconds=30),
    }
    value["request_digest"] = cell_transfer_grant_digest(value)
    return value


def _create(store):
    return store.create(
        mission_id="cell-mission-1", proposal_principal_id="cell-service",
        request_key="cell-request-1", request_digest="d" * 64,
        submission=_submission(),
    )


def _goal(action_id, attempt_id, evidence_id):
    return {
        "producer_id": "sim-model-pose", "evidence_id": evidence_id,
        "evidence_source": "sim_model_pose", "action_id": action_id,
        "attempt_id": attempt_id, "satisfied": True,
        "gripper_state": "OPEN", "gripper_evidence_id": f"{evidence_id}-gripper",
    }


def test_cell_job_migration_preserves_existing_pick_place_missions(tmp_path):
    path, _, missions, _ = _stores(tmp_path)
    legacy = missions.create_proposal(
        mission_id="legacy-mission", principal_id="operator-1", request_key="legacy-1",
        action_kind="PICK_PLACE", workcell_id="omx_01", instance_id="omx_01_control",
        plan={"observation_id": "obs-1"},
        goal_predicate={
            "predicate_id": "goal-1", "condition": "object_in_destination",
            "object_id": "box-1", "destination_id": "tray-1",
            "evidence_source": "camera_observation",
        },
    )["mission"]

    store = CellJobStore(path)
    assert CellJobStore(path).get("cell-mission-missing") is None
    assert missions.get_mission("legacy-mission") == legacy
    with store._connect() as connection:
        migration = connection.execute(
            "SELECT version FROM fleet_component_migrations WHERE component='cell_jobs'",
        ).fetchone()[0]
    assert migration == 1


def test_cell_job_steps_advance_only_after_matching_goal_confirmation(tmp_path):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    proposed = _create(store)
    assert [step["status"] for step in proposed["steps"]] == ["WAITING", "WAITING"]

    ready = store.admit("cell-mission-1", actor_id="operator-1",
                        expected_generation=enabled["generation"])
    assert ready["status"] == "READY"
    assert [step["status"] for step in ready["steps"]] == ["READY", "WAITING"]
    grant0 = _grant(ready, 0)
    running = store.start_step(
        "cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
        grant=grant0,
    )
    assert running["status"] == "RUNNING"
    assert running["steps"][0]["grant"]["request_digest"] == grant0["request_digest"]
    with pytest.raises(MissionConflict, match="current READY"):
        store.start_step(
            "cell-mission-1", step_index=1, action_id="action-1", attempt_id="attempt-1",
            grant=_grant(running, 1),
        )

    succeeded = store.record_action_result(
        "cell-mission-1", step_index=0, event_id="device-event-0",
        action_id="action-0", attempt_id="attempt-0", outcome="SUCCEEDED",
        result={"journal_event_id": 10},
    )
    assert succeeded["status"] == "ACTION_SUCCEEDED"
    assert [step["status"] for step in succeeded["steps"]] == ["ACTION_SUCCEEDED", "WAITING"]
    assert tasks.resource_claims(resource_kind="pallet", resource_id="pallet-1")

    advanced = store.confirm_step_goal(
        "cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
        evidence=_goal("action-0", "attempt-0", "goal-0"),
    )
    assert advanced["status"] == "READY"
    assert advanced["current_step_index"] == 1
    assert [step["status"] for step in advanced["steps"]] == ["GOAL_CONFIRMED", "READY"]

    grant1 = _grant(advanced, 1)
    store.start_step(
        "cell-mission-1", step_index=1, action_id="action-1", attempt_id="attempt-1",
        grant=grant1,
    )
    store.record_action_result(
        "cell-mission-1", step_index=1, event_id="device-event-1",
        action_id="action-1", attempt_id="attempt-1", outcome="SUCCEEDED",
        result={"journal_event_id": 11},
    )
    complete = store.confirm_step_goal(
        "cell-mission-1", step_index=1, action_id="action-1", attempt_id="attempt-1",
        evidence=_goal("action-1", "attempt-1", "goal-1"),
    )
    assert complete["status"] == "GOAL_CONFIRMED"
    assert [step["status"] for step in complete["steps"]] == [
        "GOAL_CONFIRMED", "GOAL_CONFIRMED",
    ]
    assert tasks.resource_claims(resource_kind="pallet", resource_id="pallet-1") == []


def test_unknown_cell_action_survives_restart_as_hold_without_replay(tmp_path):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1",
                expected_generation=enabled["generation"])
    mission = store.get("cell-mission-1")
    store.start_step(
        "cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
        grant=_grant(mission, 0),
    )
    held = store.record_action_result(
        "cell-mission-1", step_index=0, event_id="timeout-event",
        action_id="action-0", attempt_id="attempt-0", outcome="UNKNOWN",
        reason="LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN", result={"transport": "timeout"},
    )

    restarted = CellJobStore(path).get("cell-mission-1")
    assert held["status"] == restarted["status"] == "HOLD"
    assert restarted["steps"][0]["grant"]["action_id"] == "action-0"
    assert restarted["steps"][0]["status"] == "HOLD"
    assert restarted["steps"][1]["status"] == "WAITING"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")


@pytest.mark.parametrize("prior_state", ["READY", "RUNNING", "ACTION_SUCCEEDED"])
def test_cell_job_startup_fences_old_authority_without_replaying_steps(tmp_path, prior_state):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    ready = store.admit("cell-mission-1", actor_id="operator-1",
                        expected_generation=enabled["generation"])
    grant = _grant(ready, 0)
    if prior_state != "READY":
        store.start_step("cell-mission-1", step_index=0, action_id="action-0",
                         attempt_id="attempt-0", grant=grant)
    if prior_state == "ACTION_SUCCEEDED":
        store.record_action_result(
            "cell-mission-1", step_index=0, event_id="success-before-site-restart",
            action_id="action-0", attempt_id="attempt-0", outcome="SUCCEEDED",
            result={"journal_event_id": 10},
        )
    previous = store.get("cell-mission-1")
    assert store.recover_after_startup() == 0
    control = tasks.close_dispatch_for_startup()
    restarted = CellJobStore(path)
    assert restarted.recover_after_startup() == 1
    assert restarted.recover_after_startup() == 0
    held = restarted.get("cell-mission-1")
    assert held["status"] == held["steps"][0]["status"] == "HOLD"
    assert held["reason"] == "SITE_AUTHORITY_CHANGED"
    assert held["steps"][1]["status"] == "WAITING"
    for field in ("action_id", "attempt_id", "grant", "result"):
        assert held["steps"][0][field] == previous["steps"][0][field]
    if prior_state != "READY":
        assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
    # An in-flight Action (DISPATCHING) blocks rearm; held claims do not (D-403 보강 2026-10-03).
    assert control["rearm_available"] is (prior_state != "RUNNING")
    with pytest.raises(MissionConflict, match="current READY"):
        restarted.start_step("cell-mission-1", step_index=0, action_id="another-action",
                             attempt_id="another-attempt", grant=grant)


def test_cell_step_cannot_start_without_every_admitted_resource_claim(tmp_path):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    ready = store.admit("cell-mission-1", actor_id="operator-1",
                        expected_generation=enabled["generation"])
    with store._connect() as connection:
        connection.execute("DELETE FROM fleet_action_claims WHERE resource_key='pallet:pallet-1'")
        connection.commit()
    # C4b 1b A4: a missing claim holds the Job before anything is sent, and releases the rest (A5).
    held = store.start_step("cell-mission-1", step_index=0, action_id="action-0",
                            attempt_id="attempt-0", grant=_grant(ready, 0))
    assert held["status"] == held["steps"][0]["status"] == "HOLD"
    assert held["reason"] == "FLEET_CLAIM_MISSING_BEFORE_SUBMISSION"
    assert held["steps"][0]["action_id"] is None
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01") == []


def test_cell_grant_cannot_change_a_pose_or_run_under_a_stale_generation(tmp_path):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    ready = store.admit("cell-mission-1", actor_id="operator-1",
                        expected_generation=enabled["generation"])
    changed = _grant(ready, 0)
    changed["cell_transfer"]["pick"]["x"] = 0.9
    changed["request_digest"] = cell_transfer_grant_digest(changed)
    with pytest.raises(ValueError, match="PlanBundle step"):
        store.start_step(
            "cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
            grant=changed,
        )

    stopped = tasks.trip_stop_latch(actor_id="operator-1")
    tasks.rearm_dispatch(expected_generation=stopped["generation"], actor_id="operator-1")
    held = store.get("cell-mission-1")
    assert held["status"] == "HOLD" and held["reason"] == "site_stop"
    with pytest.raises(MissionConflict, match="current READY"):
        store.start_step(
            "cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
            grant=_grant(ready, 0),
        )


def _running(tmp_path):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    ready = store.admit("cell-mission-1", actor_id="operator-1",
                        expected_generation=enabled["generation"])
    running = store.start_step(
        "cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
        grant=_grant(ready, 0),
    )
    return path, tasks, store, running


def _phases(tasks):
    return sorted({claim["phase"] for kind, ident in (("workcell", "omx_01"), ("pallet", "pallet-1"))
                   for claim in tasks.resource_claims(resource_kind=kind, resource_id=ident)})


def test_submission_promotes_claims_so_a_stop_cannot_drop_an_inflight_claim(tmp_path):
    # rosy-a9 item 1: the latch deletes CLAIMED claims; an in-flight Action's claims are DISPATCHING.
    _, tasks, _, running = _running(tmp_path)
    assert running["status"] == "RUNNING" and _phases(tasks) == ["DISPATCHING"]

    stopped = tasks.trip_stop_latch(actor_id="operator-1")

    assert _phases(tasks) == ["DISPATCHING"]
    with pytest.raises(Exception, match="unresolved Action claims"):
        tasks.rearm_dispatch(expected_generation=stopped["generation"], actor_id="operator-1")


@pytest.mark.parametrize("outcome, reason, status, phases", [
    ("SUCCEEDED", None, "ACTION_SUCCEEDED", ["CLAIMED"]),
    ("FAILED", "LOCAL_ACTION_FAILED", "HOLD", ["HELD"]),
    ("REJECTED", "LOCAL_ACTION_REJECTED", "HOLD", ["HELD"]),
    ("UNKNOWN", "LOCAL_ACTION_READBACK_UNKNOWN", "HOLD", ["UNKNOWN"]),
])
def test_result_outcomes_set_status_reason_and_claim_phase(tmp_path, outcome, reason, status, phases):
    # rosy-a9 item 2: a confirmed end returns the claims; only an unknown outcome pins them.
    _, tasks, store, _ = _running(tmp_path)
    result = store.record_action_result(
        "cell-mission-1", step_index=0, event_id="device-event-0", action_id="action-0",
        attempt_id="attempt-0", outcome=outcome, reason=reason, result={"journal_event_id": 3},
    )
    assert result["status"] == result["steps"][0]["status"] == status
    assert result["reason"] == result["steps"][0]["reason"] == reason
    assert _phases(tasks) == phases


def test_a_non_success_needs_a_reason_and_outcomes_are_closed(tmp_path):
    _, _, store, _ = _running(tmp_path)
    with pytest.raises(ValueError, match="reason"):
        store.record_action_result("cell-mission-1", step_index=0, event_id="e", action_id="action-0",
                                   attempt_id="attempt-0", outcome="FAILED", result={})
    with pytest.raises(ValueError, match="outcome"):
        store.record_action_result("cell-mission-1", step_index=0, event_id="e", action_id="action-0",
                                   attempt_id="attempt-0", outcome="HOLD", reason="X", result={})


def test_device_results_use_the_callers_event_id_and_replays_are_noops(tmp_path):
    # rosy-a9 item 5 + key check: the key is the caller's event_id; replay is checked before status.
    path, _, store, _ = _running(tmp_path)
    first = store.record_action_result(
        "cell-mission-1", step_index=0, event_id="device:abc", action_id="action-0",
        attempt_id="attempt-0", outcome="SUCCEEDED", result={"journal_event_id": 3},
    )
    replay = store.record_action_result(
        "cell-mission-1", step_index=0, event_id="device:abc", action_id="action-0",
        attempt_id="attempt-0", outcome="SUCCEEDED", result={"journal_event_id": 3},
    )
    assert replay == first
    with store._connect() as connection:
        keys = [row[0] for row in connection.execute(
            "SELECT event_key FROM fleet_cell_events WHERE event_type LIKE 'CELL_STEP_ACTION_%'")]
    assert keys == ["cell-mission-1:device:abc"]
    with pytest.raises(MissionConflict, match="reused"):
        store.record_action_result(
            "cell-mission-1", step_index=0, event_id="device:abc", action_id="action-0",
            attempt_id="attempt-0", outcome="FAILED", reason="LOCAL_ACTION_FAILED", result={},
        )

    confirmed = store.confirm_step_goal(
        "cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
        evidence=_goal("action-0", "attempt-0", "goal-0"),
    )
    again = store.confirm_step_goal(
        "cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
        evidence=_goal("action-0", "attempt-0", "goal-0"),
    )
    assert again == confirmed and again["current_step_index"] == 1
    changed = {**_goal("action-0", "attempt-0", "goal-0"), "producer_id": "other"}
    with pytest.raises(MissionConflict, match="reused"):
        store.confirm_step_goal("cell-mission-1", step_index=0, action_id="action-0",
                                attempt_id="attempt-0", evidence=changed)


def test_submitting_event_carries_the_fence(tmp_path):
    # rosy-a9 item 6.
    _, _, _, running = _running(tmp_path)
    submitting = [event for event in running["events"] if event["event_type"] == "CELL_STEP_SUBMITTING"]
    assert submitting[0]["detail"]["authority_epoch"] == running["authority_epoch"]
    assert submitting[0]["detail"]["dispatch_generation"] == running["dispatch_generation"]


@pytest.mark.parametrize("claim_phase, phases", [("UNKNOWN", ["UNKNOWN"])])
def test_generic_hold_from_running_is_idempotent(tmp_path, claim_phase, phases):
    # rosy-a9 item 4; 1b A2, 1c: a RUNNING Job holds with UNKNOWN claims only.
    _, tasks, store, _ = _running(tmp_path)
    held = store.hold("cell-mission-1", reason="LOCAL_ACTION_READBACK_UNKNOWN",
                      claim_phase=claim_phase, actor_id="mission-dispatcher", event_key="hold-1")
    again = store.hold("cell-mission-1", reason="LOCAL_ACTION_READBACK_UNKNOWN",
                       claim_phase=claim_phase, actor_id="mission-dispatcher", event_key="hold-1")
    assert held == again
    assert held["status"] == held["steps"][0]["status"] == "HOLD"
    assert _phases(tasks) == phases
    assert [event["event_type"] for event in held["events"]].count("CELL_JOB_HELD") == 1


@pytest.mark.parametrize("claim_phase, error", [
    (None, ValueError), ("HELD", MissionConflict), ("DISPATCHING", ValueError),
])
def test_running_hold_cannot_release_or_park_in_flight_claims(tmp_path, claim_phase, error):
    # 1b A2 / 1c: a RUNNING Job holds with UNKNOWN only; hold() never releases.
    _, tasks, store, _ = _running(tmp_path)
    with pytest.raises(error):
        store.hold("cell-mission-1", reason="X", claim_phase=claim_phase, actor_id="op", event_key="k")
    assert store.get("cell-mission-1")["status"] == "RUNNING" and _phases(tasks) == ["DISPATCHING"]


def test_pre_send_hold_releases_and_action_succeeded_hold_parks_claims(tmp_path):
    # 1b A2/A5 and the untested ACTION_SUCCEEDED hold path.
    _, tasks, store, _ = _running(tmp_path)
    store.record_action_result("cell-mission-1", step_index=0, event_id="e", action_id="action-0",
                               attempt_id="attempt-0", outcome="SUCCEEDED", result={})
    with pytest.raises(MissionConflict):
        store.hold("cell-mission-1", reason="X", claim_phase="UNKNOWN", actor_id="op", event_key="k")
    held = store.hold("cell-mission-1", reason="OPERATOR_HOLD", claim_phase="HELD", actor_id="op",
                      event_key="k")
    assert held["status"] == held["steps"][0]["status"] == "HOLD" and _phases(tasks) == ["HELD"]


def test_hold_after_re_approval_is_not_a_replay(tmp_path):
    # 1b B2: the hold key carries the approval count.
    path, _, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    store.hold("cell-mission-1", reason="R", claim_phase="HELD", actor_id="op", event_key="same")
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO fleet_cell_events (event_key, mission_id, step_index, event_type, actor_id, "
            "detail_json, created_at) VALUES ('m:resumed', 'cell-mission-1', 0, 'CELL_JOB_RESUMED', "
            "'op', '{}', 'now')")
        connection.execute("UPDATE fleet_cell_jobs SET status='READY'")
        connection.execute("UPDATE fleet_cell_steps SET status='READY' WHERE step_index=0")
        connection.commit()
    again = store.hold("cell-mission-1", reason="R", claim_phase="HELD", actor_id="op", event_key="same")
    assert again["status"] == "HOLD"
    assert [event["event_type"] for event in again["events"]].count("CELL_JOB_HELD") == 2


def test_generic_hold_is_valid_only_from_ready_running_or_action_succeeded(tmp_path):
    path, _, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    with pytest.raises(MissionConflict, match="cannot be held"):
        store.hold("cell-mission-1", reason="X", claim_phase="HELD", actor_id="op", event_key="k")
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    ready_hold = store.hold("cell-mission-1", reason="OPERATOR_HOLD", claim_phase="HELD",
                            actor_id="operator-1", event_key="k")
    assert ready_hold["steps"][0]["status"] == "HOLD"
    with pytest.raises(MissionConflict, match="cannot be held"):
        store.hold("cell-mission-1", reason="X", claim_phase="HELD", actor_id="op", event_key="k2")


def _claim_phases(path):
    import sqlite3
    connection = sqlite3.connect(path)
    try:
        return sorted(connection.execute(
            "SELECT owner_id, resource_key, phase FROM fleet_action_claims").fetchall())
    finally:
        connection.close()


def _second_job(store, generation):
    store.create(mission_id="cell-mission-2", proposal_principal_id="cell-service",
                 request_key="cell-request-2", request_digest="d" * 64, submission=_submission())
    return store.admit("cell-mission-2", actor_id="operator-1", expected_generation=generation)


def test_stop_latch_keeps_a_failed_jobs_claims_so_another_job_cannot_take_them(tmp_path):
    # C4b 1b A1 (review M1 probe): A HOLD after FAILED -> stop -> B must not be admitted.
    path, tasks, store, _ = _running(tmp_path)
    store.record_action_result("cell-mission-1", step_index=0, event_id="e1", action_id="action-0",
                               attempt_id="attempt-0", outcome="FAILED", reason="LOCAL_ACTION_FAILED",
                               result={})
    stopped = tasks.trip_stop_latch(actor_id="operator-1")
    assert {phase for _, _, phase in _claim_phases(path)} == {"HELD"}
    rearmed = tasks.rearm_dispatch(expected_generation=stopped["generation"], actor_id="operator-1")
    with pytest.raises(MissionConflict, match="conflicts"):
        _second_job(store, rearmed["generation"])


@pytest.mark.parametrize("state", ["READY", "ACTION_SUCCEEDED", "HOLD"])
def test_stop_latch_holds_a_non_terminal_job_and_keeps_claims_out_of_its_reach(tmp_path, state):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    ready = store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    if state != "READY":
        store.start_step("cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
                         grant=_grant(ready, 0))
        store.record_action_result(
            "cell-mission-1", step_index=0, event_id="e1", action_id="action-0", attempt_id="attempt-0",
            outcome="SUCCEEDED" if state == "ACTION_SUCCEEDED" else "REJECTED",
            reason=None if state == "ACTION_SUCCEEDED" else "LOCAL_ACTION_REJECTED", result={})
    stopped = tasks.trip_stop_latch(actor_id="operator-1")
    job = store.get("cell-mission-1")
    assert job["status"] == "HOLD"
    if state != "HOLD":
        assert job["reason"] == "site_stop"
    assert {phase for _, _, phase in _claim_phases(path)} == {"HELD"}
    # Held claims do not block rearm (only unresolved DISPATCHING/UNKNOWN do).
    assert stopped["rearm_available"] is True
    rearmed = tasks.rearm_dispatch(expected_generation=stopped["generation"], actor_id="operator-1")
    assert rearmed["dispatch_enabled"]
    with pytest.raises(MissionConflict):
        store.confirm_step_goal("cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
                                evidence=_goal("action-0", "attempt-0", "goal-0"))


def test_startup_fence_keeps_claims_held(tmp_path):
    path, tasks, store, _ = _running(tmp_path)
    store.record_action_result("cell-mission-1", step_index=0, event_id="e1", action_id="action-0",
                               attempt_id="attempt-0", outcome="SUCCEEDED", result={})
    tasks.close_dispatch_for_startup()
    CellJobStore(path).recover_after_startup()
    assert {phase for _, _, phase in _claim_phases(path)} == {"HELD"}
