"""D-763 6: a multi-step job holds one CORE trip lease from approval to its end (Fleet side)."""

from __future__ import annotations

import pytest

from fleet.server.console_view import TripAware
from fleet.server.trip_guard import install_trip_guard
from test_trip_lease import _do, _plan, _refused, _setup, _ticks

JOB = "job-3"
R = "rosy_60"  # test_trip_runner.Ports' robot
CAPS = {"controls": {"items": [{"kind": "base_velocity", "trip_lease": True, "trip_lease_job": True,
                                "goal_lease": True, "line_follow_authority_under_lease": True,
                                "line_follow_authority": True, "drive_modes": ["lane", "free"]}]}}


def _job_runner(**lease):
    runner, store, ports = _setup(lease={"required": True, "holder": "site-a", **lease})
    runner.authority.enabled = True
    lost = []

    async def on_job_lost(view, detail):
        lost.append((view["job_id"], detail))
    runner.lease.on_job_lost = on_job_lost
    return runner, store, ports, lost


def _held(**lease):
    runner, store, ports, lost = _job_runner(**lease)
    lease_view = _do(runner, runner.hold_job(R, JOB, "kim", CAPS))
    return runner, store, ports, lost, lease_view


def _caps(**base):
    item = {**CAPS["controls"]["items"][0], **base}
    return {"controls": {"items": [{k: v for k, v in item.items() if v is not None}]}}


# ---- approval gate (rev 2 Q10 a, b) ------------------------------------------------------------

@pytest.mark.parametrize("change,missing", [
    ({"lease": {"required": False}}, "fleet.trip_lease_required"),
    ({"authority": False}, "fleet.traffic.authority"),
    ({"lease": {"ttl_s": 5.0}}, "fleet.trip_lease_ttl_s"),   # the lease must outlive the 5 s authority
    ({"caps": _caps(trip_lease_job=None)}, "trip_lease_job"),
    ({"caps": _caps(goal_lease=None)}, "goal_lease"),
    ({"caps": _caps(trip_lease=None)}, "trip_lease"),
    ({"caps": _caps(line_follow_authority_under_lease=None)}, "line_follow_authority_under_lease"),
])
def test_a_job_takes_a_robot_only_with_every_bound_on(change, missing):
    runner, _, ports, _ = _job_runner(**change.get("lease", {}))
    runner.authority.enabled = change.get("authority", True)
    err = _refused(runner, runner.hold_job(R, JOB, "kim", change.get("caps", CAPS)))
    assert (err.status, err.code) == (422, "LINK_UNBOUNDED_MOTION") and missing in err.detail["missing"]
    assert ports.lease.puts == [] and runner.lease.job_of(R) is None


@pytest.mark.parametrize("change,reasons", [
    ({"authority": False}, ["hold_back"]),                                  # no authority goes out
    ({"caps": _caps(line_follow_authority=None)}, ["hold_back"]),
    ({"caps": _caps(goal_lease=None)}, ["no_goal_lease"]),                  # a free leg without a leased goal
    ({"caps": _caps(drive_modes=None)}, ["leg_unknown"]),
    ({"caps": _caps(drive_modes=True)}, ["leg_unknown"]),                   # malformed: 422, not a 500
    ({"caps": _caps(drive_modes=5)}, ["leg_unknown"]),
    ({"caps": _caps(goal_lease=None, line_follow_authority=None)}, ["hold_back", "no_goal_lease"]),
])
def test_the_motion_bound_part_is_rule_ms_verdict(change, reasons):
    """D-760 6 in one place: hold_job asks rule_m.verdict per leg (without the lease) and names its reasons."""
    runner, _, ports, _ = _job_runner()
    runner.authority.enabled = change.get("authority", True)
    err = _refused(runner, runner.hold_job(R, JOB, "kim", change.get("caps", CAPS)))
    assert (err.status, err.code) == (422, "LINK_UNBOUNDED_MOTION") and err.detail["reasons"] == reasons
    assert ports.lease.puts == []


def test_a_lane_only_robot_needs_no_free_leg_bound():
    runner, _, _, _ = _job_runner()
    err = _refused(runner, runner.hold_job(R, JOB, "kim", _caps(drive_modes=["lane"], goal_lease=None)))
    assert err.detail == {"reasons": [], "missing": ["goal_lease"]}   # Rule M passes; only Q10 (b) refuses


def test_a_free_only_robot_needs_no_lane_authority():
    runner, _, ports, _ = _job_runner()
    runner.authority.enabled = False                     # no lane authority at all
    err = _refused(runner, runner.hold_job(R, JOB, "kim", _caps(drive_modes=["free"], line_follow_authority=None)))
    assert err.detail == {"reasons": [], "missing": ["fleet.traffic.authority"]}   # Rule M passes; Q10 (a) refuses
    runner.authority.enabled = True
    assert _do(runner, runner.hold_job(R, JOB, "kim", _caps(drive_modes=["free"], line_follow_authority=None)))[
        "state"] == "held"


def test_an_authority_required_robot_passes_without_the_under_lease_flag():
    runner, _, ports, _ = _job_runner()
    caps = _caps(line_follow_authority_under_lease=None, line_follow_authority_required=True)
    assert _do(runner, runner.hold_job(R, JOB, "kim", caps))["state"] == "held"


def test_no_job_holds_a_robot_without_the_incident_path():
    runner, _, ports, _ = _job_runner()
    runner.lease.on_job_lost = None
    with pytest.raises(RuntimeError):
        _do(runner, runner.hold_job(R, JOB, "kim", CAPS))
    assert ports.lease.puts == []


# ---- between steps: the lease alone ------------------------------------------------------------

def test_between_steps_only_the_lease_is_renewed():
    runner, _, ports, _, lease = _held()
    assert ports.lease.puts[0]["job_id"] == JOB and ports.lease.puts[0]["trip_id"] == JOB
    sent = []

    async def no_motion_bound(*args, **kwargs):
        sent.append(args)
    ports.send_authority = no_motion_bound
    runner._renew_lease = no_motion_bound
    _ticks(runner, ports, n=40)                          # 20 s with no trip: the job's gap
    assert sent == [] and ports.goals == []
    assert len(ports.lease.puts) > 30 and {p["lease_id"] for p in ports.lease.puts} == {lease["lease_id"]}
    assert all(p["job_id"] == JOB for p in ports.lease.puts)
    assert ports.lease.lease is not None and lease["state"] == "held"


def test_the_jobs_step_adopts_its_lease_and_closing_the_step_keeps_it():
    runner, store, ports, _, lease = _held()
    _plan(store, ports, "east:fwd", 0.5, "SE", plan_id="p1")
    view = _do(runner, runner.start("p1", "kim", job_id=JOB))
    assert view["lease"] is lease and len({p["lease_id"] for p in ports.lease.puts}) == 1
    _do(runner, runner.cancel_robot(R, "operator_cancel"))
    assert ports.lease.deletes == [] and lease["state"] == "held"
    _ticks(runner, ports, n=4)
    assert ports.lease.puts[-1]["lease_id"] == lease["lease_id"]
    async def end_job():                                # the job ended (called on the server's loop)
        runner.release_job(R, JOB)
    _do(runner, end_job())
    assert [d[0] for d in ports.lease.deletes] == [lease["lease_id"]] and runner.lease.job_of(R) is None


def test_a_step_that_does_not_start_leaves_the_job_its_lease():
    runner, store, ports, _, lease = _held()
    _do(runner, runner.lease.release(R, lease["lease_id"]))
    assert ports.lease.deletes == [] and ports.lease.lease is not None


def test_another_trip_start_is_refused_before_any_motion():
    runner, store, ports, _, _ = _held()
    _plan(store, ports, "east:fwd", 0.5, "SE", plan_id="p1")
    puts = len(ports.lease.puts)
    err = _refused(runner, runner.start("p1", "lee"))
    assert (err.status, err.code, err.detail) == (409, "TRIP_ROBOT_BUSY", {"reason": "job", "owner_kind": "mission"})
    assert JOB not in str(err.detail)  # security review: the holder's mission id is not the trip starter's
    assert len(ports.lease.puts) == puts and ports.goals == [] and ports.line_starts == [] and ports.sent == []
    err = _refused(runner, runner.hold_job(R, "job-4", "lee", CAPS))   # one job per robot
    assert (err.status, err.code) == (409, "TRIP_ROBOT_BUSY")


class _Console(TripAware):
    robot_ids = [R]

    def __init__(self):
        self.calls = []

    async def goal(self, robot_id, *args, **kwargs):
        self.calls.append(("goal", robot_id))

    async def cancel(self, robot_id, *args, **kwargs):
        self.calls.append(("cancel", robot_id))

    async def estop_all(self, *args, **kwargs):
        self.calls.append(("estop_all",))

    async def line_follow_mode(self, robot_id, mode):
        self.calls.append(("line", robot_id, mode))

    async def formation_start(self, *a, **k):
        self.calls.append(("formation",))

    formation_reform = formation_resume = formation_start


def test_between_steps_every_fleet_entry_answers_busy_but_stops_pass():
    runner, _, ports, _, _ = _held()
    console = _Console()
    install_trip_guard(console, runner)
    assert console.trip_busy(R) and console.trip_refusal([R]).code == "TRIP_ROBOT_BUSY"
    with pytest.raises(Exception) as busy:
        _do(runner, console.goal(R, 1.0, 0.0, 0.0))
    assert getattr(busy.value, "code", None) == "TRIP_ROBOT_BUSY" and console.calls == []
    _do(runner, console.line_follow_mode(R, "OFF"))
    _do(runner, console.cancel(R))
    assert console.calls == [("line", R, "OFF"), ("cancel", R)]


def test_a_persons_stop_through_fleet_holds_the_job_and_no_step_runs_on():
    """Fleet's own token is the lease owner, so CORE keeps the lease: Fleet gives it up and the job HOLDs."""
    runner, store, ports, lost, lease = _held()
    console = _Console()
    install_trip_guard(console, runner)
    _plan(store, ports, "east:fwd", 0.5, "SE", plan_id="p1")
    _do(runner, runner.start("p1", "kim", job_id=JOB))
    _do(runner, console.cancel(R))
    assert runner.view("p1")["state"] == "canceled"
    assert lost == [(JOB, {"lease_reason": "operator_cancel"})] and lease["state"] == "lost"
    assert [d[0] for d in ports.lease.deletes] == [lease["lease_id"]] and ports.lease.lease is None
    _plan(store, ports, "east:fwd", 0.5, "SE", plan_id="p2")
    assert _refused(runner, runner.start("p2", "kim", job_id=JOB)).code == "TRIP_ROBOT_BUSY"  # re-approval first
    assert console.trip_busy(R)                          # the job keeps the robot in HOLD


def test_a_failed_trip_cancel_still_holds_the_job():
    runner, _, ports, lost, lease = _held()
    console = _Console()
    install_trip_guard(console, runner)

    async def broken(robot_id, reason):
        raise OSError("trip store down")
    runner.cancel_robot = broken
    _do(runner, console.cancel(R))
    assert lost == [(JOB, {"lease_reason": "operator_cancel"})] and lease["state"] == "lost"


def test_a_job_does_not_take_a_robot_that_already_moves():
    runner, store, ports, _ = _job_runner()
    _plan(store, ports, "east:fwd", 0.5, "SE", plan_id="p1")
    _do(runner, runner.start("p1", "kim"))
    err = _refused(runner, runner.hold_job(R, JOB, "kim", CAPS))
    assert (err.status, err.code, err.detail) == (409, "TRIP_ROBOT_BUSY", {"reason": "trip"})
    runner2, _, ports2, _ = _job_runner()
    runner2._engaged = lambda robot_id: "goal"           # a console goal still running
    assert _refused(runner2, runner2.hold_job(R, JOB, "kim", CAPS)).detail == {"reason": "goal"}
    assert ports2.lease.puts == []


def test_a_job_ends_only_after_its_step_trip():
    runner, store, ports, _, lease = _held()
    _plan(store, ports, "east:fwd", 0.5, "SE", plan_id="p1")
    _do(runner, runner.start("p1", "kim", job_id=JOB))
    with pytest.raises(Exception) as busy:
        runner.release_job(R, JOB)
    assert getattr(busy.value, "code", None) == "TRIP_BUSY" and lease["state"] == "held"


@pytest.mark.parametrize('owner_kind', ['mission', 'charge_session'])
def test_a_jobs_durable_robot_claim_holds_the_robot_without_its_lease(owner_kind):
    runner, store, ports, _ = _job_runner()
    claims = {R: [{"owner_kind": "task", "owner_id": "t-1"}, {"owner_kind": owner_kind, "owner_id": JOB}]}
    console = _Console()
    install_trip_guard(console, runner, claims=lambda resource_kind, resource_id: claims.get(resource_id, []))
    assert runner.lease.job_of(R) == JOB and console.trip_busy(R)   # e.g. HOLD after a Fleet restart
    claims[R] = [{"owner_kind": "task", "owner_id": "t-1"}]
    assert runner.lease.job_of(R) is None and not console.trip_busy(R)  # a Task claim is not a job
    claims[R].append({"owner_kind": owner_kind, "owner_id": JOB})
    _plan(store, ports, "east:fwd", 0.5, "SE", plan_id="p1")
    assert _refused(runner, runner.start("p1", "lee")).code == "TRIP_ROBOT_BUSY"


# ---- lease loss while the job holds the robot (rev 2 Q3) ---------------------------------------

def test_loss_between_steps_calls_the_incident_path_once_and_keeps_the_hold():
    runner, _, ports, lost, lease = _held()
    ports.lease.end("taken_over", "pilot")
    _ticks(runner, ports, n=3)
    assert lost == [(JOB, {"lease_reason": "taken_over", "lease_by": "pilot"})]
    assert lease["state"] == "lost" and runner.lease.job_of(R) == JOB
    puts = len(ports.lease.puts)
    _ticks(runner, ports, n=3)
    assert len(ports.lease.puts) == puts                # never renewed back into a lease (D-541 7)
    again = _do(runner, runner.hold_job(R, JOB, "kim", CAPS))   # re-approval: a new lease
    assert again["lease_id"] != lease["lease_id"] and again["state"] == "held"


def test_link_loss_between_steps_is_lost_at_ttl_after_the_last_confirmed_renew():
    runner, _, ports, lost, lease = _held()
    ports.lease.down = True
    _ticks(runner, ports, n=15)                          # 7.5 s: Fleet keeps trying
    assert lost == [] and lease["state"] == "held"
    _ticks(runner, ports, n=2)                           # past 8 s
    assert lost == [(JOB, {"lease_reason": "renew_timeout"})]


def test_loss_during_a_step_ends_the_trip_lease_lost_and_tells_the_job():
    runner, store, ports, lost, lease = _held()
    _plan(store, ports, "east:fwd", 0.5, "SE", plan_id="p1")
    _do(runner, runner.start("p1", "kim", job_id=JOB))
    ports.lease.end("expired", "core")
    _ticks(runner, ports, n=2)
    assert runner.view("p1")["state"] == "stopped" and runner.view("p1")["reason"] == "lease_lost"
    assert lost == [(JOB, {"lease_reason": "expired", "lease_by": "core"})]
    assert runner.lease.job_of(R) == JOB
