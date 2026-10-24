"""D-779 stage 1: per-arm tables mirror the single-arm ledger without changing its behaviour."""

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from fleet.server import cell_job_store as store_module
from fleet.server.cell_arm_ledger import SINGLE_ARM_ROLE, arms, depends_on, step_actions
from fleet.server.cell_job_store import CellJobStore
from fleet.server.action_claims import release_keys
from fleet.server.dispatch_admission import reserve
from fleet.server.mission_store import MissionStore
from fleet.server.step_action_kinds import step_grant_digest
from fleet.server.task_store import FleetTaskStore


def _ledger(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    control = FleetTaskStore(path)
    control = control.store if hasattr(control, "store") else control
    MissionStore(path)
    enabled = control.rearm_dispatch(expected_generation=control.dispatch_control()["generation"],
                                     actor_id="operator-1")
    return path, CellJobStore(path), enabled


def _step(index):
    return {"skill_id": "pallet.transfer", "version": "1.0.0", "inputs": {
        "item": "box", "pallet_id": "pallet-1", "layer_index": index,
        "home_pose_base": {"x_m": 0.0, "y_m": 0.0, "z_m": 0.4, "yaw_rad": 0.0},
        "source_pose_base": {"x_m": 0.1, "y_m": 0.2, "z_m": 0.3, "yaw_rad": 0.0},
        "destination_pose_base": {"x_m": 0.4, "y_m": 0.5, "z_m": 0.3, "yaw_rad": 1.57},
        "source_approach_z_base_m": 0.5, "destination_approach_z_base_m": 0.5, "carry_z_base_m": 0.6}}


def _submission(step_count=2):
    return {"job_id": "e" * 64, "workcell_id": "omx_01", "instance_id": "omx_01_control",
            "recipe_digest": "a" * 64, "cell_digest": "b" * 64, "process_artifact_digest": "c" * 64,
            "job": {"steps": list(range(step_count))}, "steps": [_step(i) for i in range(step_count)],
            "resources": [["workcell", "omx_01"], ["pallet", "pallet-1"]],
            "ledger_markers": [{"after_step_ordinal": step_count, "pallet_id": "pallet-1"}]}


def _grant(job, index):
    step = job["steps"][index]["step"]["inputs"]
    now = datetime.now(timezone.utc)
    value = {
        "mission_id": job["mission_id"], "step_id": job["steps"][index]["step_id"],
        "action_id": f"action-{index}", "attempt_id": f"attempt-{index}", "request_digest": "0" * 64,
        "workcell_id": job["workcell_id"], "instance_id": job["instance_id"], "action_kind": "CELL_TRANSFER",
        "cell_transfer": {
            "job_id": job["job_id"], "recipe_sha256": job["recipe_digest"], "cell_sha256": job["cell_digest"],
            "step_index": index, "item": step["item"], "pallet": step["pallet_id"],
            "layer": step["layer_index"], "frame": "robot_base",
            "home": {"x": 0.0, "y": 0.0, "z": 0.4, "yaw": 0.0}, "pick": {"x": 0.1, "y": 0.2, "z": 0.3, "yaw": 0.0},
            "place": {"x": 0.4, "y": 0.5, "z": 0.3, "yaw": 1.57},
            "pick_approach_z": 0.5, "place_approach_z": 0.5, "carry_z": 0.6},
        "capability_revision": "cell-transfer-v1", "config_revision": "cell-config-v1",
        "authority_epoch": job["authority_epoch"], "dispatch_generation": job["dispatch_generation"],
        "issued_at": now, "expires_at": now + timedelta(seconds=30)}
    value["request_digest"] = step_grant_digest(value)
    return value


def _read(path, mission_id):
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        return arms(connection, mission_id), step_actions(connection, mission_id)


def _created(path, store):
    return store.create(mission_id="cell-1", proposal_principal_id="planner", request_key="rk-1",
                        request_digest="d" * 64, submission=_submission())


def test_a_new_cell_job_gets_one_arm_and_one_action_per_step(tmp_path):
    path, store, _ = _ledger(tmp_path)
    _created(path, store)
    arm_rows, actions = _read(path, "cell-1")
    assert [(row["arm_role"], row["instance_id"], row["status"]) for row in arm_rows] == [
        (SINGLE_ARM_ROLE, "omx_01_control", "READY")]
    assert [(row["step_index"], row["arm_role"], row["status"], row["action_kind"]) for row in actions] == [
        (0, SINGLE_ARM_ROLE, "WAITING", "CELL_TRANSFER"), (1, SINGLE_ARM_ROLE, "WAITING", "CELL_TRANSFER")]


def test_the_mirror_follows_admit_start_and_a_failed_result(tmp_path):
    path, store, control = _ledger(tmp_path)
    _created(path, store)
    job = store.admit("cell-1", actor_id="operator-1", expected_generation=control["generation"])
    assert _read(path, "cell-1")[1][0]["status"] == "READY"
    store.start_step("cell-1", step_index=0, action_id="action-0", attempt_id="attempt-0", grant=_grant(job, 0))
    arm_rows, actions = _read(path, "cell-1")
    assert (arm_rows[0]["status"], arm_rows[0]["running_step_index"]) == ("RUNNING", 0)
    assert (actions[0]["status"], actions[0]["action_id"], actions[0]["attempt_id"]) == (
        "RUNNING", "action-0", "attempt-0")
    store.record_action_result("cell-1", step_index=0, event_id="ev-1", action_id="action-0",
                               attempt_id="attempt-0", outcome="FAILED", result={}, reason="GRASP_LOST")
    arm_rows, actions = _read(path, "cell-1")
    assert (arm_rows[0]["status"], arm_rows[0]["running_step_index"], arm_rows[0]["reason"]) == (
        "HOLD", None, "GRASP_LOST")
    assert (actions[0]["status"], actions[0]["reason"]) == ("HOLD", "GRASP_LOST")


def test_a_version_two_ledger_is_backfilled_on_start(tmp_path):
    path, store, _ = _ledger(tmp_path)
    _created(path, store)
    expected = _read(path, "cell-1")
    with closing(sqlite3.connect(path)) as connection:
        for trigger in ("fleet_cell_arm_mirror_step_insert", "fleet_cell_arm_mirror_step_update",
                        "fleet_cell_arm_mirror_job_update"):
            connection.execute(f"DROP TRIGGER {trigger}")
        connection.execute("DROP TABLE fleet_cell_step_actions")
        connection.execute("DROP TABLE fleet_cell_job_arms")
        connection.execute("DELETE FROM fleet_component_migrations WHERE component='cell_jobs' AND version>=3")
        connection.commit()
    CellJobStore(path)
    assert _read(path, "cell-1") == expected


def test_an_older_fleet_refuses_a_version_three_ledger(tmp_path, monkeypatch):
    path, _, _ = _ledger(tmp_path)
    monkeypatch.setattr(store_module, "_MIGRATION_VERSION", 2)
    with pytest.raises(RuntimeError, match="unsupported Cell Job journal migration version 5"):
        CellJobStore(path)


def test_a_trip_job_gets_no_arm_rows(tmp_path):
    path, store, _ = _ledger(tmp_path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "INSERT INTO fleet_cell_jobs (mission_id, proposal_principal_id, request_key, request_digest, job_id, "
            "workcell_id, instance_id, recipe_digest, cell_digest, process_artifact_digest, job_json, "
            "resources_json, ledger_markers_json, status, created_at, updated_at) VALUES "
            "('trip-1', 'p', 'k', ?, 'j', 'site', 'pinky_01', ?, ?, ?, '{}', '[]', '[]', 'PROPOSED', 't', 't')",
            ("d" * 64, "a" * 64, "b" * 64, "c" * 64))
        connection.execute(
            "INSERT INTO fleet_cell_steps (mission_id, step_index, step_id, action_kind, step_json, status, "
            "updated_at) VALUES ('trip-1', 0, 'trip-1:step-1', 'TRIP', '{}', 'WAITING', 't')")
        connection.commit()
    assert _read(path, "trip-1") == ([], [])


def test_depends_on_keeps_serial_order_for_steps_compiled_before_d779():
    assert depends_on("{}", 0) == ()
    assert depends_on('{"skill_id": "pallet.transfer"}', 3) == (2,)
    assert depends_on({"depends_on": [2, 0, 2]}, 3) == (0, 2)
    assert depends_on({"depends_on": []}, 3) == ()
    for bad in ([3], [-1], ["1"], 1):
        with pytest.raises(ValueError, match="earlier step indexes"):
            depends_on({"depends_on": bad}, 3)


def test_arm_and_zone_claims_are_released_by_key_only(tmp_path):
    path, _, _ = _ledger(tmp_path)
    with closing(sqlite3.connect(path)) as connection:
        assert reserve(connection, owner_kind="mission", owner_id="cell-1", generation=1, phase="DISPATCHING",
                       resources=[("arm", "omx_01.left"), ("zone", "omx_01.shared_band"), ("workcell", "omx_01")])
        assert not reserve(connection, owner_kind="mission", owner_id="cell-2", generation=1, phase="DISPATCHING",
                           resources=[("zone", "omx_01.shared_band")])
        assert reserve(connection, owner_kind="mission", owner_id="cell-2", generation=1, phase="DISPATCHING",
                       resources=[("zone", "omx_01.right_half")])
        released = release_keys(connection, owner_kind="mission", owner_id="cell-1", generation=1,
                                resources=[("arm", "omx_01.left"), ("zone", "omx_01.shared_band"),
                                           ("zone", "omx_01.right_half")])
        assert released == 2
        left = {row[0] for row in connection.execute("SELECT resource_key FROM fleet_action_claims")}
        assert left == {"workcell:omx_01", "zone:omx_01.right_half"}


def test_release_keys_never_frees_job_claims_or_settled_phases(tmp_path):
    path, _, _ = _ledger(tmp_path)
    with closing(sqlite3.connect(path)) as connection:
        with pytest.raises(ValueError, match="only arm and zone"):
            release_keys(connection, owner_kind="mission", owner_id="cell-1", generation=1,
                         resources=[("workcell", "omx_01")])
        with pytest.raises(ValueError, match="generation"):
            release_keys(connection, owner_kind="mission", owner_id="cell-1", generation=-1,
                         resources=[("arm", "omx_01.left")])
        for phase, arm in (("HELD", "omx_01.left"), ("UNKNOWN", "omx_01.right")):
            assert reserve(connection, owner_kind="mission", owner_id="cell-1", generation=1, phase=phase,
                           resources=[("arm", arm)])
        assert reserve(connection, owner_kind="mission", owner_id="cell-1", generation=2, phase="CLAIMED",
                       resources=[("zone", "omx_01.left_half")])
        assert release_keys(connection, owner_kind="mission", owner_id="cell-1", generation=1,
                            resources=[("arm", "omx_01.left"), ("arm", "omx_01.right"),
                                       ("zone", "omx_01.left_half")]) == 0
        assert connection.execute("SELECT COUNT(*) FROM fleet_action_claims").fetchone()[0] == 3


def test_two_jobs_reusing_an_action_id_do_not_break_the_mirror(tmp_path):
    path, store, control = _ledger(tmp_path)
    for mission_id, key in (("cell-1", "rk-1"), ("cell-2", "rk-2")):
        submission = _submission()
        submission["workcell_id"], submission["instance_id"] = f"omx_{mission_id}", f"{mission_id}_control"
        submission["resources"] = [["workcell", f"omx_{mission_id}"], ["pallet", f"pallet-{mission_id}"]]
        store.create(mission_id=mission_id, proposal_principal_id="planner", request_key=key,
                     request_digest="d" * 64, submission=submission)
        job = store.admit(mission_id, actor_id="operator-1", expected_generation=control["generation"])
        store.start_step(mission_id, step_index=0, action_id="action-0", attempt_id="attempt-0",
                         grant=_grant(job, 0))
    assert [row["action_id"] for row in _read(path, "cell-2")[1]][:1] == ["action-0"]
