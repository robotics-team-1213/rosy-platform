"""D-779 stages 3-4: the multi-arm dispatcher (per-arm ready set, arm/zone claims, per-arm outcomes)."""

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from fleet.server.cell_arm_dispatcher import PAIR_REASON, CellJobDispatcher, pair_fields
from fleet.server.cell_arm_jobs import TIGHT_PARTNER_REASON
from fleet.server.cell_arm_store import ArmJobStore
from fleet.server.cell_job_store import CellJobStore
from fleet.server.local_action_transport import LocalActionRejected
from fleet.server.mission_store import MissionConflict
from fleet.server.step_dispatcher import MAX_IO_PER_TICK, StepJobDispatcher

from test_cell_arm_jobs import WORKCELL, arm_step, create_arm_job, four_steps
from test_cell_job_store import _create, _goal, _stores
from test_step_dispatcher import Transport, _receipt

OMX = {"omx_01": "omx_01_control", "omx_02": "omx_02_control"}  # each arm owner is its own instance
REVISIONS = {instance: {"capability_revision": "cell-transfer-v1", "config_revision": "cell-config-v1"}
             for instance in OMX.values()}
LEFT, RIGHT = "omx_01_control", "omx_02_control"
OWNER_CLAIMS = {"workcell:omx_01": "CLAIMED", "workcell:omx_02": "CLAIMED"}  # Job-level, admission to end


class ArmTransport(Transport):
    """Per-instance device answers; records cancels (the pair rule may cancel)."""

    def __init__(self):
        super().__init__()
        self.cancels, self.results = [], {}
        self.on_get = lambda grant: self.results.get(grant.instance_id, _receipt(grant, "RUNNING", 3,
                                                                                  phases=("approach",)))

    def cancel(self, grant, *, reason):
        self.cancels.append((grant.instance_id, reason))
        return _receipt(grant, "CANCEL_REQUESTED", 4, phases=("approach",))

    def answer(self, instance, state, event_id=10):
        self.on_get = lambda grant: (_receipt(grant, state, event_id) if grant.instance_id == instance
                                     else _receipt(grant, "RUNNING", 3, phases=("approach",)))


def _setup(tmp_path, steps=None, **kwargs):
    path, tasks, _, enabled = _stores(tmp_path)
    cells = CellJobStore(path)
    create_arm_job(cells, steps=steps)
    cells.admit("arm-job-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = ArmTransport()
    dispatcher = CellJobDispatcher(cells, tasks, transport, OMX, REVISIONS, deployment_profile="simulation",
                                   **kwargs)
    return path, cells, tasks, transport, dispatcher


def _claims(path):
    with closing(sqlite3.connect(path)) as connection:
        return dict(connection.execute("SELECT resource_key, phase FROM fleet_action_claims "
                                       "WHERE owner_id='arm-job-1'").fetchall())


def _arms(job):
    return {arm["arm_role"]: (arm["status"], arm["reason"]) for arm in job["arms"]}


def _action(job, index, role):
    return next(a for a in job["step_actions"] if a["step_index"] == index and a["arm_role"] == role)


def _confirm(cells, index, role):
    action = _action(cells.get("arm-job-1"), index, role)
    return ArmJobStore(cells).confirm_step_goal(
        "arm-job-1", step_index=index, action_id=action["action_id"], attempt_id=action["attempt_id"],
        evidence=_goal(action["action_id"], action["attempt_id"], f"goal-{index}-{role}"))


def test_two_arms_dispatch_concurrently_in_their_own_zones(tmp_path):
    path, cells, _, transport, dispatcher = _setup(tmp_path)
    dispatcher.dispatch_next()
    assert sorted((g.instance_id, g.workcell_id, g.cell_transfer.step_index) for g in transport.submissions) == [
        (LEFT, "omx_01", 0), (RIGHT, "omx_02", 1)]
    job = cells.get("arm-job-1")
    assert job["status"] == "RUNNING" and _arms(job) == {"left": ("RUNNING", None), "right": ("RUNNING", None)}
    assert _claims(path) == {
        f"arm:{WORKCELL}.left": "DISPATCHING", f"arm:{WORKCELL}.right": "DISPATCHING",
        f"zone:{WORKCELL}.left_half": "DISPATCHING", f"zone:{WORKCELL}.right_half": "DISPATCHING",
        "pallet:pallet-1": "CLAIMED", f"workcell:{WORKCELL}": "CLAIMED", **OWNER_CLAIMS}
    dispatcher.dispatch_next()
    assert len(transport.submissions) == 2  # read back, never resubmitted
    assert len(transport.lookups) == 2


def test_success_frees_only_that_actions_keys_and_depends_on_waits_for_the_goal(tmp_path):
    path, cells, _, transport, dispatcher = _setup(tmp_path)
    dispatcher.dispatch_next()
    transport.answer(LEFT, "SUCCEEDED")
    dispatcher.dispatch_next()
    job = cells.get("arm-job-1")
    assert _action(job, 0, "left")["status"] == "ACTION_SUCCEEDED" and job["steps"][0]["status"] == "ACTION_SUCCEEDED"
    assert _arms(job)["left"] == ("READY", None)
    assert f"arm:{WORKCELL}.left" not in _claims(path) and f"zone:{WORKCELL}.left_half" not in _claims(path)
    assert _claims(path)[f"zone:{WORKCELL}.right_half"] == "DISPATCHING"
    dispatcher.dispatch_next()  # step 2 depends on step 0's goal, not its Action success
    assert len(transport.submissions) == 2
    _confirm(cells, 0, "left")
    dispatcher.dispatch_next()
    assert [g.cell_transfer.step_index for g in transport.submissions][-1] == 2
    assert _claims(path)[f"zone:{WORKCELL}.shared_band"] == "DISPATCHING"


def test_a_shared_zone_takes_one_arm_at_a_time(tmp_path):
    path, cells, _, transport, dispatcher = _setup(tmp_path)
    dispatcher.dispatch_next()
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 10)
    dispatcher.dispatch_next()
    _confirm(cells, 0, "left")
    _confirm(cells, 1, "right")
    transport.on_get = lambda grant: _receipt(grant, "RUNNING", 3, phases=("approach",))
    dispatcher.dispatch_next()
    dispatcher.dispatch_next()
    shared = [g for g in transport.submissions if g.cell_transfer.step_index in {2, 3}]
    assert len(shared) == 1  # both are ready; the shared band admits one
    waiting = 3 if shared[0].cell_transfer.step_index == 2 else 2
    assert cells.get("arm-job-1")["steps"][waiting]["status"] == "READY"
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 11)
    dispatcher.dispatch_next()
    dispatcher.dispatch_next()
    assert sorted(g.cell_transfer.step_index for g in transport.submissions) == [0, 1, 2, 3]


def test_a_failed_arm_holds_alone_and_resumes_alone(tmp_path):
    path, cells, tasks, transport, dispatcher = _setup(tmp_path)
    dispatcher.dispatch_next()
    transport.answer(LEFT, "FAILED")
    dispatcher.dispatch_next()
    job = cells.get("arm-job-1")
    assert _arms(job) == {"left": ("HOLD", "LOCAL_ACTION_FAILED"), "right": ("RUNNING", None)}
    assert job["status"] == "RUNNING" and job["steps"][0]["status"] == "HOLD"
    claims = _claims(path)
    assert claims[f"arm:{WORKCELL}.left"] == claims[f"zone:{WORKCELL}.left_half"] == "HELD"
    assert claims[f"arm:{WORKCELL}.right"] == "DISPATCHING" and claims[f"workcell:{WORKCELL}"] == "CLAIMED"
    # the other arm finishes and goes on; the held arm and its zone stay held
    transport.answer(RIGHT, "SUCCEEDED")
    dispatcher.dispatch_next()
    _confirm(cells, 1, "right")
    dispatcher.dispatch_next()
    assert transport.submissions[-1].cell_transfer.step_index == 3
    generation = tasks.dispatch_control()["generation"]
    resumed = ArmJobStore(cells).resume_arm("arm-job-1", arm_role="left", actor_id="operator-2",
                                            expected_generation=generation)
    assert _arms(resumed)["left"] == ("READY", None) and _action(resumed, 0, "left")["status"] == "READY"
    assert f"arm:{WORKCELL}.left" not in _claims(path)
    first = transport.submissions[0].action_id
    dispatcher.dispatch_next()
    again = [g for g in transport.submissions if g.cell_transfer.step_index == 0]
    assert len(again) == 2 and again[1].action_id != first  # a new attempt, never the old one


def test_an_unknown_arm_outcome_is_read_back_and_blocks_its_resume(tmp_path):
    path, cells, tasks, transport, dispatcher = _setup(tmp_path, steps=[arm_step(0, "left", "left_half", [])])

    def lost(grant):
        transport.submissions.append(grant)
        raise TimeoutError("response lost")

    transport.submit = lost
    dispatcher.dispatch_next()
    job = cells.get("arm-job-1")
    assert _arms(job)["left"] == ("HOLD", "LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN") and job["status"] == "READY"
    assert _claims(path)[f"arm:{WORKCELL}.left"] == "UNKNOWN"
    with pytest.raises(MissionConflict):
        ArmJobStore(cells).resume_arm("arm-job-1", arm_role="left", actor_id="operator-2",
                                      expected_generation=tasks.dispatch_control()["generation"])
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 20)
    dispatcher.dispatch_next()
    job = cells.get("arm-job-1")
    assert _arms(job)["left"] == ("READY", None) and _action(job, 0, "left")["status"] == "ACTION_SUCCEEDED"
    assert f"arm:{WORKCELL}.left" not in _claims(path)
    assert len(transport.submissions) == 1


def test_not_found_after_expiry_means_never_ran_and_parks_the_arm(tmp_path):
    clock = {"now": datetime.now(timezone.utc)}
    path, cells, _, transport, dispatcher = _setup(
        tmp_path, steps=[arm_step(0, "left", "left_half", [])], now=lambda: clock["now"])

    def lost(grant):  # no receipt ever: only then can a 404 mean "never ran" (1c item 3)
        transport.submissions.append(grant)
        raise TimeoutError("response lost")

    transport.submit = lost
    dispatcher.dispatch_next()
    assert _claims(path)[f"arm:{WORKCELL}.left"] == "UNKNOWN"
    transport.on_get = lambda grant: None
    clock["now"] += timedelta(seconds=30)
    dispatcher.dispatch_next()
    job = cells.get("arm-job-1")
    assert _arms(job)["left"] == ("HOLD", "LOCAL_ACTION_NOT_FOUND_AFTER_SUBMIT")
    assert _claims(path)[f"arm:{WORKCELL}.left"] == "HELD"


def test_a_tight_step_holds_both_arms_and_settles_the_partner_by_readback(tmp_path):
    pair = arm_step(0, ["left", "right"], "shared_band", [], coupling="tight")
    path, cells, _, transport, dispatcher = _setup(tmp_path, steps=[pair, arm_step(1, "right", "right_half", [])])
    dispatcher.dispatch_next()
    assert sorted(g.instance_id for g in transport.submissions) == [LEFT, RIGHT]
    transport.answer(LEFT, "FAILED")
    dispatcher.dispatch_next()
    job = cells.get("arm-job-1")
    assert _arms(job) == {"left": ("HOLD", "LOCAL_ACTION_FAILED"), "right": ("HOLD", TIGHT_PARTNER_REASON)}
    assert job["status"] == "HOLD"
    claims = _claims(path)
    assert claims[f"arm:{WORKCELL}.left"] == "HELD"
    assert claims[f"arm:{WORKCELL}.right"] == claims[f"zone:{WORKCELL}.shared_band"] == "UNKNOWN"
    transport.answer(RIGHT, "SUCCEEDED")
    dispatcher.dispatch_next()  # the partner's own success keeps it parked with its tight partner
    job = cells.get("arm-job-1")
    assert _arms(job)["right"] == ("HOLD", TIGHT_PARTNER_REASON) and _action(job, 0, "right")["status"] == "HOLD"
    assert set(_claims(path).values()) == {"HELD", "CLAIMED"}
    assert not any(g.cell_transfer.step_index == 1 for g in transport.submissions)


def test_an_alternate_arm_takes_a_held_arms_step_in_one_arm_mode(tmp_path):
    steps = [arm_step(0, "left", "left_half", [], alternates=["right"]), arm_step(1, "left", "left_half", [0])]
    path, cells, tasks, transport, dispatcher = _setup(tmp_path, steps=steps)
    ArmJobStore(cells).set_arm_offline("arm-job-1", arm_role="left", actor_id="operator-2", reason="OWNER_REAPPROVAL")
    dispatcher.dispatch_next()
    assert [(g.instance_id, g.cell_transfer.step_index) for g in transport.submissions] == [(RIGHT, 0)]
    job = cells.get("arm-job-1")
    assert job["placements"][0]["assigned"] == ["right"]
    event = next(e for e in job["events"] if e["event_type"] == "CELL_STEP_ALTERNATE_ARM")
    assert event["detail"]["primary_arm"] == "left" and event["detail"]["primary_status"] == "OFFLINE"
    transport.answer(RIGHT, "SUCCEEDED")
    dispatcher.dispatch_next()
    _confirm(cells, 0, "right")
    dispatcher.dispatch_next()  # step 1 has no alternate: it waits for its arm
    assert len(transport.submissions) == 1
    ArmJobStore(cells).resume_arm("arm-job-1", arm_role="left", actor_id="operator-2",
                                  expected_generation=tasks.dispatch_control()["generation"])
    dispatcher.dispatch_next()
    assert [(g.instance_id, g.cell_transfer.step_index) for g in transport.submissions][-1] == (LEFT, 1)
    assert cells.get("arm-job-1")["placements"][0]["assigned"] == ["right"]  # never reverted


def test_a_pair_where_one_owner_refuses_cancels_the_other(tmp_path):
    pair = arm_step(0, ["left", "right"], "shared_band", [], coupling="independent")
    path, cells, _, transport, dispatcher = _setup(tmp_path, steps=[pair])
    accept = transport.on_submit

    def submit(grant):
        if grant.instance_id == RIGHT:
            transport.submissions.append(grant)
            raise LocalActionRejected("GRANT_REJECTED: busy")
        return accept(grant)

    transport.submit = lambda grant: (transport.submissions.append(grant) or accept(grant)
                                      ) if grant.instance_id == LEFT else submit(grant)
    dispatcher.dispatch_next()
    assert transport.cancels == [(LEFT, PAIR_REASON)]
    job = cells.get("arm-job-1")
    assert _arms(job)["right"] == ("HOLD", "LOCAL_ACTION_REJECTED")
    assert _action(job, 0, "left")["status"] == "RUNNING"  # its cancel is settled by readback


def test_site_stop_holds_idle_arms_and_a_late_success_parks(tmp_path):
    steps = [arm_step(0, "left", "left_half", []), arm_step(1, "right", "right_half", [0])]
    path, cells, tasks, transport, dispatcher = _setup(tmp_path, steps=steps)
    dispatcher.dispatch_next()
    tasks.trip_stop_latch(actor_id="operator-2")
    job = cells.get("arm-job-1")
    assert _arms(job) == {"left": ("RUNNING", None), "right": ("HOLD", "site_stop")} and job["status"] == "RUNNING"
    claims = _claims(path)
    assert claims[f"arm:{WORKCELL}.left"] == claims[f"zone:{WORKCELL}.left_half"] == "DISPATCHING"
    assert claims[f"workcell:{WORKCELL}"] == claims["pallet:pallet-1"] == "HELD"
    transport.answer(LEFT, "SUCCEEDED")
    dispatcher.dispatch_next()
    job = cells.get("arm-job-1")
    assert _arms(job)["left"] == ("HOLD", "site_stop") and job["status"] == "HOLD"
    assert set(_claims(path).values()) == {"HELD"}
    control = tasks.dispatch_control()
    rearmed = tasks.rearm_dispatch(expected_generation=control["generation"], actor_id="operator-2")
    resumed = ArmJobStore(cells).resume("arm-job-1", actor_id="operator-2", expected_generation=rearmed["generation"])
    assert resumed["status"] == "READY" and _action(resumed, 0, "left")["status"] == "ACTION_SUCCEEDED"
    assert _claims(path) == {"pallet:pallet-1": "CLAIMED", f"workcell:{WORKCELL}": "CLAIMED", **OWNER_CLAIMS}
    dispatcher.dispatch_next()
    assert len(transport.submissions) == 1  # the transfer is never sent again; goal evidence decides


def test_startup_recovery_holds_every_arm_and_pins_in_flight_claims(tmp_path):
    path, cells, tasks, transport, dispatcher = _setup(tmp_path)
    dispatcher.dispatch_next()
    tasks.close_dispatch_for_startup()
    restarted = CellJobStore(path)
    assert restarted.recover_after_startup() == 1
    job = restarted.get("arm-job-1")
    assert job["status"] == "HOLD" and set(_arms(job).values()) == {("HOLD", "SITE_AUTHORITY_CHANGED")}
    assert {_claims(path)[f"arm:{WORKCELL}.{role}"] for role in ("left", "right")} == {"UNKNOWN"}
    with pytest.raises(MissionConflict):
        ArmJobStore(restarted).resume("arm-job-1", actor_id="operator-2",
                                      expected_generation=tasks.dispatch_control()["generation"])
    again = CellJobDispatcher(restarted, tasks, transport, OMX, REVISIONS, deployment_profile="simulation")
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 30)
    again.dispatch_next()
    job = restarted.get("arm-job-1")
    assert set(_arms(job).values()) == {("HOLD", "SITE_AUTHORITY_CHANGED")}  # old fence: parked
    assert {phase for key, phase in _claims(path).items() if key.startswith(("arm:", "zone:"))} == {"HELD"}
    assert len(transport.submissions) == 2


def test_the_io_cap_counts_arm_actions(tmp_path):
    pair = arm_step(0, ["left", "right"], "shared_band", [])
    path, cells, _, transport, dispatcher = _setup(tmp_path, steps=[pair])
    dispatcher.arms.io_floor = MAX_IO_PER_TICK - 4  # a pair: two exchanges per arm and one cancel
    assert dispatcher.arms.dispatch_next() is None and transport.submissions == []
    dispatcher.arms.io_floor = MAX_IO_PER_TICK - 5
    dispatcher.arms.dispatch_next()
    assert len(transport.submissions) == 2


def test_without_a_multi_arm_job_the_tick_is_the_single_arm_tick(tmp_path, monkeypatch):
    path, tasks, _, enabled = _stores(tmp_path)
    cells = CellJobStore(path)
    _create(cells)
    cells.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = ArmTransport()
    dispatcher = CellJobDispatcher(cells, tasks, transport, {"omx_01": "omx_01_control"},
                                   {"omx_01_control": REVISIONS[LEFT]}, deployment_profile="simulation")
    assert isinstance(dispatcher, StepJobDispatcher)
    monkeypatch.setattr(dispatcher.arms, "dispatch_next", lambda: pytest.fail("multi-arm pass ran"))
    first = dispatcher.dispatch_next()
    assert first["state"] == "ACCEPTED" and first["step_index"] == 0
    assert [g.instance_id for g in transport.submissions] == ["omx_01_control"]


def test_pair_fields_follow_the_installed_grant_model():
    class Legacy:
        model_fields = {"instance_id": None}

    class Paired:
        model_fields = {"arm_role": None, "pair_id": None, "partner_instance_id": None, "coupling": None}

    class Payload:
        @staticmethod
        def strongest_coupling():
            return "independent"

    assert pair_fields(Legacy, role="left", partner_instance=RIGHT, pair_id="p-1", coupling="tight",
                       payload=Payload()) == {}
    assert pair_fields(Paired, role="left", partner_instance=None, pair_id=None, coupling="independent",
                       payload=Payload()) == {"arm_role": "left"}
    assert pair_fields(Paired, role="left", partner_instance=RIGHT, pair_id="p-1", coupling="tight",
                       payload=Payload()) == {"arm_role": "left", "pair_id": "p-1", "partner_instance_id": RIGHT}
    assert pair_fields(Paired, role="left", partner_instance=RIGHT, pair_id="p-1", coupling="independent",
                       payload=Payload())["coupling"] == "independent"


def test_an_arm_whose_owner_is_configured_under_another_workcell_is_not_dispatched(tmp_path):
    path, cells, tasks, transport, _ = _setup(tmp_path)
    dispatcher = CellJobDispatcher(cells, tasks, transport, {"omx_09": LEFT, "omx_02": RIGHT}, REVISIONS,
                                   deployment_profile="simulation")
    dispatcher.dispatch_next()
    assert [g.instance_id for g in transport.submissions] == [RIGHT]  # the left owner's claim is omx_01


def test_a_stop_between_the_two_sends_of_a_pair_holds_the_unsent_arm(tmp_path):
    pair = arm_step(0, ["left", "right"], "shared_band", [], coupling="tight")
    path, cells, tasks, transport, dispatcher = _setup(tmp_path, steps=[pair])
    accept = transport.on_submit

    def submit(grant):
        transport.submissions.append(grant)
        tasks.trip_stop_latch(actor_id="operator-2")  # lands after the left send, before the right one
        return accept(grant)

    transport.submit = submit
    dispatcher.dispatch_next()
    assert [g.instance_id for g in transport.submissions] == [LEFT]
    assert transport.cancels == [(LEFT, PAIR_REASON)]
    job = cells.get("arm-job-1")
    assert _arms(job)["right"] == ("HOLD", "FLEET_FENCE_CHANGED_BEFORE_LOCAL_SUBMIT")
    assert _action(job, 0, "left")["status"] == "RUNNING"  # readback settles the cancelled left arm
    assert _claims(path)[f"arm:{WORKCELL}.right"] == "HELD"


def test_cancel_marks_every_arm_in_the_same_transaction(tmp_path):
    path, cells, _, _, _ = _setup(tmp_path)
    cancelled = ArmJobStore(cells).cancel("arm-job-1", actor_id="operator-2")
    assert {arm["status"] for arm in cancelled["arms"]} == {"HOLD"}
    assert {a["reason"] for a in cancelled["step_actions"]} == {"CANCELLED_BY_OPERATOR"}
    assert _claims(path) == {}
    assert [e["event_type"] for e in cancelled["events"]][-1] == "CELL_JOB_CANCELLED"
