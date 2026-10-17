"""D-780 owner side: coordinator peer roles, COORDINATOR stop source, PHASE_WAIT barriers."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for relative in ("middleware/devices/omx/agent/src", "middleware/devices/omx/adapter",
                 "middleware/devices/omx/adapter/test"):
    if str(ROOT / relative) not in sys.path:
        sys.path.insert(0, str(ROOT / relative))

from core_common.protocol.schemas import FleetCellTransferGrant, StopRequestSource  # noqa: E402
from omx_adapter.action_api import ActionApi, LocalStopApi  # noqa: E402
from omx_adapter.action_runner import ActionRunner  # noqa: E402
from omx_adapter.action_store import ActionStore  # noqa: E402
from omx_adapter.local_stop import LocalStopController  # noqa: E402
from omx_adapter.owner_recovery_api import OwnerRecoveryApi  # noqa: E402
from omx_adapter.phase_gate import PHASE_WAIT  # noqa: E402
from rosy_agent.barrier_journal import BarrierJournal  # noqa: E402
from rosy_agent.barrier_supervisor import BarrierSupervisor, make_coordinator_hold  # noqa: E402
from rosy_agent.coordinator_api import CoordinatorPeerApi  # noqa: E402

FLEET, COORDINATOR, STRANGER = 1001, 2002, 3003
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
POSE = {"x": 0.1, "y": 0.2, "z": 0.3, "yaw": 0.0}
BARRIERS = [
    {"barrier_id": "both_ready", "before_first_phase": True, "coupling_after": "loose", "max_wait_s": 5.0},
    {"barrier_id": "both_grasped", "after_phase": "grasp", "coupling_after": "tight", "max_wait_s": 3.0},
]


def _grant(barriers=BARRIERS, coupling="tight", action_id="a-1"):
    value = {
        "mission_id": "m-1", "step_id": "s-1", "action_id": action_id, "attempt_id": f"t-{action_id}",
        "request_digest": "0" * 64, "workcell_id": "cell-1", "instance_id": "omx-left",
        "action_kind": "CELL_TRANSFER",
        "cell_transfer": {
            "job_id": "job-1", "recipe_sha256": "a" * 64, "cell_sha256": "b" * 64, "step_index": 0,
            "item": "box", "pallet": "A", "layer": 0, "frame": "robot_base", "home": POSE, "pick": POSE,
            "place": POSE, "pick_approach_z": 0.5, "place_approach_z": 0.5, "carry_z": 0.6},
        "capability_revision": "c", "config_revision": "r", "authority_epoch": 2, "dispatch_generation": 8,
        "issued_at": NOW, "expires_at": NOW + timedelta(seconds=30),
        "arm_role": "left", "pair_id": "pair-1", "partner_instance_id": "omx-right", "coupling": coupling,
    }
    if barriers:
        value["cell_transfer"]["barriers"] = barriers
    return FleetCellTransferGrant.model_validate(value)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def cell(tmp_path):
    clock = Clock()
    store = ActionStore(tmp_path / "owner.sqlite3")
    journal = BarrierJournal(store.path, monotonic=clock, now=lambda: NOW)
    holds = []
    fence = {"current": True}
    supervisor = BarrierSupervisor(journal, store, coordinator_liveness_s=2.0, monotonic=clock,
                                   hold_owner=lambda grant, reason: holds.append((grant.action_id, reason.value)),
                                   fence_current=lambda epoch, generation: fence["current"])
    runner = ActionRunner(store, object(), workcell_id="cell-1", instance_id="omx-left",
                          principal_for_peer=lambda uid: f"fleet-uid-{uid}", allowed_peer_uids={FLEET},
                          current_fence=lambda epoch, generation: True, capability_current=lambda grant: True)
    peer_api = CoordinatorPeerApi(store, journal, supervisor, workcell_id="cell-1",
                                  coordinator_peer_uids={COORDINATOR}, fleet_peer_uids={FLEET},
                                  read_receipt=runner.read_receipt,
                                  fence_current=lambda epoch, generation: fence["current"])
    api = ActionApi(runner, coordinator_api=peer_api)
    return SimpleNamespace(store=store, journal=journal, supervisor=supervisor, holds=holds, clock=clock,
                           api=api, runner=runner, fence=fence)


def _journal_action(store, grant):
    store.create_action(workcell_id=grant.workcell_id, instance_id=grant.instance_id,
                        principal_id=f"fleet-uid-{FLEET}", request_key=grant.action_id,
                        action_id=grant.action_id, action_kind=grant.action_kind,
                        configuration_revision=grant.config_revision, observation_id="",
                        owner_generation=grant.dispatch_generation, payload=grant.model_dump(mode="json"))
    store.begin_submission(grant.action_id, expected_generation=grant.dispatch_generation,
                           attempt_id=grant.attempt_id)
    return grant


def _move(store, grant, phase_id="approach", ordinal=0):
    store.begin_phase(grant.action_id, grant.attempt_id, phase_id=phase_id, ordinal=ordinal,
                      command_digest="d" * 64)


def _release(cell, grant, barrier_id="both_ready", **changes):
    request = {"version": 2, "operation": "ReleaseBarrier", "action_id": grant.action_id,
               "pair_id": "pair-1", "barrier_id": barrier_id, "authority_epoch": 2, "dispatch_generation": 8,
               "partner_arrival": {"instance_id": "omx-right", "action_id": "a-r", "arrived_at": "x"}}
    request.update(changes)
    return cell.api.dispatch(request, peer_uid=COORDINATOR)


def test_phase_wait_refuses_truth_testing():
    assert PHASE_WAIT is type(PHASE_WAIT)()
    with pytest.raises(TypeError):
        bool(PHASE_WAIT)


def test_gate_records_phase_wait_once_and_allows_after_release(cell):
    grant = _journal_action(cell.store, _grant())
    assert cell.supervisor.phase_gate(grant, "approach") is PHASE_WAIT
    assert cell.supervisor.phase_gate(grant, "approach") is PHASE_WAIT
    assert cell.supervisor.phase_gate(grant, "grasp") is True  # no barrier before grasp
    events = [event["event_type"] for event in cell.store.attempt_snapshot(grant.action_id, grant.attempt_id)["events"]]
    assert events.count("PHASE_WAIT") == 1
    assert cell.supervisor.first_phase_released(grant) is False
    assert _release(cell, grant)["status"] == 200
    assert cell.supervisor.phase_gate(grant, "approach") is True
    assert cell.supervisor.first_phase_released(grant) is True


def test_grant_without_barriers_never_touches_the_journal(cell):
    grant = _journal_action(cell.store, _grant(barriers=None, coupling="independent"))
    assert all(cell.supervisor.phase_gate(grant, phase) is True
               for phase in ("approach", "grasp", "transfer", "release"))
    assert cell.journal.rows(grant.action_id, grant.attempt_id) == {}
    assert cell.supervisor.tick(grant) is None


def test_peer_role_matrix(cell):
    grant = _journal_action(cell.store, _grant())
    get_barrier = {"version": 2, "operation": "GetBarrier"}
    assert cell.api.dispatch(get_barrier, peer_uid=FLEET)["error"]["code"] == "COORDINATOR_PEER_REQUIRED"
    assert cell.api.dispatch(get_barrier, peer_uid=STRANGER)["error"]["code"] == "PEER_NOT_ALLOWED"
    fleet_release = {"version": 2, "operation": "ReleaseBarrier", "action_id": grant.action_id}
    assert cell.api.dispatch(fleet_release, peer_uid=FLEET)["status"] == 403
    for operation in ("SubmitAction", "CancelAction", "RecoverOwner", "RearmLocal"):
        refused = cell.api.dispatch({"version": 1, "operation": operation}, peer_uid=COORDINATOR)
        assert (refused["status"], refused["error"]["code"]) == (403, "COORDINATOR_NOT_ALLOWED")
    read = cell.api.dispatch({"version": 2, "operation": "GetAction", "action_id": grant.action_id},
                             peer_uid=COORDINATOR)
    assert read["status"] == 200 and read["receipt"]["state"] == "SUBMITTING"
    missing = cell.api.dispatch({"version": 2, "operation": "GetAction", "action_id": "nope"},
                                peer_uid=COORDINATOR)
    assert missing["status"] == 404
    # The Fleet principal path is unchanged for the Fleet peer.
    fleet_read = cell.api.dispatch({"version": 2, "operation": "GetAction", "action_id": grant.action_id},
                                   peer_uid=FLEET)
    assert fleet_read["status"] == 200


def test_get_barrier_lists_paired_actions_and_reports_states(cell):
    grant = _journal_action(cell.store, _grant())
    listed = cell.api.dispatch({"version": 2, "operation": "GetBarrier"}, peer_uid=COORDINATOR)
    assert listed["status"] == 200
    (view,) = listed["actions"]
    assert (view["pair_id"], view["partner_instance_id"], view["coupling"], view["moved"]) == (
        "pair-1", "omx-right", "tight", False)
    assert [item["state"] for item in view["barriers"]] == ["not_reached", "not_reached"]
    assert view["fence_open"] is True
    cell.supervisor.phase_gate(grant, "approach")
    single = cell.api.dispatch({"version": 2, "operation": "GetBarrier", "action_id": grant.action_id},
                               peer_uid=COORDINATOR)
    assert single["action"]["barriers"][0]["state"] == "waiting"
    assert single["action"]["barriers"][0]["arrived_at"] == NOW.isoformat(timespec="microseconds")
    assert cell.api.dispatch({"version": 1, "operation": "GetBarrier"}, peer_uid=COORDINATOR)["status"] == 400


def test_release_checks_pair_plan_generation_fence_arrival_and_is_idempotent(cell):
    grant = _journal_action(cell.store, _grant())
    assert _release(cell, grant)["error"]["code"] == "BARRIER_NOT_REACHED"
    cell.supervisor.phase_gate(grant, "approach")
    assert _release(cell, grant, pair_id="pair-2")["error"]["code"] == "PAIR_MISMATCH"
    assert _release(cell, grant, barrier_id="placed_before_push")["status"] == 404
    assert _release(cell, grant, dispatch_generation=9)["error"]["code"] == "FENCE_STALE"
    cell.fence["current"] = False
    assert _release(cell, grant)["error"]["code"] == "FENCE_STALE"
    cell.fence["current"] = True
    first = _release(cell, grant)
    assert first["status"] == 200 and first["created"] is True
    again = _release(cell, grant, partner_arrival={"instance_id": "omx-right", "action_id": "a-r",
                                                   "arrived_at": "later"})
    assert again["status"] == 200 and again["created"] is False
    assert again["barrier"] == first["barrier"]
    assert first["barrier"]["release"]["partner_arrival"]["instance_id"] == "omx-right"
    assert first["barrier"]["release"]["coordinator"] == f"coordinator-uid-{COORDINATOR}"


def test_owner_without_coordinator_keeps_unknown_operation(cell):
    plain = ActionApi(cell.runner)
    response = plain.dispatch({"version": 2, "operation": "GetBarrier"}, peer_uid=FLEET)
    assert (response["status"], response["error"]["code"]) == (404, "UNKNOWN_OPERATION")


def test_timeout_before_any_moved_phase_fails_the_action_without_hold(cell):
    grant = _journal_action(cell.store, _grant())
    cell.supervisor.phase_gate(grant, "approach")
    cell.clock.t += 5.0
    assert cell.supervisor.tick(grant) is None  # exactly max_wait_s is still waiting
    cell.clock.t += 0.01
    assert cell.supervisor.tick(grant) == "FAILED"
    action = cell.store.get_action(grant.action_id)
    assert (action["state"], action["reason"]) == ("FAILED", "BARRIER_TIMEOUT")
    assert cell.holds == []
    assert cell.journal.rows(grant.action_id, grant.attempt_id)["both_ready"]["state"] == "expired"
    assert cell.supervisor.phase_gate(grant, "approach") is False
    assert _release(cell, grant)["error"]["code"] == "ACTION_NOT_ACTIVE"  # FAILED can no longer move


def test_timeout_after_a_moved_phase_holds_the_owner(cell):
    grant = _journal_action(cell.store, _grant(barriers=[BARRIERS[1]]))
    _move(cell.store, grant)
    assert cell.supervisor.phase_gate(grant, "transfer") is PHASE_WAIT
    cell.clock.t += 3.5
    assert cell.supervisor.tick(grant) == "HOLD"
    assert cell.holds == [(grant.action_id, "BARRIER_TIMEOUT")]


def test_tight_segment_holds_on_coordinator_silence_only(cell):
    grant = _journal_action(cell.store, _grant())
    _move(cell.store, grant)
    cell.supervisor.phase_gate(grant, "approach")
    _release(cell, grant)  # loose after the first barrier: no liveness watch
    cell.clock.t += 10
    assert cell.supervisor.tick(grant) is None
    cell.supervisor.phase_gate(grant, "transfer")
    _release(cell, grant, barrier_id="both_grasped")  # tight from here
    cell.clock.t += 1.5
    assert cell.supervisor.tick(grant) is None
    cell.api.dispatch({"version": 2, "operation": "GetBarrier"}, peer_uid=COORDINATOR)  # liveness traffic
    cell.clock.t += 1.9
    assert cell.supervisor.tick(grant) is None
    cell.clock.t += 0.2
    assert cell.supervisor.tick(grant) == "HOLD"
    assert cell.holds == [(grant.action_id, "PARTNER_LINK_LOST")]


def test_liveness_bound_must_exceed_the_uds_budget(cell):
    with pytest.raises(ValueError):
        BarrierSupervisor(cell.journal, cell.store, coordinator_liveness_s=0.25, hold_owner=lambda *_: None)


def test_coordinator_hold_latches_stop_with_source_and_reason_and_holds_the_action(tmp_path):
    store = ActionStore(tmp_path / "owner.sqlite3")
    stop = LocalStopController(store.path, workcell_id="cell-1", instance_id="omx-left")
    grant = _journal_action(store, _grant())
    cancelled = []
    hold = make_coordinator_hold(stop, store, cancel_active=lambda: cancelled.append(True), now=lambda: NOW)
    hold(grant, "BARRIER_TIMEOUT")
    snapshot = stop.snapshot(workcell_id="cell-1", instance_id="omx-left")
    assert (snapshot.source, snapshot.reason, snapshot.state.value) == (
        StopRequestSource.COORDINATOR, "BARRIER_TIMEOUT", "LOCAL_LATCHED")
    action = store.get_action(grant.action_id)
    assert (action["state"], action["reason"]) == ("HOLD", "BARRIER_TIMEOUT")
    assert cancelled == [True]
    with pytest.raises(ValueError):
        hold(grant, "free text")


def _stop_request(reason):
    return {"version": 1, "operation": "StopLocal", "workcell_id": "cell-1", "instance_id": "omx-left",
            "authority_epoch": 2, "dispatch_generation": 8, "requested_at": NOW.isoformat(), "reason": reason}


def test_coordinator_stop_records_coordinator_source_with_a_reason_code(tmp_path):
    stop = LocalStopController(tmp_path / "stop.sqlite3", workcell_id="cell-1", instance_id="omx-left")
    api = LocalStopApi(stop, source_by_peer_uid={FLEET: StopRequestSource.FLEET,
                                                 COORDINATOR: StopRequestSource.COORDINATOR})
    assert api.dispatch(_stop_request("operator saw a wobble"), peer_uid=COORDINATOR)["status"] == 400
    stopped = api.dispatch(_stop_request("PARTNER_FAILED"), peer_uid=COORDINATOR)
    assert stopped["status"] == 200
    assert (stopped["snapshot"]["source"], stopped["snapshot"]["reason"]) == ("coordinator", "PARTNER_FAILED")
    rearm = {"version": 1, "operation": "RearmLocal", "workcell_id": "cell-1", "instance_id": "omx-left",
             "authority_epoch": 3, "dispatch_generation": 9}
    assert api.dispatch(rearm, peer_uid=COORDINATOR)["error"]["code"] == "FLEET_PEER_REQUIRED"
    # The Fleet stop keeps free-text reasons.
    assert api.dispatch(_stop_request("operator stop"), peer_uid=FLEET)["snapshot"]["source"] == "fleet"


def test_existing_stop_latch_table_is_migrated_with_rows_unchanged(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE omx_local_stop (
            workcell_id TEXT NOT NULL, instance_id TEXT NOT NULL, authority_epoch INTEGER NOT NULL,
            dispatch_generation INTEGER NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('OPEN', 'REQUESTED', 'LOCAL_LATCHED', 'UNKNOWN')),
            source TEXT NOT NULL CHECK(source IN ('fleet', 'operator_local')),
            dispatch_enabled INTEGER NOT NULL CHECK(dispatch_enabled IN (0, 1)),
            observed_at TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(workcell_id, instance_id))""")
        connection.execute("INSERT INTO omx_local_stop VALUES ('cell-1', 'omx-left', 4, 11, 'LOCAL_LATCHED', "
                           "'operator_local', 0, '2026-10-01T00:00:00+00:00', 'OLD_REASON')")
    stop = LocalStopController(path, workcell_id="cell-1", instance_id="omx-left")
    kept = stop.snapshot(workcell_id="cell-1", instance_id="omx-left")
    assert (kept.authority_epoch, kept.dispatch_generation, kept.source.value, kept.reason) == (
        4, 11, "operator_local", "OLD_REASON")
    LocalStopController(path, workcell_id="cell-1", instance_id="omx-left")  # second start: no rebuild
    api = LocalStopApi(stop, source_by_peer_uid={COORDINATOR: StopRequestSource.COORDINATOR})
    assert api.dispatch(_stop_request("PARTNER_LINK_LOST"), peer_uid=COORDINATOR)["snapshot"]["source"] == "coordinator"


def test_recovery_api_lets_the_coordinator_read_but_not_recover():
    owner = SimpleNamespace(config=SimpleNamespace(workcell_id="cell-1", instance_id="omx-left"),
                            recovery_state=lambda: {"state": "hold", "reason": "x", "observed_sequence": 3})
    api = OwnerRecoveryApi(owner, None, None, allowed_peer_uids={FLEET}, current_fence=lambda *_: True,
                           read_peer_uids={COORDINATOR})
    base = {"version": 1, "workcell_id": "cell-1", "instance_id": "omx-left"}
    assert api.dispatch({**base, "operation": "GetOwnerState"}, peer_uid=COORDINATOR)["status"] == 200
    recover = {**base, "operation": "RecoverOwner", "authority_epoch": 2, "dispatch_generation": 8,
               "operator_confirmed": True, "observed_sequence": 3, "actor_id": "op"}
    assert api.dispatch(recover, peer_uid=COORDINATOR)["error"]["code"] == "PEER_NOT_ALLOWED"
    assert api.dispatch({**base, "operation": "GetOwnerState"}, peer_uid=STRANGER)["status"] == 403


def test_runner_returns_on_phase_wait_and_submits_after_release(tmp_path):
    from test_omx_pick_place_runner import _harness, _event

    gate = {"approach": PHASE_WAIT, "grasp": PHASE_WAIT}
    _, recorder, port, runner = _harness(tmp_path, phase_gate=lambda phase_id: gate.get(phase_id, True))
    assert runner.start() == {"waiting": "approach"}
    assert port.submissions == [] and recorder.phases() == []
    gate["approach"] = True
    runner.start()
    command, goal = port.submissions[0]
    runner.on_ros_goal_event(_event("TERMINAL_RESULT", command, "approach", goal, 2, status=4, result_code=0))
    assert runner.advance() == {"waiting": "grasp"}
    assert len(port.submissions) == 1
    gate["grasp"] = True
    runner.advance()
    assert len(port.submissions) == 2


@pytest.mark.parametrize("moved,state", [(False, "FAILED"), (True, "HOLD")])
def test_a_closed_fence_ends_a_waiting_action_at_once(cell, moved, state):
    grant = _journal_action(cell.store, _grant())
    if moved:
        _move(cell.store, grant)
        cell.supervisor.phase_gate(grant, "transfer")
    else:
        cell.supervisor.phase_gate(grant, "approach")
    cell.fence["current"] = False
    assert cell.supervisor.end_fenced_waits() == [grant.action_id]
    action = cell.store.get_action(grant.action_id)
    assert (action["state"], action["reason"]) == (state, "STOP_FENCED_AT_BARRIER")
    assert cell.holds == []  # the latch is already closed; no second, coordinator-sourced stop
    assert cell.supervisor.end_fenced_waits() == []


def test_tick_ends_a_wait_whose_fence_closed(cell):
    grant = _journal_action(cell.store, _grant())
    cell.supervisor.phase_gate(grant, "approach")
    cell.fence["current"] = False
    assert cell.supervisor.tick(grant) == "FAILED"


def test_release_refuses_an_action_that_can_no_longer_move(cell):
    grant = _journal_action(cell.store, _grant())
    cell.supervisor.phase_gate(grant, "approach")
    cell.store.hold_action(grant.action_id, grant.attempt_id, reason="ROS_GOAL_FAILED")
    assert _release(cell, grant)["error"]["code"] == "ACTION_NOT_ACTIVE"


def test_an_arrival_from_an_earlier_boot_is_never_released_or_timed(cell):
    grant = _journal_action(cell.store, _grant())
    cell.supervisor.phase_gate(grant, "approach")
    restarted = BarrierJournal(cell.store.path, monotonic=cell.clock, now=lambda: NOW)
    with pytest.raises(Exception, match="restart"):
        restarted.release(grant.action_id, grant.attempt_id, "both_ready", release={})
    supervisor = BarrierSupervisor(restarted, cell.store, coordinator_liveness_s=2.0, monotonic=cell.clock,
                                   hold_owner=lambda *_: None)
    assert supervisor.tick(grant) == "FAILED"  # stale arrival: ended, not waited on


def test_expiry_failure_falls_back_to_owner_hold(cell, monkeypatch):
    grant = _journal_action(cell.store, _grant())
    cell.supervisor.phase_gate(grant, "approach")

    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(cell.journal, "expire", broken)
    cell.clock.t += 6
    assert cell.supervisor.tick(grant) == "HOLD"
    assert cell.holds == [(grant.action_id, "BARRIER_TIMEOUT")]


def test_owner_without_coordinator_refuses_pair_grants_before_journaling(cell):
    plain = ActionApi(cell.runner)
    response = plain.dispatch({"version": 2, "operation": "SubmitAction",
                               "grant": _grant().model_dump(mode="json")}, peer_uid=FLEET)
    assert (response["status"], response["error"]["code"]) == (409, "BARRIERS_UNSUPPORTED")
    assert cell.store.get_action("a-1") is None


def test_a_repeated_release_returns_the_same_result_after_the_action_stopped_moving(cell):
    grant = _journal_action(cell.store, _grant())
    cell.supervisor.phase_gate(grant, "approach")
    first = _release(cell, grant)
    cell.store.hold_action(grant.action_id, grant.attempt_id, reason="ROS_GOAL_FAILED")
    again = _release(cell, grant)
    assert again["status"] == 200 and again["created"] is False and again["barrier"] == first["barrier"]


def test_a_barrier_table_without_boot_ids_is_migrated_fail_closed(cell):
    grant = _journal_action(cell.store, _grant())
    with sqlite3.connect(cell.store.path) as connection:
        connection.execute("DROP TABLE omx_action_barriers")
        connection.execute("""CREATE TABLE omx_action_barriers (
            action_id TEXT NOT NULL, attempt_id TEXT NOT NULL, barrier_id TEXT NOT NULL,
            gated_phase TEXT NOT NULL, coupling_after TEXT NOT NULL, max_wait_s REAL NOT NULL,
            state TEXT NOT NULL, authority_epoch INTEGER NOT NULL, dispatch_generation INTEGER NOT NULL,
            arrived_at TEXT NOT NULL, arrived_monotonic REAL NOT NULL, released_at TEXT,
            released_monotonic REAL, release_json TEXT, expired_at TEXT,
            PRIMARY KEY(action_id, attempt_id, barrier_id))""")
        connection.execute("INSERT INTO omx_action_barriers (action_id, attempt_id, barrier_id, gated_phase, "
                           "coupling_after, max_wait_s, state, authority_epoch, dispatch_generation, arrived_at, "
                           "arrived_monotonic) VALUES (?, ?, 'both_ready', 'approach', 'loose', 5.0, 'waiting', "
                           "2, 8, 'x', 1.0)", (grant.action_id, grant.attempt_id))
    journal = BarrierJournal(cell.store.path, monotonic=cell.clock, now=lambda: NOW)
    (row,) = journal.rows(grant.action_id, grant.attempt_id).values()
    assert row["boot_id"] == "pre-boot-id"
    with pytest.raises(Exception, match="restart"):
        journal.release(grant.action_id, grant.attempt_id, "both_ready", release={})
