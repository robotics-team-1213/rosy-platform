"""Native receipts stay bound to the owner admission, not caller correlation."""

from types import SimpleNamespace
import time

import pytest

from core.bridge.goal_tracker import GoalTracker
from core_features.navigation.manager import NavigationError, NavigationManager, NavGoalSpec
from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, ZERO
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits


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
