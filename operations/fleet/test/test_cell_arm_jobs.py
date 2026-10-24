"""D-779 stage 2: multi-arm Cell Job creation, placement and the single-arm paths that must skip it."""

import copy
import sqlite3
from contextlib import closing

import pytest

from fleet.server import cell_arm_jobs
from fleet.server import cell_job_store as store_module
from fleet.server.cell_arm_ledger import SINGLE_ARM_ROLE
from fleet.server.cell_arm_store import ArmJobStore
from fleet.server.cell_job_store import CANCELLED_REASON, CellJobStore
from fleet.server.mission_store import MissionConflict

from test_cell_job_store import _create, _stores
from test_cell_job_store import _step as _single_step
from test_cell_job_store import _submission as _single_submission

WORKCELL = "bench_01"
ARMS = [{"role": "left", "instance_id": "omx_01_control", "workcell_id": "omx_01"},
        {"role": "right", "instance_id": "omx_02_control", "workcell_id": "omx_02"}]


def inputs(index):
    return copy.deepcopy(_single_step(index)["inputs"])


def arm_step(index, arm, zone, depends_on, *, alternates=(), coupling="independent"):
    roles = [arm] if isinstance(arm, str) else list(arm)
    return {"skill_id": "pallet.transfer", "version": "1.0.0", "placement": {
        "arm": arm, "alternates": list(alternates), "zone": zone, "coupling": coupling,
        "depends_on": list(depends_on), "actions": {role: inputs(index) for role in [*roles, *alternates]}}}


def four_steps():
    """Two arms in their own halves, then one shared-band step each after their first."""
    return [arm_step(0, "left", "left_half", []), arm_step(1, "right", "right_half", []),
            arm_step(2, "left", "shared_band", [0]), arm_step(3, "right", "shared_band", [1])]


def arm_submission(steps=None, pallet="pallet-1", cell=WORKCELL):
    steps = four_steps() if steps is None else steps
    owners = [["workcell", arm["workcell_id"]] for arm in ARMS]
    return {"job_id": "e" * 64, "workcell_id": cell, "arms": copy.deepcopy(ARMS),
            "recipe_digest": "a" * 64, "cell_digest": "b" * 64, "process_artifact_digest": "c" * 64,
            "job": {"steps": list(range(len(steps)))}, "steps": steps,
            "resources": [["workcell", cell], *owners, ["pallet", pallet]],
            "ledger_markers": [{"after_step_ordinal": len(steps), "pallet_id": pallet}]}


def create_arm_job(cells, mission_id="arm-job-1", steps=None, pallet="pallet-1", cell=WORKCELL):
    return cells.create(mission_id=mission_id, proposal_principal_id="cell-service", request_key=f"rk-{mission_id}",
                        request_digest="d" * 64, submission=arm_submission(steps, pallet, cell))


def single_arm_job(cells, workcell="omx_03"):
    """A single-arm Job on its own workcell (``omx_01`` is an arm owner of the multi-arm Job)."""
    submission = {**_single_submission(), "workcell_id": workcell, "instance_id": f"{workcell}_control",
                  "resources": [["workcell", workcell], ["pallet", "pallet-1"]]}
    mission_id = "cell-mission-1" if workcell == "omx_03" else f"cell-mission-1-{workcell}"
    return cells.create(mission_id=mission_id, proposal_principal_id="cell-service",
                        request_key=f"request-{mission_id}", request_digest="d" * 64, submission=submission)


def rows(path, sql, *args):
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, args)]


def test_creation_stores_placement_beside_the_single_arm_step_shape(tmp_path):
    path, _, _, _ = _stores(tmp_path)
    cells = CellJobStore(path)
    job = create_arm_job(cells)
    assert job["status"] == "PROPOSED"
    assert [(arm["arm_role"], arm["instance_id"], arm["status"]) for arm in job["arms"]] == [
        ("left", "omx_01_control", "READY"), ("right", "omx_02_control", "READY")]
    assert [(p["step_index"], p["assigned"], p["zone_id"], p["depends_on"]) for p in job["placements"]] == [
        (0, ["left"], "left_half", []), (1, ["right"], "right_half", []),
        (2, ["left"], "shared_band", [0]), (3, ["right"], "shared_band", [1])]
    # step_json keeps the single-arm shape (the primary arm's inputs); placement lives elsewhere
    assert all(set(step["step"]) == {"skill_id", "version", "inputs"} for step in job["steps"])
    assert job["steps"][1]["step"]["inputs"] == inputs(1)
    # one Action row per primary arm, none mirrored for a single-arm role
    assert [(a["step_index"], a["arm_role"], a["status"]) for a in job["step_actions"]] == [
        (0, "left", "WAITING"), (1, "right", "WAITING"), (2, "left", "WAITING"), (3, "right", "WAITING")]
    assert cell_arm_jobs.CANCELLED_REASON == CANCELLED_REASON


def _broken(change):
    submission = arm_submission()
    change(submission)
    return submission


@pytest.mark.parametrize("change", [
    lambda s: s.update(arms=s["arms"][:1]),  # one arm is a single-arm Job
    lambda s: s["arms"][1].update(role="left"),
    lambda s: s["arms"][1].update(instance_id="omx_01_control"),
    lambda s: s["arms"][1].update(role="Right"),
    lambda s: s["steps"][0]["placement"].update(arm="middle"),
    lambda s: s["steps"][0]["placement"].update(alternates=["left"]),
    lambda s: s["steps"][0]["placement"].update(coupling="tight"),  # tight needs two arms
    lambda s: s["steps"][0]["placement"].update(coupling="rigid"),
    lambda s: s["steps"][2]["placement"].update(depends_on=[3]),  # a later step
    lambda s: s["steps"][2]["placement"].update(depends_on=None),  # multi-arm declares it
    lambda s: s["steps"][0]["placement"].update(alternates=["right"]),  # no inputs for the alternate
    lambda s: s["steps"][0]["placement"]["actions"]["left"].pop("carry_z_base_m"),
    lambda s: s["steps"][0]["placement"]["actions"]["left"].update(carry_z_base_m=0.1),
    lambda s: s["steps"][0]["placement"].pop("zone"),
    lambda s: s["steps"][0]["placement"].update(zone="bad zone"),
    lambda s: s["resources"].append(["zone", f"{WORKCELL}.left_half"]),  # per Action, not per Job
    lambda s: s.update(resources=[["pallet", "pallet-1"]]),
    lambda s: s["resources"].remove(["workcell", "omx_02"]),  # every arm owner is a Job-level claim
    lambda s: s["arms"][1].pop("workcell_id"),
    lambda s: s["arms"][1].update(workcell_id="omx_01"),
    lambda s: s.update(operator_checkpoints=[]),
    lambda s: s.update(instance_id="omx_01_control"),
    # D-781 §5 per-arm predicates: exactly the step's primary and alternate arms, in robot_base
    lambda s: s["steps"][0].update(goal_predicates={"left": {"frame": "robot_base"}, "right": {"frame": "robot_base"}}),
    lambda s: s["steps"][0].update(goal_predicates={"left": {"frame": "cell"}}),
    lambda s: s["steps"][0].update(goal_predicates=[{"frame": "robot_base"}]),
    # D-781 §2 sku on the wire: an identifier, and only on a box step
    lambda s: s["steps"][0]["placement"]["actions"]["left"].update(sku="bad sku"),
    lambda s: s["steps"][0]["placement"]["actions"]["left"].update(item="slip_sheet", sku="foam"),
])
def test_invalid_multi_arm_submissions_are_refused_and_write_nothing(tmp_path, change):
    path, _, _, _ = _stores(tmp_path)
    cells = CellJobStore(path)
    with pytest.raises(ValueError):
        cells.create(mission_id="arm-job-1", proposal_principal_id="cell-service", request_key="rk",
                     request_digest="d" * 64, submission=_broken(change))
    assert cells.get("arm-job-1") is None
    assert rows(path, "SELECT * FROM fleet_cell_arm_jobs") == []


def test_per_arm_goal_predicates_and_sku_are_stored_with_the_step(tmp_path):
    path, _, _, _ = _stores(tmp_path)
    cells = CellJobStore(path)
    step = arm_step(0, "left", "left_half", [], alternates=["right"])
    for role, x in (("left", 0.4), ("right", 0.2)):
        step["placement"]["actions"][role]["sku"] = "foam_40x30x30"
        step["goal_predicates"] = {**step.get("goal_predicates", {}),
                                   role: {"condition": "item_at_pose", "frame": "robot_base", "target": {"x": x}}}
    job = create_arm_job(cells, steps=[step])
    stored = job["steps"][0]["step"]
    assert set(stored) == {"skill_id", "version", "inputs", "goal_predicates"}
    assert stored["goal_predicates"] == step["goal_predicates"]
    assert stored["inputs"]["sku"] == "foam_40x30x30"
    assert job["placements"][0]["payloads"]["right"]["sku"] == "foam_40x30x30"


def test_a_coordinated_step_pairs_two_arms_without_alternates(tmp_path):
    path, _, _, _ = _stores(tmp_path)
    cells = CellJobStore(path)
    pair = arm_step(0, ["left", "right"], "shared_band", [], coupling="tight")
    job = create_arm_job(cells, steps=[pair])
    assert [(a["arm_role"], a["status"]) for a in job["step_actions"]] == [("left", "WAITING"), ("right", "WAITING")]
    repeated = arm_step(0, ["left", "right"], "shared_band", [])
    repeated["placement"]["arm"] = ["left", "left"]
    with pytest.raises(ValueError):
        create_arm_job(cells, "arm-job-2", steps=[repeated])


def test_single_arm_mirror_and_backfill_skip_a_multi_arm_job(tmp_path):
    path, _, _, enabled = _stores(tmp_path)
    cells = CellJobStore(path)
    create_arm_job(cells, pallet="pallet-2")  # beside a single-arm Job on pallet-1
    single_arm_job(cells)  # a single-arm Job beside it is still mirrored
    cells.admit("arm-job-1", actor_id="operator-1", expected_generation=enabled["generation"])
    cells.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    with closing(sqlite3.connect(path)) as connection:  # any later Job/step write leaves arm rows alone
        connection.execute("UPDATE fleet_cell_jobs SET status='RUNNING' WHERE mission_id='arm-job-1'")
        connection.execute("UPDATE fleet_cell_steps SET status='RUNNING', action_id='x' WHERE mission_id='arm-job-1'")
        connection.commit()
    CellJobStore(path)  # restart: triggers recreated, idempotent backfill
    arm_rows = rows(path, "SELECT arm_role, status FROM fleet_cell_job_arms WHERE mission_id='arm-job-1' "
                          "ORDER BY arm_role")
    assert arm_rows == [{"arm_role": "left", "status": "READY"}, {"arm_role": "right", "status": "READY"}]
    actions = rows(path, "SELECT step_index, arm_role, status, action_id FROM fleet_cell_step_actions "
                         "WHERE mission_id='arm-job-1' ORDER BY step_index")
    assert [(a["step_index"], a["arm_role"], a["status"], a["action_id"]) for a in actions] == [
        (0, "left", "WAITING", None), (1, "right", "WAITING", None),
        (2, "left", "WAITING", None), (3, "right", "WAITING", None)]
    single = rows(path, "SELECT arm_role, status FROM fleet_cell_job_arms WHERE mission_id='cell-mission-1'")
    assert single == [{"arm_role": SINGLE_ARM_ROLE, "status": "READY"}]


def test_single_arm_dispatcher_queries_never_return_a_multi_arm_job(tmp_path):
    path, _, _, enabled = _stores(tmp_path)
    cells = CellJobStore(path)
    create_arm_job(cells, pallet="pallet-2")  # beside a single-arm Job on pallet-1
    single_arm_job(cells)
    for mission_id in ("arm-job-1", "cell-mission-1"):
        cells.admit(mission_id, actor_id="operator-1", expected_generation=enabled["generation"])
    assert [job["mission_id"] for job in cells.jobs("READY")] == ["cell-mission-1"]
    assert "arms" not in cells.get("cell-mission-1")  # a single-arm read is unchanged
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE fleet_cell_jobs SET status='HOLD' WHERE mission_id='arm-job-1'")
        connection.execute("UPDATE fleet_action_claims SET phase='UNKNOWN' WHERE owner_id='arm-job-1'")
        connection.commit()
    assert cells.next_unresolved() == []


def test_admission_uses_the_job_claims_and_cancel_shows_on_every_arm(tmp_path):
    path, _, _, enabled = _stores(tmp_path)
    cells = CellJobStore(path)
    create_arm_job(cells)
    job = cells.admit("arm-job-1", actor_id="operator-1", expected_generation=enabled["generation"])
    assert job["status"] == "READY"
    assert sorted((c["resource_key"], c["phase"]) for c in rows(path, "SELECT * FROM fleet_action_claims")) == [
        ("pallet:pallet-1", "CLAIMED"), (f"workcell:{WORKCELL}", "CLAIMED"), ("workcell:omx_01", "CLAIMED"),
        ("workcell:omx_02", "CLAIMED")]
    arms = ArmJobStore(cells)
    cancelled = arms.cancel("arm-job-1", actor_id="operator-2")
    assert cancelled["reason"] == CANCELLED_REASON
    assert {(arm["status"], arm["reason"]) for arm in cancelled["arms"]} == {("HOLD", CANCELLED_REASON)}
    assert rows(path, "SELECT * FROM fleet_action_claims") == []
    assert not arms.has_active()
    with pytest.raises(MissionConflict):
        arms.resume("arm-job-1", actor_id="operator-2", expected_generation=enabled["generation"])


def test_a_stage_one_fleet_refuses_a_ledger_that_may_hold_multi_arm_jobs(tmp_path, monkeypatch):
    path, _, _, _ = _stores(tmp_path)
    create_arm_job(CellJobStore(path))
    monkeypatch.setattr(store_module, "_MIGRATION_VERSION", 3)  # per-arm tables only, no multi-arm filter
    with pytest.raises(RuntimeError, match="unsupported Cell Job journal migration version 5"):
        CellJobStore(path)


def test_an_arm_owner_is_never_driven_by_two_jobs(tmp_path):
    """Safety review 2026-10-17: every arm owner's workcell is a Job-level claim."""
    path, _, _, enabled = _stores(tmp_path)
    generation = enabled["generation"]
    cells = CellJobStore(path)
    create_arm_job(cells, pallet="pallet-2")
    _create(cells)  # a single-arm Job on omx_01, the left arm's owner, holds it first
    cells.admit("cell-mission-1", actor_id="operator-1", expected_generation=generation)
    with pytest.raises(MissionConflict):
        cells.admit("arm-job-1", actor_id="operator-1", expected_generation=generation)
    cells.cancel("cell-mission-1", actor_id="operator-2")
    cells.admit("arm-job-1", actor_id="operator-1", expected_generation=generation)
    # and the other way round: the multi-arm Job holds omx_02, a single-arm Job there is refused
    single_arm_job(cells, "omx_02")
    with pytest.raises(MissionConflict):
        cells.admit("cell-mission-1-omx_02", actor_id="operator-1", expected_generation=generation)
    create_arm_job(cells, "arm-job-2", pallet="pallet-3", cell="bench_02")  # same arm owners, another cell
    with pytest.raises(MissionConflict):
        cells.admit("arm-job-2", actor_id="operator-1", expected_generation=generation)
