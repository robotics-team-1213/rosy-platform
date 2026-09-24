"""Nav2 목표 세대 관리 (moving goal 이 깨뜨린 단일 핸들 전제).

핸들은 불투명한 객체다 — rclpy 없이 전부 확인할 수 있다.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.bridge.goal_tracker import GoalTracker, on_response, on_result


def test_a_result_for_the_current_goal_is_current():
    tracker = GoalTracker()
    generation = tracker.opening()
    assert tracker.accepted(generation, "h1") is True

    assert tracker.finished(generation) is True
    assert tracker.live_count == 0


def test_a_result_for_a_superseded_goal_is_not_current():
    """선점된 목표의 abort 를 현재 목표의 실패로 읽으면 상태가 무너진다."""
    tracker = GoalTracker()
    first = tracker.opening()
    tracker.accepted(first, "h1")
    second = tracker.opening()
    tracker.accepted(second, "h2")

    assert tracker.finished(first) is False
    assert tracker.finished(second) is True


def test_an_acceptance_that_arrives_after_a_cancel_is_refused():
    """send 와 accept 사이의 취소 창. 등록해 버리면 아무도 못 거둔다."""
    tracker = GoalTracker()
    generation = tracker.opening()

    assert tracker.cancel_all() == []
    assert tracker.accepted(generation, "late") is False
    assert tracker.live_count == 0


def test_cancel_returns_every_live_handle_not_just_the_last():
    tracker = GoalTracker()
    for name in ("h1", "h2", "h3"):
        tracker.accepted(tracker.opening(), name)

    assert sorted(tracker.cancel_all()) == ["h1", "h2", "h3"]
    assert tracker.live_count == 0


def test_cancel_makes_every_outstanding_result_stale():
    tracker = GoalTracker()
    generation = tracker.opening()
    tracker.accepted(generation, "h1")

    tracker.cancel_all()

    assert tracker.finished(generation) is False


def test_a_rejection_is_current_only_for_the_latest_goal():
    tracker = GoalTracker()
    first = tracker.opening()
    second = tracker.opening()

    assert tracker.rejected(first) is False
    assert tracker.rejected(second) is True


# --- the two callbacks the bridge used to own (C1) ---------------------------

class _Nav:
    def __init__(self) -> None:
        self.calls: list = []

    def on_goal_accepted(self) -> None:
        self.calls.append(("on_goal_accepted",))

    def on_result(self, *args) -> None:
        self.calls.append(("on_result", args))


class _Future:
    def __init__(self, result=None, raises=None) -> None:
        self._result = result
        self._raises = raises

    def result(self):
        if self._raises is not None:
            raise self._raises
        return self._result


class _Handle:
    def __init__(self, accepted=True, result_future=None) -> None:
        self.accepted = accepted
        self.cancelled = False
        self.result_future = result_future or _Future()

    def cancel_goal_async(self) -> str:
        self.cancelled = True
        return "cancel-future"

    def get_result_async(self):
        return self.result_future


def test_a_rejected_goal_reports_failure_for_the_current_generation():
    tracker = GoalTracker()
    generation = tracker.opening()
    nav = _Nav()
    attached = []

    on_response(tracker, nav, _Future(_Handle(accepted=False)), generation,
                attach_result=lambda *a: attached.append(a))

    assert nav.calls == [("on_result", (False, "REJECTED"))]
    assert attached == []


def test_a_rejection_for_a_superseded_goal_is_not_reported():
    """A stale rejection must not fail the goal that replaced it."""
    tracker = GoalTracker()
    tracker.opening()
    second = tracker.opening()
    nav = _Nav()

    on_response(tracker, nav, _Future(_Handle(accepted=False)), second - 1,
                attach_result=lambda *a: None)

    assert nav.calls == []


def test_an_acceptance_for_a_superseded_goal_is_cancelled_not_registered():
    """Left alive, it is a Nav2 goal nobody owns — cancel it on the spot."""
    tracker = GoalTracker()
    first = tracker.opening()
    tracker.opening()
    nav = _Nav()
    handle = _Handle()
    attached = []

    on_response(tracker, nav, _Future(handle), first,
                attach_result=lambda *a: attached.append(a))

    assert handle.cancelled is True
    assert nav.calls == []
    assert attached == []
    assert tracker.live_count == 0


def test_a_current_acceptance_notifies_and_wires_the_result_future():
    tracker = GoalTracker()
    generation = tracker.opening()
    nav = _Nav()
    handle = _Handle(result_future=_Future("RESULT"))
    attached = []

    on_response(tracker, nav, _Future(handle), generation,
                attach_result=lambda *a: attached.append(a))

    assert nav.calls == [("on_goal_accepted",)]
    assert attached == [(handle.result_future, generation)]
    assert tracker.live_count == 1


def test_a_successful_result_status_is_read_as_success():
    """`4` is `GoalStatus.STATUS_SUCCEEDED` — rclpy hands back a status, not a bool."""
    tracker = GoalTracker()
    generation = tracker.opening()
    tracker.accepted(generation, "h1")
    nav = _Nav()

    on_result(tracker, nav, _Future(SimpleNamespace(status=4)), generation)

    assert nav.calls == [("on_result", (True,))]


def test_any_other_status_is_read_as_failure():
    tracker = GoalTracker()
    generation = tracker.opening()
    tracker.accepted(generation, "h1")
    nav = _Nav()

    on_result(tracker, nav, _Future(SimpleNamespace(status=5)), generation)

    assert nav.calls == [("on_result", (False,))]


def test_a_superseded_goal_result_is_dropped_entirely():
    """Reading this as the current goal's failure drops nav_state to FAILED,
    and the HOLD that follows can no longer cancel anything."""
    tracker = GoalTracker()
    first = tracker.opening()
    tracker.accepted(first, "h1")
    tracker.opening()                      # the goal moved on
    nav = _Nav()

    on_result(tracker, nav, _Future(SimpleNamespace(status=5)), first)

    assert nav.calls == []


def test_a_future_that_raises_becomes_a_failed_result_not_a_crash():
    tracker = GoalTracker()
    generation = tracker.opening()
    tracker.accepted(generation, "h1")
    nav = _Nav()

    on_result(tracker, nav, _Future(raises=RuntimeError("action server gone")),
              generation)

    assert nav.calls == [("on_result", (False, "action server gone"))]
