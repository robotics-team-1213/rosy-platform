"""D-400: shadow evaluation judges like enforce but changes nothing."""

from types import SimpleNamespace

import pytest

from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits


class FakePolicy:
    """Duck-typed Control CommandPolicy: evaluate(...) -> (snapshot, result) or None."""

    revision = "rev-1"

    def __init__(self, reason="allow", linear=0.05, angular=0.4, raises=False, none=False):
        self.reason, self.linear, self.angular = reason, linear, angular
        self.raises, self.none = raises, none

    def evaluate(self, linear, angular, now, allow_bounded_sweep=False):
        if self.raises:
            raise RuntimeError("boom")
        if self.none:
            return None
        snapshot = SimpleNamespace(calibration_revision="rev-1", observed_at=now - 0.05, expires_at=now + 0.3)
        return snapshot, SimpleNamespace(reason=self.reason, linear=self.linear, angular=self.angular)


def _safety(policy):
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    safety._policy_clock = lambda: 1.0          # deterministic eval time (0 ms)
    listened = []
    safety.policy_listeners.append(lambda: listened.append(True))
    safety.bind_shadow_control_policy(policy)
    return safety, listened


def test_shadow_binding_keeps_enforcement_off():
    safety, listened = _safety(FakePolicy())

    assert safety.policy_mode == "shadow"
    assert safety.policy_required is False
    assert listened == []                       # binding a shadow never clears commands
    assert safety.evaluate_candidate(1, "navigation", 0.1, 0.0, 10.0) == (0.1, 0.0)


def test_limit_verdict_records_the_limited_command():
    safety, _ = _safety(FakePolicy(reason="motion_limited", linear=0.05, angular=0.4))

    safety.shadow_evaluate(1, "navigation", 0.1, 0.6, 10.0, output=(0.1, 0.6))

    (event,) = safety.shadow.drain()
    assert event["verdict"] == "limit"
    assert event["limited"] == [0.05, 0.4]


def test_allow_verdict_when_limits_cover_the_command():
    safety, _ = _safety(FakePolicy(reason="allow", linear=0.2, angular=0.8))

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

    (event,) = safety.shadow.drain()
    assert event["verdict"] == "allow"
    assert event["limited"] == event["commanded"]


@pytest.mark.parametrize("policy,verdict", [(FakePolicy(reason="pickup"), "stop"),
                                            (FakePolicy(raises=True), "unavailable"),
                                            (FakePolicy(none=True), "unavailable")])
def test_stop_and_failure_never_latch(policy, verdict):
    safety, _ = _safety(policy)
    safety.policy_reason = "untouched"

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

    assert safety.estop is False
    assert safety.policy_reason == "untouched"
    assert safety.policy_required is False and safety.policy_mode == "shadow"
    assert safety.shadow.snapshot()["counts"][verdict] == 1


def test_stop_verdict_records_zero_limited_and_last_stop():
    safety, _ = _safety(FakePolicy(reason="pickup"))

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

    (event,) = safety.shadow.drain()
    assert event["limited"] == [0.0, 0.0]
    assert safety.shadow.snapshot()["last_stop"]["reason"] == "pickup"


def test_mismatched_calibration_revision_is_unavailable():
    class Other(FakePolicy):
        def evaluate(self, linear, angular, now, allow_bounded_sweep=False):
            snapshot, result = super().evaluate(linear, angular, now)
            snapshot.calibration_revision = "other"
            return snapshot, result

    safety, _ = _safety(Other())

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

    snap = safety.shadow.snapshot()
    assert snap["counts"]["unavailable"] == 1
    assert snap["last_unavailable"]["reason"] == "policy_invalid"


def test_eval_time_is_recorded():
    safety, _ = _safety(FakePolicy())

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

    assert safety.shadow.snapshot()["eval_ms"]["n"] == 1


def test_a_failing_clock_never_escapes():
    safety, _ = _safety(FakePolicy())
    calls = []

    def clock():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("clock")
        return 1.0

    safety._policy_clock = clock

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))   # must not raise

    snap = safety.shadow.snapshot()
    assert safety.shadow_record_errors == 0
    assert snap["counts"]["unavailable"] == 1


def test_shadow_then_enforce_is_refused():
    safety, _ = _safety(FakePolicy())

    with pytest.raises(ValueError, match="exclusive"):
        safety.bind_control_policy(FakePolicy())

    assert safety.policy_mode == "shadow" and safety.policy_required is False


def test_shadow_then_bind_policy_is_refused():
    safety, _ = _safety(FakePolicy())

    with pytest.raises(ValueError, match="exclusive"):
        safety.bind_policy(lambda request: None, "rev")

    assert safety.policy_mode == "shadow" and safety.policy_required is False


def test_second_shadow_binding_is_refused_and_keeps_the_log():
    safety, _ = _safety(FakePolicy())
    log = safety.shadow

    with pytest.raises(ValueError, match="exclusive"):
        safety.bind_shadow_control_policy(FakePolicy())

    assert safety.shadow is log


def test_enforce_then_shadow_is_refused():
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    safety.bind_control_policy(FakePolicy())

    with pytest.raises(ValueError, match="exclusive"):
        safety.bind_shadow_control_policy(FakePolicy())

    assert safety.policy_mode == "enforce" and safety.shadow is None


def test_shadow_on_a_required_manager_is_refused():
    safety = SafetyManager(SpeedLimits(), BatteryPolicy(), policy_required=True)

    with pytest.raises(ValueError, match="exclusive"):
        safety.bind_shadow_control_policy(FakePolicy())

    assert safety.shadow is None


def test_over_budget_evaluation_is_unavailable():
    safety, _ = _safety(FakePolicy())
    ticks = iter([1.0, 1.02])                   # 20 ms
    safety._policy_clock = lambda: next(ticks)

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

    snap = safety.shadow.snapshot()
    assert snap["counts"]["unavailable"] == 1
    assert snap["last_unavailable"]["reason"] == "policy_invalid"
    assert snap["eval_ms"]["p50"] == pytest.approx(20.0)


def test_without_a_shadow_binding_nothing_is_recorded():
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

    assert safety.shadow is None
    assert safety.policy_mode == "off"


def test_stop_reason_that_looks_like_a_failure_is_still_a_stop():
    safety, _ = _safety(FakePolicy(reason="policy_failed"))   # not in the limit list -> disposition stop

    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))

    assert safety.shadow.snapshot()["counts"]["stop"] == 1


def test_a_failing_recorder_never_escapes():
    safety, _ = _safety(FakePolicy())

    class Broken:
        def record(self, verdict):
            raise KeyError("boom")

    safety.shadow = Broken()
    safety.shadow_evaluate(1, "navigation", 0.1, 0.0, 10.0, output=(0.1, 0.0))   # must not raise

    assert safety.shadow_record_errors == 1


def test_enforce_binding_sets_enforce_mode():
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    safety.bind_control_policy(FakePolicy())
    assert safety.policy_mode == "enforce" and safety.policy_required is True and safety.shadow is None
