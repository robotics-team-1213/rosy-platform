"""D-779 §3/§6 for multi-arm Cell Jobs: per-step goal evidence (per-arm predicates, D-781 §5),
per-arm resume (store and route), the tight-partner resume rule and the pair send rule (an
accepted arm is cancelled only when its step did not start on every arm)."""

import copy
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.cell_arm_dispatcher import PAIR_REASON
from fleet.server.cell_arm_jobs import PAIR_PARTIAL_REASON, TIGHT_PARTNER_REASON
from fleet.server.cell_arm_store import ArmJobStore
from fleet.server.cell_goal_evidence import attach_goal_predicates
from fleet.server.cell_goal_evidence_registry import CellGoalProducer, CellGoalRegistry
from fleet.server.cell_goal_evidence_service import CellGoalEvidenceService
from fleet.server.cell_job_routes import install_cell_job_routes
from fleet.server.goal_evidence_service import GoalEvidenceSubmissionError
from fleet.server.goal_evidence_store import GoalEvidenceStore
from fleet.server.local_action_transport import LocalActionRejected
from fleet.server.mission_store import MissionConflict
from fleet.server.site_auth import SitePrincipal

from test_cell_arm_dispatcher import LEFT, RIGHT, _action, _arms, _setup
from test_cell_arm_jobs import WORKCELL, arm_step, four_steps, single_arm_job
from test_cell_goal_evidence_service import GEOMETRY, _tolerance
from test_step_dispatcher import _receipt

INSTANCES = {"left": LEFT, "right": RIGHT}


def with_predicates(steps):
    """Each step's item_at_pose predicate, compiled in its first primary arm's frame."""
    steps = copy.deepcopy(steps)
    for step in steps:
        arm = step["placement"]["arm"]
        frame = arm if isinstance(arm, str) else arm[0]
        document = {"steps": [{"inputs": step["placement"]["actions"][frame]}]}
        attach_goal_predicates(document, GEOMETRY, _tolerance())
        step["goal_predicate"] = document["steps"][0]["goal_predicate"]
    return steps


def with_arm_predicates(steps):
    """Per-arm predicates (D-781 §5): one for every primary and alternate arm, from its own inputs."""
    steps = copy.deepcopy(steps)
    for step in steps:
        actions = step["placement"]["actions"]
        document = {"steps": [{"inputs": actions[role]} for role in sorted(actions)]}
        attach_goal_predicates(document, GEOMETRY, _tolerance())
        step["goal_predicates"] = {role: item["goal_predicate"]
                                   for role, item in zip(sorted(actions), document["steps"])}
    return steps


def goal_setup(tmp_path, steps, *, predicates=with_predicates):
    holder = {}
    path, cells, tasks, transport, dispatcher = _setup(
        tmp_path, steps=predicates(steps),
        on_step_action_succeeded=lambda job, index: (
            holder["service"].on_action_terminal(job["mission_id"]) if "service" in holder else None))
    producers = tuple(CellGoalProducer(
        producer_id=f"gazebo-pose-{role}", token=f"pose-secret-{role}", workcell_id=WORKCELL,
        instance_id=instance, recipe_sha256="a" * 64, cell_sha256="b" * 64,
        evaluator_revisions=("placement-v1",), max_age_s=5.0,
        valid_until=datetime.fromtimestamp(time.time() + 3600, timezone.utc)) for role, instance in INSTANCES.items())
    clock = [time.time()]
    service = CellGoalEvidenceService(cells, CellGoalRegistry(producers), GoalEvidenceStore(path),
                                      now=lambda: clock[0])
    holder["service"] = service
    return path, cells, tasks, transport, dispatcher, service, clock


def evidence(cells, index, role, evidence_id, observed_at):
    job = cells.get("arm-job-1")
    action = _action(job, index, role)
    peers = [a for a in job["step_actions"] if a["step_index"] == index and a["grant"] is not None]
    issued = max(datetime.fromisoformat(a["grant"]["issued_at"].replace("Z", "+00:00")).timestamp() for a in peers)
    grant = action["grant"]
    return {
        "producer_id": f"gazebo-pose-{role}", "evidence_id": evidence_id,
        "evidence_source": "sim_model_pose", "evaluator_revision": "placement-v1",
        "job_id": job["job_id"], "step_id": job["steps"][index]["step_id"], "step_index": index,
        "action_id": action["action_id"], "attempt_id": action["attempt_id"],
        "request_digest": action["request_digest"], "recipe_sha256": grant["cell_transfer"]["recipe_sha256"],
        "cell_sha256": grant["cell_transfer"]["cell_sha256"], "model_id": "cell_" + action["action_id"],
        "observation_id": f"{evidence_id}-pose", "observation_digest": "d" * 64,
        "evidence_revision": "world-base-v1", "observed_at": observed_at,
        "model_pose_base": {"x_m": .4, "y_m": .5, "z_m": .3, "roll_rad": 0., "pitch_rad": 0., "yaw_rad": 1.57},
        "initial_observation_id": f"{evidence_id}-initial", "initial_observation_digest": "c" * 64,
        "initial_observed_at": issued,
        "initial_model_pose_base": {"x_m": .1, "y_m": .2, "z_m": .3, "roll_rad": 0., "pitch_rad": 0., "yaw_rad": 0.},
        "gripper_state": "OPEN", "gripper_evidence_id": f"{evidence_id}-gripper",
        "gripper_evidence_revision": "joint-readback-v1", "gripper_observed_at": observed_at,
    }


def submit(service, clock, cells, index, role, evidence_id, *, token_role=None):
    observed = time.time() + .01
    clock[0] = observed + .01
    return service.submit(token=f"pose-secret-{token_role or role}", mission_id="arm-job-1",
                          raw_evidence=evidence(cells, index, role, evidence_id, observed))


def claims(path):
    with closing(sqlite3.connect(path)) as connection:
        return dict(connection.execute("SELECT resource_key, phase FROM fleet_action_claims "
                                       "WHERE owner_id='arm-job-1'").fetchall())


# Goal evidence (D-779 §3) -------------------------------------------------------------------------
@pytest.mark.parametrize("predicates", [with_predicates, with_arm_predicates])
def test_goal_evidence_confirms_a_step_and_opens_its_dependents(tmp_path, predicates):
    path, cells, _, transport, dispatcher, service, clock = goal_setup(tmp_path, four_steps(), predicates=predicates)
    dispatcher.dispatch_next()
    transport.answer(LEFT, "SUCCEEDED")
    dispatcher.dispatch_next()
    observed = time.time() + .01
    clock[0] = observed + .01
    raw = evidence(cells, 0, "left", "goal-0", observed)
    result = service.submit(token="pose-secret-left", mission_id="arm-job-1", raw_evidence=raw)
    assert result["state"] == "RUNNING"  # the right arm still runs step 1
    job = cells.get("arm-job-1")
    assert job["steps"][0]["status"] == "GOAL_CONFIRMED" and job["steps"][0]["goal_evidence"]["satisfied"] is True
    assert job["steps"][1]["status"] == "RUNNING" and job["current_step_index"] == 1
    dispatcher.dispatch_next()
    assert transport.submissions[-1].cell_transfer.step_index == 2  # depends_on [0] is open now
    replay = service.submit(token="pose-secret-left", mission_id="arm-job-1", raw_evidence=raw)
    assert replay["created"] is False and cells.get("arm-job-1")["steps"][0]["status"] == "GOAL_CONFIRMED"


def test_every_step_confirmed_ends_the_job_and_frees_its_claims(tmp_path):
    steps = [arm_step(0, "left", "left_half", []), arm_step(1, "right", "right_half", [])]
    path, cells, _, transport, dispatcher, service, clock = goal_setup(tmp_path, steps)
    dispatcher.dispatch_next()
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 10)
    dispatcher.dispatch_next()
    assert submit(service, clock, cells, 0, "left", "goal-0")["state"] == "READY"
    assert submit(service, clock, cells, 1, "right", "goal-1")["state"] == "GOAL_CONFIRMED"
    job = cells.get("arm-job-1")
    assert job["status"] == "GOAL_CONFIRMED" and job["current_step_index"] == 2
    assert job["events"][-1]["event_type"] == "CELL_JOB_GOAL_CONFIRMED"
    assert claims(path) == {}


def test_a_coordinated_step_waits_for_every_arm_and_the_hook_applies_stored_evidence(tmp_path):
    pair = arm_step(0, ["left", "right"], "shared_band", [], coupling="tight")
    path, cells, _, transport, dispatcher, service, clock = goal_setup(
        tmp_path, [pair, arm_step(1, "right", "right_half", [0])])
    dispatcher.dispatch_next()
    transport.answer(LEFT, "SUCCEEDED")
    dispatcher.dispatch_next()
    assert cells.get("arm-job-1")["steps"][0]["status"] == "RUNNING"
    later = time.time() + 2  # observed after the right arm's success, which comes below
    clock[0] = later + .01
    pending = service.submit(token="pose-secret-left", mission_id="arm-job-1",
                             raw_evidence=evidence(cells, 0, "left", "goal-pair", later))
    assert pending["state"] == "PENDING_ACTION_TERMINAL"
    with pytest.raises(GoalEvidenceSubmissionError) as refused:  # only the predicate arm's Action
        service.submit(token="pose-secret-right", mission_id="arm-job-1",
                       raw_evidence=evidence(cells, 0, "right", "goal-pair-right", later))
    assert refused.value.code == "EVIDENCE_SCOPE_MISMATCH"
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 11)
    dispatcher.dispatch_next()  # the right arm's success applies the stored evidence
    job = cells.get("arm-job-1")
    assert job["steps"][0]["status"] == "GOAL_CONFIRMED"
    dispatcher.dispatch_next()
    assert transport.submissions[-1].cell_transfer.step_index == 1


def test_a_failed_partner_keeps_the_coordinated_step_unconfirmed(tmp_path):
    pair = arm_step(0, ["left", "right"], "shared_band", [], coupling="tight")
    path, cells, _, transport, dispatcher, service, clock = goal_setup(tmp_path, [pair])
    dispatcher.dispatch_next()
    transport.answer(LEFT, "SUCCEEDED")
    dispatcher.dispatch_next()
    transport.answer(RIGHT, "FAILED")
    dispatcher.dispatch_next()
    result = submit(service, clock, cells, 0, "left", "goal-0")
    assert result["state"] == "PENDING_ACTION_TERMINAL"
    assert cells.get("arm-job-1")["steps"][0]["status"] == "HOLD"


@pytest.mark.parametrize("mutation", ["producer_instance", "model", "attempt", "pre_grant"])
def test_invalid_multi_arm_evidence_changes_nothing(tmp_path, mutation):
    path, cells, _, transport, dispatcher, service, clock = goal_setup(tmp_path, four_steps())
    dispatcher.dispatch_next()
    transport.answer(LEFT, "SUCCEEDED")
    dispatcher.dispatch_next()
    observed = time.time() + .01
    clock[0] = observed + .01
    raw = evidence(cells, 0, "left", "goal-bad", observed)
    token = "pose-secret-left"
    if mutation == "producer_instance":  # the right arm's producer is not registered for the left arm
        token, raw["producer_id"] = "pose-secret-right", "gazebo-pose-right"
    elif mutation == "model":
        raw["model_id"] = "cell_other"
    elif mutation == "attempt":
        raw["attempt_id"] = "other-attempt"
    else:
        raw["initial_observed_at"] -= 1
    before = cells.get("arm-job-1")
    with pytest.raises(GoalEvidenceSubmissionError):
        service.submit(token=token, mission_id="arm-job-1", raw_evidence=raw)
    assert cells.get("arm-job-1") == before
    assert service.store.get("goal-bad") is None


def _alternate_run(tmp_path, predicates, primary_shift_m=0.0):
    """Step 0 belongs to the left arm with the right arm as alternate; the left arm is taken out,
    so the right arm runs it. ``primary_shift_m`` moves only the LEFT arm's place pose."""
    step = arm_step(0, "left", "left_half", [], alternates=["right"])
    step["placement"]["actions"]["left"]["destination_pose_base"]["x_m"] += primary_shift_m
    setup = goal_setup(tmp_path, [step], predicates=predicates)
    _, cells, _, transport, dispatcher, _, _ = setup
    ArmJobStore(cells).set_arm_offline("arm-job-1", arm_role="left", actor_id="operator-2", reason="OWNER_REAPPROVAL")
    dispatcher.dispatch_next()
    transport.answer(RIGHT, "SUCCEEDED")
    dispatcher.dispatch_next()
    assert cells.get("arm-job-1")["placements"][0]["assigned"] == ["right"]
    assert cells.get("arm-job-1")["steps"][0]["status"] == "ACTION_SUCCEEDED"
    return setup


def test_an_alternate_arm_step_is_judged_with_the_alternate_arms_predicate(tmp_path):
    # The left (primary) predicate is 0.1 m off the observed pose; only the right arm's own matches.
    path, cells, _, transport, dispatcher, service, clock = _alternate_run(tmp_path, with_arm_predicates, 0.1)
    job = cells.get("arm-job-1")
    stored = job["steps"][0]["step"]["goal_predicates"]
    assert stored["left"]["target"]["x"] == pytest.approx(stored["right"]["target"]["x"] + 0.1)
    with pytest.raises(GoalEvidenceSubmissionError) as refused:  # the primary arm's producer is not in scope
        submit(service, clock, cells, 0, "right", "goal-alt-left", token_role="left")
    assert refused.value.code == "PRODUCER_SCOPE_MISMATCH"
    result = submit(service, clock, cells, 0, "right", "goal-alt")
    assert result["state"] == "GOAL_CONFIRMED"
    job = cells.get("arm-job-1")
    assert job["steps"][0]["status"] == "GOAL_CONFIRMED"
    assert job["steps"][0]["goal_evidence"]["predicate"]["target"]["x"] == pytest.approx(stored["right"]["target"]["x"])


def test_an_alternate_arm_step_off_its_own_pose_is_not_confirmed(tmp_path):
    # Mirror of the above: the alternate's own predicate is off, the primary's would match.
    step = arm_step(0, "left", "left_half", [], alternates=["right"])
    step["placement"]["actions"]["right"]["destination_pose_base"]["x_m"] += 0.1
    path, cells, _, transport, dispatcher, service, clock = goal_setup(tmp_path, [step], predicates=with_arm_predicates)
    ArmJobStore(cells).set_arm_offline("arm-job-1", arm_role="left", actor_id="operator-2", reason="OWNER_REAPPROVAL")
    dispatcher.dispatch_next()
    transport.answer(RIGHT, "SUCCEEDED")
    dispatcher.dispatch_next()
    with pytest.raises(GoalEvidenceSubmissionError) as refused:
        submit(service, clock, cells, 0, "right", "goal-alt")
    assert refused.value.code == "CELL_GOAL_NOT_AT_POSE"
    assert cells.get("arm-job-1")["steps"][0]["status"] == "ACTION_SUCCEEDED"


def test_an_alternate_arm_step_without_a_predicate_in_its_frame_is_refused(tmp_path):
    # Only the legacy single predicate (the primary arm's frame) is stored: it never judges an alternate.
    path, cells, _, transport, dispatcher, service, clock = _alternate_run(tmp_path, with_predicates)
    with pytest.raises(GoalEvidenceSubmissionError) as refused:
        submit(service, clock, cells, 0, "right", "goal-alt")
    assert refused.value.code == "CELL_GOAL_PREDICATE_MISSING"
    assert cells.get("arm-job-1")["steps"][0]["status"] == "ACTION_SUCCEEDED"
    assert service.store.get("goal-alt") is None


# Per-arm resume (D-779 §6) ------------------------------------------------------------------------
def test_a_tight_partner_resumes_only_after_its_partner(tmp_path):
    pair = arm_step(0, ["left", "right"], "shared_band", [], coupling="tight")
    path, cells, tasks, transport, dispatcher = _setup(tmp_path, steps=[pair])
    dispatcher.dispatch_next()
    transport.answer(LEFT, "FAILED")
    dispatcher.dispatch_next()
    transport.answer(RIGHT, "SUCCEEDED")
    dispatcher.dispatch_next()
    arms, generation = ArmJobStore(cells), tasks.dispatch_control()["generation"]
    assert _arms(cells.get("arm-job-1"))["right"] == ("HOLD", TIGHT_PARTNER_REASON)
    with pytest.raises(MissionConflict, match="tight partner"):
        arms.resume_arm("arm-job-1", arm_role="right", actor_id="operator-2", expected_generation=generation)
    arms.resume_arm("arm-job-1", arm_role="left", actor_id="operator-2", expected_generation=generation)
    job = arms.resume_arm("arm-job-1", arm_role="right", actor_id="operator-2", expected_generation=generation)
    assert _arms(job) == {"left": ("READY", None), "right": ("READY", None)}
    assert _action(job, 0, "right")["status"] == "ACTION_SUCCEEDED"  # its success is kept, never resent
    assert _action(job, 0, "left")["status"] == "READY"
    assert (job["steps"][0]["status"], job["steps"][0]["reason"]) == ("HOLD", PAIR_PARTIAL_REASON)  # visible
    dispatcher.dispatch_next()  # a coordinated step never restarts one arm alone
    assert len(transport.submissions) == 2


def _route_client(cells):
    app = FastAPI()
    operator = SitePrincipal(principal_id="operator-2", role="operator")
    install_cell_job_routes(app, cell_job_store=cells, proposal_store=None, require_viewer=lambda: operator,
                            require_named_operator=lambda: operator, operator_guard=[], read_guard=[])
    return TestClient(app)


def test_the_arm_resume_route_resumes_one_held_arm(tmp_path):
    path, cells, tasks, transport, dispatcher = _setup(tmp_path)
    single_arm_job(cells)
    dispatcher.dispatch_next()
    transport.answer(LEFT, "FAILED")
    dispatcher.dispatch_next()
    client = _route_client(cells)
    generation = tasks.dispatch_control()["generation"]
    base = "/api/fleet/cell-jobs/arm-job-1/arms"
    assert client.post(f"{base}/left/resume", json={"expected_generation": generation + 1}).status_code == 409
    assert client.post(f"{base}/right/resume", json={"expected_generation": generation}).status_code == 409
    assert client.post(f"{base}/middle/resume", json={"expected_generation": generation}).status_code == 409
    assert client.post("/api/fleet/cell-jobs/cell-mission-1/arms/left/resume",
                       json={"expected_generation": generation}).status_code == 409  # single-arm Job
    assert client.post("/api/fleet/cell-jobs/nope/arms/left/resume",
                       json={"expected_generation": generation}).status_code == 404
    resumed = client.post(f"{base}/left/resume", json={"expected_generation": generation})
    assert resumed.status_code == 200
    job = resumed.json()["job"]
    assert {arm["arm_role"]: arm["status"] for arm in job["arms"]} == {"left": "READY", "right": "RUNNING"}
    assert "proposal_principal_id" not in job  # redacted: the operator is not the proposer
    again = client.post(f"{base}/left/resume", json={"expected_generation": generation})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "CELL_JOB_RECOVERY_REFUSED"


# Pair send rule (D-778 §4) ------------------------------------------------------------------------
def test_a_pair_both_accepted_is_never_cancelled(tmp_path):
    pair = arm_step(0, ["left", "right"], "shared_band", [])
    path, cells, _, transport, dispatcher = _setup(tmp_path, steps=[pair])
    dispatcher.dispatch_next()
    assert sorted(g.instance_id for g in transport.submissions) == [LEFT, RIGHT]
    assert transport.cancels == []


def test_an_arm_that_succeeded_at_once_is_not_cancelled_when_its_partner_refuses(tmp_path):
    pair = arm_step(0, ["left", "right"], "shared_band", [])
    path, cells, tasks, transport, dispatcher = _setup(tmp_path, steps=[pair])

    def submit_grant(grant):
        transport.submissions.append(grant)
        if grant.instance_id == RIGHT:
            raise LocalActionRejected("GRANT_REJECTED: busy")
        return _receipt(grant, "SUCCEEDED", 5)

    transport.submit = submit_grant
    dispatcher.dispatch_next()
    assert transport.cancels == []
    job = cells.get("arm-job-1")
    assert _action(job, 0, "left")["status"] == "ACTION_SUCCEEDED" and _arms(job)["right"][0] == "HOLD"
    ArmJobStore(cells).resume_arm("arm-job-1", arm_role="right", actor_id="operator-2",
                                  expected_generation=tasks.dispatch_control()["generation"])
    dispatcher.dispatch_next()
    assert len(transport.submissions) == 2  # the half-done pair is not restarted on one arm


def test_an_error_between_the_sends_cancels_the_sent_arm_and_holds_the_unsent_one(tmp_path, monkeypatch):
    pair = arm_step(0, ["left", "right"], "shared_band", [])
    path, cells, _, transport, dispatcher = _setup(tmp_path, steps=[pair])
    apply = dispatcher.arms._apply

    def broken(job, index, grant, receipt):
        apply(job, index, grant, receipt)
        raise RuntimeError("ledger write failed after the left send")

    monkeypatch.setattr(dispatcher.arms, "_apply", broken)
    with pytest.raises(RuntimeError):
        dispatcher.dispatch_next()
    assert [g.instance_id for g in transport.submissions] == [LEFT]
    assert transport.cancels == [(LEFT, PAIR_REASON)]
    job = cells.get("arm-job-1")
    assert _action(job, 0, "right")["status"] == "HOLD" and _action(job, 0, "right")["reason"] == PAIR_REASON
    assert claims(path)[f"arm:{WORKCELL}.right"] == "HELD"
    assert _action(job, 0, "left")["status"] == "RUNNING"  # read back, settled by the device


def test_an_unknown_second_send_cancels_both_arms_that_may_run(tmp_path):
    pair = arm_step(0, ["left", "right"], "shared_band", [])
    path, cells, _, transport, dispatcher = _setup(tmp_path, steps=[pair])
    accept = transport.on_submit

    def submit_grant(grant):
        transport.submissions.append(grant)
        if grant.instance_id == RIGHT:
            raise TimeoutError("response lost")
        return accept(grant)

    transport.submit = submit_grant
    dispatcher.dispatch_next()
    assert sorted(transport.cancels) == [(LEFT, PAIR_REASON), (RIGHT, PAIR_REASON)]
    job = cells.get("arm-job-1")
    assert _arms(job)["right"] == ("HOLD", "LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN")
    assert claims(path)[f"arm:{WORKCELL}.right"] == "UNKNOWN"  # read back before any resume
