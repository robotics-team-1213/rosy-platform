"""Manual sheet checkpoints fence box dispatch; no physical-access proof is inferred."""

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib
import json
import pytest

from fleet.server.cell_job_store import CellJobStore
from fleet.server.mission_store import MissionConflict
from test_cell_job_store import _stores, _submission, _grant, _goal, _claim_phases
from test_step_dispatcher import REVISIONS, Transport
from fleet.server.step_dispatcher import StepJobDispatcher


def checkpoint(ordinal=2):
    descriptor = {"kind": "operator_sheet",
            "before_transfer_ordinal": ordinal, "pallet_id": "pallet-1", "layer_index": ordinal - 1,
            "sheet_pose_base": {"x_m": .4, "y_m": .5, "z_m": .3, "yaw_rad": 0.}, "thickness_m": .001}
    bound = {"recipe_sha256": "a" * 64, "cell_sha256": "b" * 64, "checkpoint": descriptor}
    return {"checkpoint_id": hashlib.sha256(json.dumps(bound, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode()).hexdigest(), **descriptor}


def create(tmp_path, ordinal=2):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    submission = _submission()
    submission["operator_checkpoints"] = [checkpoint(ordinal)]
    bind_manual_job(submission)
    store.create(mission_id="sheet-job", proposal_principal_id="cell-service", request_key="sheet-request",
                 request_digest="d" * 64, submission=submission)
    return path, tasks, store, enabled


def bind_manual_job(submission):
    raw = []
    indexed = {value["before_transfer_ordinal"]: value for value in submission["operator_checkpoints"]}
    for ordinal, transfer in enumerate(submission["steps"], 1):
        body = transfer["inputs"]
        sheet = indexed.get(ordinal)
        if sheet is not None:
            pose = sheet["sheet_pose_base"]
            raw.append({"kind": "operator_sheet", "item": "slip_sheet", "pallet": sheet["pallet_id"],
                        "layer": sheet["layer_index"], "target": {"x": pose["x_m"], "y": pose["y_m"],
                        "z": pose["z_m"], "yaw": pose["yaw_rad"]}, "approach_z": None, "thickness_m": sheet["thickness_m"]})
        for kind in ("pick", "place"):
            raw.append({"kind": kind, "item": "box", "pallet": body["pallet_id"], "layer": body["layer_index"],
                        "target": None, "approach_z": None})
    submission["job"] = {"recipe_hash": submission["recipe_digest"], "cell_hash": submission["cell_digest"],
                         "carry_z": .6, "steps": raw}


def test_first_transfer_checkpoint_holds_admission_and_dispatch(tmp_path):
    path, tasks, store, enabled = create(tmp_path, ordinal=1)
    job = store.admit("sheet-job", actor_id="operator-1", expected_generation=enabled["generation"])
    assert job["status"] == "HOLD"
    assert job["reason"] == "OPERATOR_SHEET_ACCESS_UNAVAILABLE"
    assert job["operator_checkpoints"][0]["status"] == "WAITING_ACCESS"
    assert {phase for _, _, phase in _claim_phases(path)} == {"HELD"}
    transport = Transport()
    dispatcher = StepJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                                   deployment_profile="simulation")
    dispatcher.dispatch_next()
    assert not transport.submissions
    with pytest.raises(MissionConflict, match="checkpoint"):
        store.resume("sheet-job", actor_id="operator-1", expected_generation=enabled["generation"])


def test_goal_confirmation_and_checkpoint_hold_are_one_durable_transition(tmp_path):
    path, _, store, enabled = create(tmp_path)
    ready = store.admit("sheet-job", actor_id="operator-1", expected_generation=enabled["generation"])
    store.start_step("sheet-job", step_index=0, action_id="action-0", attempt_id="attempt-0", grant=_grant(ready, 0))
    store.record_action_result("sheet-job", step_index=0, event_id="terminal", action_id="action-0",
                              attempt_id="attempt-0", outcome="SUCCEEDED", result={"journal_event_id": 10})
    held = store.confirm_step_goal("sheet-job", step_index=0, action_id="action-0", attempt_id="attempt-0",
                                  evidence=_goal("action-0", "attempt-0", "goal"))
    assert held["status"] == "HOLD" and held["current_step_index"] == 1
    assert [step["status"] for step in held["steps"]] == ["GOAL_CONFIRMED", "HOLD"]
    assert held["steps"][0]["action_id"] == "action-0"
    assert held["steps"][1]["grant"] is None
    assert held["operator_checkpoints"][0]["status"] == "WAITING_ACCESS"
    assert {phase for _, _, phase in _claim_phases(path)} == {"HELD"}
    reopened = CellJobStore(path)
    reopened.recover_after_startup()
    assert reopened.get("sheet-job") == held


def test_final_start_gate_closes_corrupt_ready_state_without_journaling_grant(tmp_path):
    path, _, store, enabled = create(tmp_path, ordinal=1)
    held = store.admit("sheet-job", actor_id="operator-1", expected_generation=enabled["generation"])
    with closing(store._connect()) as db, db:
        db.execute("UPDATE fleet_cell_jobs SET status='READY',reason=NULL WHERE mission_id='sheet-job'")
        db.execute("UPDATE fleet_cell_steps SET status='READY' WHERE mission_id='sheet-job' AND step_index=0")
    job = store.start_step("sheet-job", step_index=0, action_id="action-0", attempt_id="attempt-0", grant=_grant(held, 0))
    assert job["status"] == "HOLD"
    assert job["steps"][0]["action_id"] is None
    assert job["steps"][0]["grant"] is None


def test_restart_closes_ready_checkpoint_even_without_generation_change(tmp_path):
    path, _, store, enabled = create(tmp_path, ordinal=1)
    store.admit("sheet-job", actor_id="operator-1", expected_generation=enabled["generation"])
    with closing(store._connect()) as db, db:
        db.execute("UPDATE fleet_cell_jobs SET status='READY',reason=NULL WHERE mission_id='sheet-job'")
        db.execute("UPDATE fleet_cell_steps SET status='READY' WHERE mission_id='sheet-job' AND step_index=0")
    reopened = CellJobStore(path)
    reopened.recover_after_startup()
    assert reopened.get("sheet-job")["status"] == "HOLD"


def test_goal_confirmation_racing_next_start_never_issues_next_grant(tmp_path):
    _, _, store, enabled = create(tmp_path)
    ready = store.admit("sheet-job", actor_id="operator-1", expected_generation=enabled["generation"])
    store.start_step("sheet-job", step_index=0, action_id="action-0", attempt_id="attempt-0", grant=_grant(ready, 0))
    store.record_action_result("sheet-job", step_index=0, event_id="terminal", action_id="action-0",
                              attempt_id="attempt-0", outcome="SUCCEEDED", result={"journal_event_id": 10})
    barrier = Barrier(2)
    def confirm():
        barrier.wait(timeout=3)
        return store.confirm_step_goal("sheet-job", step_index=0, action_id="action-0", attempt_id="attempt-0",
                                       evidence=_goal("action-0", "attempt-0", "goal"))
    def start():
        barrier.wait(timeout=3)
        with pytest.raises(MissionConflict):
            store.start_step("sheet-job", step_index=1, action_id="action-1", attempt_id="attempt-1", grant=_grant(ready, 1))
    with ThreadPoolExecutor(max_workers=2) as pool:
        confirming, starting = pool.submit(confirm), pool.submit(start)
        assert confirming.result(timeout=5)["status"] == "HOLD"
        starting.result(timeout=5)
    assert store.get("sheet-job")["steps"][1]["grant"] is None


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(operator_checkpoints=[]),
    lambda value: value["operator_checkpoints"][0].update(checkpoint_id="0" * 64),
    lambda value: value["operator_checkpoints"][0].update(before_transfer_ordinal=3),
    lambda value: value["operator_checkpoints"][0].update(thickness_m=float("nan")),
    lambda value: value["operator_checkpoints"][0].update(layer_index=True),
    lambda value: value["operator_checkpoints"][0].update(pallet_id="other"),
])
def test_invalid_checkpoint_rolls_back_job_and_steps(tmp_path, mutate):
    path, _, _, _ = _stores(tmp_path)
    store = CellJobStore(path)
    submission = _submission()
    submission["operator_checkpoints"] = [checkpoint()]
    bind_manual_job(submission)
    mutate(submission)
    with pytest.raises(ValueError):
        store.create(mission_id="bad", proposal_principal_id="cell-service", request_key="request",
                     request_digest="d" * 64, submission=submission)
    assert store.get("bad") is None
    with closing(store._connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM fleet_cell_checkpoints").fetchone()[0] == 0


def test_dispatch_due_checkpoint_before_owner_identity_or_grant_creation(tmp_path):
    _, tasks, store, enabled = create(tmp_path, ordinal=1)
    store.admit("sheet-job", actor_id="operator-1", expected_generation=enabled["generation"])
    with closing(store._connect()) as db, db:
        db.execute("UPDATE fleet_cell_jobs SET status='READY',reason=NULL WHERE mission_id='sheet-job'")
        db.execute("UPDATE fleet_cell_steps SET status='READY' WHERE mission_id='sheet-job' AND step_index=0")
    calls = []
    transport = Transport()
    original = transport.owner_identity
    transport.owner_identity = lambda instance: (calls.append(instance), original(instance))[1]
    dispatcher = StepJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                                   deployment_profile="simulation")
    grants = []
    original_grant = dispatcher._grant
    dispatcher._grant = lambda *args: (grants.append(args), original_grant(*args))[1]
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert not calls and not grants and not transport.submissions


@pytest.mark.parametrize("mutation", ["omitted", "partial", "wrong_pose", "malformed_manual"])
def test_manual_job_requires_complete_matching_checkpoint_projection(tmp_path, mutation):
    path, _, _, _ = _stores(tmp_path)
    store = CellJobStore(path)
    submission = _submission()
    submission["operator_checkpoints"] = [checkpoint(1), checkpoint(2)]
    bind_manual_job(submission)
    if mutation == "omitted":
        del submission["operator_checkpoints"]
    elif mutation == "partial":
        submission["operator_checkpoints"] = submission["operator_checkpoints"][:1]
    elif mutation == "wrong_pose":
        submission["job"]["steps"][0]["target"]["z"] = .9
    else:
        del submission["job"]["steps"][0]["thickness_m"]
    with pytest.raises(ValueError, match="checkpoint|manual"):
        store.create(mission_id="bad-projection", proposal_principal_id="cell-service", request_key="request",
                     request_digest="d" * 64, submission=submission)
    assert store.get("bad-projection") is None
