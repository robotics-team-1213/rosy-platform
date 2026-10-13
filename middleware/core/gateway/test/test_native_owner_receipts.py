"""Native receipts stay bound to the owner admission, not caller correlation."""

from types import SimpleNamespace
import time
import threading
from uuid import UUID

import pytest

from core.bridge.goal_tracker import GoalTracker
from core_features.navigation.manager import NavigationError, NavigationManager, NavGoalSpec
from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, ZERO
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits
from core_common.protocol.native_receipts import BOOT_ID, NativeReceipts
from core_common.protocol.schemas import DockState, SwarmFollowParams
from core_features.swarm.manager import SwarmError

from test_docking_mode_ownership import docking_robot, DrivingExecutor, OPERATOR


class _State:
    map_id = "map"

    def set_navigation(self, state):
        self.navigation = state


class _Events:
    def __init__(self):
        self.events = []

    def publish(self, name, **kwargs):
        self.events.append((name, kwargs.get("data", {})))


def _nav():
    events = _Events()
    nav = NavigationManager(events, _State(), None, SimpleNamespace(estop=False))
    return nav, events


def test_inline_goal_callbacks_keep_exact_first_terminal_and_new_run():
    nav, events = _nav()

    class InlineExecutor:
        def send_native_goal(self, spec, run_id, *, correlation_id):
            nav.on_goal_accepted(native_run_id=run_id)
            nav.on_result(True, correlation_id=correlation_id, native_run_id=run_id)

        def cancel_goal(self):
            pass

    nav.executor = InlineExecutor()
    receipt = []
    spec = NavGoalSpec(1, 2, 0)
    nav.goal(spec, correlation_id="reused", receipt_sink=receipt.append)
    first = receipt[0]
    assert first.phase == "SUBMITTED"
    assert nav.native_readback(first.run_id)["operation"]["result"] == "SUCCEEDED"
    assert nav.nav_state.value == "ARRIVED"
    assert nav._lease is None

    nav.goal(spec, correlation_id="reused", receipt_sink=receipt.append)
    second = receipt[1]
    assert first.run_id != second.run_id
    nav.on_result(False, native_run_id=first.run_id, correlation_id="reused")
    assert nav.native_readback(second.run_id)["operation"]["result"] == "SUCCEEDED"
    assert nav.native_readback(first.run_id)["operation"]["result"] == "SUCCEEDED"
    completed = [data for name, data in events.events if name == "nav.completed"]
    assert {data["run_id"] for data in completed} == {str(first.run_id), str(second.run_id)}


def test_ambiguous_send_blocks_new_goal_until_explicit_cancel():
    nav, _events = _nav()

    class UnknownExecutor:
        def send_native_goal(self, spec, run_id, *, correlation_id):
            raise RuntimeError("ambiguous transport")

        def cancel_goal(self):
            pass

    nav.executor = UnknownExecutor()
    receipt = []
    with pytest.raises(RuntimeError):
        nav.goal(NavGoalSpec(1, 2, 0), receipt_sink=receipt.append)
    assert nav.native_readback(receipt[0].run_id)["operation"]["phase"] == "SUBMITTED"
    with pytest.raises(NavigationError) as refused:
        nav.goal(NavGoalSpec(3, 4, 0))
    assert refused.value.code == "NAVIGATION_ACTIVE"
    assert nav.cancel()
    assert nav.native_readback(receipt[0].run_id)["operation"]["result"] == "CANCELED"


def test_goal_tracker_transport_snapshot_tracks_pending_handle_and_completion():
    tracker = GoalTracker()
    generation = tracker.opening()
    assert tracker.transport_snapshot()[1:] == (True, False)
    assert tracker.accepted(generation, object())
    assert tracker.transport_snapshot()[1:] == (False, True)
    assert tracker.finished(generation)
    assert tracker.transport_snapshot()[1:] == (False, False)


def test_legacy_result_callback_still_publishes_without_native_identity():
    nav, events = _nav()
    nav.on_result(True)
    nav.on_result(False, "REJECTED")
    assert [name for name, _data in events.events] == ["nav.completed", "nav.failed"]


def test_cancelled_accepted_goal_remains_pending_until_result_callback():
    tracker = GoalTracker()
    generation = tracker.opening()
    tracker.accepted(generation, object())
    tracker.cancel_all()
    assert tracker.transport_snapshot()[1:] == (True, False)
    tracker.finished(generation)
    assert tracker.transport_snapshot()[1:] == (False, False)


def test_each_teleop_pulse_preempts_then_expires_with_exact_terminal_event():
    events = _Events()
    modes = ModeMachine()
    safety = SafetyManager(SpeedLimits(max_linear=0.2, max_angular=0.8,
                                       manual_linear=0.15, manual_angular=0.6),
                           BatteryPolicy(), events=events)
    command = CommandManager(SourceRegistry(), modes, safety, events=events)
    assert modes.transition(Mode.MANUAL)[0]
    receipts = []
    assert command.teleop(0.1, 0, receipt_sink=receipts.append)[0]
    assert command.teleop(0.1, 0, receipt_sink=receipts.append)[0]
    first, second = receipts
    assert command.native_readback(first.run_id)["operation"]["result"] == "PREEMPTED"
    assert command.select_output(now=time.monotonic() + 5) == ZERO
    command.announce_pending()
    assert command.native_readback(second.run_id)["operation"]["result"] == "EXPIRED"
    terminals = [data for name, data in events.events if name == "native.operation.terminal"]
    assert [(data["run_id"], data["result"]) for data in terminals] == [
        (str(first.run_id), "PREEMPTED"), (str(second.run_id), "EXPIRED")]
    assert command.teleop(0.1, 0, receipt_sink=receipts.append)[0]
    mode_left = receipts[-1]
    assert modes.transition(Mode.IDLE)[0]
    command.announce_pending()
    assert command.native_readback(mode_left.run_id)["operation"]["result"] == "PREEMPTED"
    assert command.native_readback(mode_left.run_id)["operation"]["reason"] == "MODE_LEFT"


def test_retention_is_exact_and_pruned_identity_is_unknown():
    ledger = NativeReceipts()
    runs = []
    for _ in range(33):
        accepted = ledger.admit("navigate", "reused")
        runs.append(accepted.run_id)
        ledger.update(accepted.run_id, phase="TERMINAL", result="SUCCEEDED")
    assert ledger.readback(runs[0])["lookup"] == "UNKNOWN"
    assert ledger.readback(runs[0])["operation"] is None
    assert ledger.readback(runs[-1])["lookup"] == "FOUND"
    assert ledger.owner()["boot_id"] == str(BOOT_ID)


def test_reservation_revocation_prevents_backend_send():
    nav, _events = _nav()
    sent = []
    nav.executor = SimpleNamespace(send_goal=lambda spec: sent.append(spec), cancel_goal=lambda: None)
    owner = nav.native_readback()["owner"]
    token = nav.reserve_goal(expected_boot_id=BOOT_ID,
                             expected_owner_generation=owner["owner_generation"])
    assert nav.native_readback()["owner"]["owner_generation"] > owner["owner_generation"]
    assert nav.cancel() is False
    with pytest.raises(NavigationError) as refused:
        nav.goal(NavGoalSpec(1, 2, 0), reservation=token)
    assert refused.value.code == "OWNER_GENERATION_CHANGED"
    assert sent == []


def test_cancelled_run_requires_transport_result_before_quiescence():
    nav, _events = _nav()
    tracker = GoalTracker()

    class Executor:
        def send_native_goal(self, spec, run_id, *, correlation_id):
            self.generation = tracker.opening(correlation_id, run_id)
            tracker.accepted(self.generation, object())

        def cancel_goal(self):
            tracker.cancel_all()

        def native_transport_snapshot(self):
            return tracker.transport_snapshot()

    executor = Executor()
    nav.executor = executor
    receipt = []
    nav.goal(NavGoalSpec(1, 2, 0), receipt_sink=receipt.append)
    run_id = receipt[0].run_id
    assert nav.native_readback(run_id)["quiescence"]["actuating_callback"]
    nav.cancel()
    assert nav.native_readback(run_id)["quiescence"]["pending_submission"]
    assert not nav.native_readback(run_id)["quiescence"]["quiescent"]
    tracker.finished(executor.generation)
    assert nav.native_readback(run_id)["quiescence"]["quiescent"]


def test_dock_undock_success_cancel_and_charging_keep_exact_results(core_client):
    client, services = docking_robot(core_client)
    dock = services.docking.native.current
    assert dock.phase == "SUBMITTED"
    services.docking._mark_docked()  # sensor-confirmed terminal seam
    assert services.docking.native_readback(dock.run_id)["operation"]["result"] == "SUCCEEDED"
    with services.docking._lock:
        services.docking._state = DockState.CHARGING
    assert services.docking.native_readback(dock.run_id)["operation"]["result"] == "SUCCEEDED"
    services.docking.tick()

    response = client.post("/api/v1/docking/undock", headers=OPERATOR)
    assert response.status_code == 200, response.text
    undock = response.json()["operation"]
    assert undock["kind"] == "undock" and undock["phase"] == "SUBMITTED"
    class TravelledExecutor(DrivingExecutor):
        def travelled_m(self):
            return 1.0  # beyond this dock type's measured undock distance

    services.docking.executor = TravelledExecutor(services)
    turn_yaw = services.docking._dock.yaw + services.docking._type().undock_turn_rad
    services.state.set_pose(-1.2696, 0.0, turn_yaw)
    services.docking.tick()
    assert services.docking.native_readback(UUID(undock["run_id"]))["operation"]["result"] == "SUCCEEDED"
    assert services.docking.native_readback(dock.run_id)["operation"]["result"] == "SUCCEEDED"

    response = client.post("/api/v1/docking/dock", json={"dock": "parking"}, headers=OPERATOR)
    assert response.status_code == 200, response.text
    canceled = response.json()["operation"]["run_id"]
    closed = client.post("/api/v1/docking/cancel", headers=OPERATOR).json()["operation"]
    assert closed["run_id"] == canceled and closed["result"] == "CANCELED"
    assert services.docking.native_readback(UUID(undock["run_id"]))["operation"]["result"] == "SUCCEEDED"


def test_lost_undock_executor_cannot_be_a_native_success(core_client):
    client, services = docking_robot(core_client)
    services.docking._mark_docked()
    response = client.post("/api/v1/docking/undock", headers=OPERATOR)
    assert response.status_code == 200, response.text
    run_id = UUID(response.json()["operation"]["run_id"])
    services.docking.executor = None
    services.docking.tick()
    result = services.docking.native_readback(run_id)["operation"]
    assert (result["result"], result["reason"]) == ("FAILED", "BACKEND_ERROR")


def test_follow_hold_refollow_and_exact_closed_cancel(core_client):
    client, services = core_client()
    body = {"target_robot_id": "rosy_02", "distance": 0.5}
    first_response = client.post("/api/v1/swarm/follow", json=body, headers=OPERATOR)
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()["operation"]
    assert first["phase"] == "SUBMITTED"
    with services.swarm._lock:
        services.swarm._last_sample_at = services.swarm._clock() - 2
    services.swarm.tick()
    assert services.swarm.holding
    assert services.swarm.native_readback(UUID(first["run_id"]))["operation"]["phase"] == "RUNNING"

    second_response = client.post("/api/v1/swarm/follow", json=body, headers=OPERATOR)
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()["operation"]
    assert second["run_id"] != first["run_id"]
    assert services.swarm.native_readback(UUID(first["run_id"]))["operation"]["result"] == "PREEMPTED"
    closed = client.post("/api/v1/swarm/cancel", headers=OPERATOR).json()["operation"]
    assert closed["run_id"] == second["run_id"] and closed["result"] == "CANCELED"


def test_follow_close_fences_new_admission_until_old_cleanup(core_client):
    client, services = core_client()
    body = {"target_robot_id": "rosy_02", "distance": 0.5}
    assert client.post("/api/v1/swarm/follow", json=body, headers=OPERATOR).status_code == 200
    original_cancel = services.nav.cancel
    entered, release = threading.Event(), threading.Event()

    def blocked_cancel(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original_cancel(*args, **kwargs)

    services.nav.cancel = blocked_cancel
    worker = threading.Thread(target=services.swarm.cancel)
    worker.start()
    assert entered.wait(2)
    try:
        services.swarm.cancel()  # a no-op cancel must not revoke first cancel's fence
        with pytest.raises(SwarmError) as refused:
            services.swarm.reserve_follow(SwarmFollowParams(**body))
        assert refused.value.code == "OWNER_GENERATION_CHANGED"
    finally:
        release.set()
        worker.join(2)
        services.nav.cancel = original_cancel
    assert not worker.is_alive()
    token = services.swarm.reserve_follow(SwarmFollowParams(**body))
    services.swarm.release_follow_reservation(token)


def test_dock_and_undock_failure_and_undock_cancel_are_distinct(core_client):
    client, services = docking_robot(core_client)
    failed_dock = services.docking.native.current.run_id
    services.docking.abort("backend rejected movement")
    assert services.docking.native_readback(failed_dock)["operation"]["result"] == "FAILED"
    assert services.docking.native_readback(failed_dock)["operation"]["reason"] == "BACKEND_ERROR"

    # A fresh owner avoids using a failed dock as an undock prerequisite.
    client, services = docking_robot(core_client)
    services.docking._mark_docked()
    response = client.post("/api/v1/docking/undock", headers=OPERATOR)
    assert response.status_code == 200, response.text
    canceled_undock = UUID(response.json()["operation"]["run_id"])
    assert services.docking.state is DockState.UNDOCKING
    canceled = client.post("/api/v1/docking/cancel", headers=OPERATOR)
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["operation"]["run_id"] == str(canceled_undock)
    assert services.docking.native_readback(canceled_undock)["operation"]["result"] == "CANCELED"

    client, services = docking_robot(core_client)
    services.docking._mark_docked()
    response = client.post("/api/v1/docking/undock", headers=OPERATOR)
    failed_undock = UUID(response.json()["operation"]["run_id"])
    services.docking.abort("backend rejected undock")
    assert services.docking.native_readback(failed_undock)["operation"]["result"] == "FAILED"
    assert services.docking.native_readback(failed_undock)["operation"]["reason"] == "BACKEND_ERROR"

    _client, services = docking_robot(core_client)
    safety_dock = services.docking.native.current.run_id
    services.safety.estop = True
    services.docking.abort("emergency stop during docking")
    assert services.docking.native_readback(safety_dock)["operation"]["result"] == "CANCELED"
    assert services.docking.native_readback(safety_dock)["operation"]["reason"] == "SAFETY_STOP"


def test_paired_docking_cas_rejects_before_mode_or_backend(core_client):
    from test_docking_parking_wiring import sim_overrides

    client, services = core_client(config_overrides=sim_overrides())
    before = services.docking.native_readback()["owner"]
    path = "/api/v1/docking/dock"
    incomplete = client.post(path, json={"dock": "parking", "expected_boot_id": before["boot_id"]},
                             headers=OPERATOR)
    assert incomplete.status_code == 400
    assert incomplete.json()["error"]["code"] == "VALIDATION_ERROR"
    stale = client.post(path, json={"dock": "parking", "expected_boot_id": str(UUID(int=0)),
                                    "expected_owner_generation": before["owner_generation"]},
                        headers=OPERATOR)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "OWNER_GENERATION_CHANGED"
    assert services.docking.native_readback()["owner"] == before
    assert services.docking.state is DockState.UNDOCKED
    assert services.modes.mode is Mode.IDLE


def test_nav_terminal_reasons_and_single_home_run():
    nav, _events = _nav()
    nav.executor = SimpleNamespace(send_goal=lambda spec, **kwargs: None,
                                   cancel_goal=lambda: None)
    receipts = []
    spec = NavGoalSpec(1, 2, 0)
    nav.goal(spec, receipt_sink=receipts.append)
    rejected = receipts[-1].run_id
    nav.on_result(False, "REJECTED", native_run_id=rejected)
    assert nav.native_readback(rejected)["operation"]["reason"] == "BACKEND_REJECTED"

    now = [10.0]
    nav.lease_clock = lambda: now[0]
    nav.goal(spec, correlation_id="leased", lease_ttl_s=1.0, receipt_sink=receipts.append)
    leased = receipts[-1].run_id
    now[0] = 12.0
    assert nav.expire_goal_lease()
    assert nav.native_readback(leased)["operation"]["result"] == "EXPIRED"
    assert nav.native_readback(leased)["operation"]["reason"] == "LEASE_EXPIRED"

    nav.goal(spec, receipt_sink=receipts.append)
    stuck = receipts[-1].run_id
    nav.cancel(source="stuck_detector")
    assert nav.native_readback(stuck)["operation"]["result"] == "FAILED"
    assert nav.native_readback(stuck)["operation"]["reason"] == "STUCK"

    nav.resolve_goal = lambda **kwargs: NavGoalSpec(0, 0, 0)
    nav.home(receipt_sink=receipts.append)
    home = receipts[-1]
    assert home.kind == "home"
    assert len({receipt.run_id for receipt in receipts}) == 4
