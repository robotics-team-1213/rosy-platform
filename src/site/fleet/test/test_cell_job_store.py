from datetime import datetime, timedelta, timezone

import pytest

from fleet.server.cell_job_store import CellJobStore, cell_transfer_grant_digest
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
        result={"transport": "timeout"},
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
        assert control["rearm_available"] is False
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
    with pytest.raises(MissionConflict, match="all durable resource claims"):
        store.start_step("cell-mission-1", step_index=0, action_id="action-0",
                         attempt_id="attempt-0", grant=_grant(ready, 0))
    unchanged = store.get("cell-mission-1")
    assert unchanged["status"] == unchanged["steps"][0]["status"] == "READY"
    assert unchanged["steps"][0]["action_id"] is None
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")[0]["phase"] == "CLAIMED"


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
    with pytest.raises(MissionConflict, match="generation changed"):
        store.start_step(
            "cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
            grant=_grant(ready, 0),
        )
