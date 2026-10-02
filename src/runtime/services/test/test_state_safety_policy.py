"""D-400: robot state carries the safety policy block when a provider is set."""

import logging

from core_common.protocol.schemas import HeartbeatPayload, SafetyPolicyStatus, StateSnapshot
from core_features.safety.shadow import ShadowLog, ShadowVerdict
from core_features.state.manager import StateManager


def test_state_model_accepts_the_safety_policy_block():
    block = {"mode": "shadow", "mode_effective": "shadow", "mode_error": "", "revision": "abcd1234abcd1234",
             "sources": {"lidar_yaw_offset": "line_follow: hand value"},
             "shadow": {"counts": {"allow": 3, "limit": 1, "stop": 0, "unavailable": 0},
                        "last_stop": None, "last_unavailable": None,
                        "eval_ms": {"p50": 0.4, "p99": 1.1, "n": 4},
                        "dropped_events": 0, "suppressed_events": 2, "record_errors": 0}}

    status = SafetyPolicyStatus.model_validate(block)

    assert status.mode_effective == "shadow"
    assert status.shadow.counts["limit"] == 1
    assert "safety_policy" in StateSnapshot.model_fields
    assert StateSnapshot.model_fields["safety_policy"].default is None


def test_state_manager_reports_the_provider_block():
    state = StateManager(robot_id="rosy_01")
    state.set_safety_policy_provider(lambda: {"mode": "off", "mode_effective": "off",
                                              "mode_error": "", "revision": "", "sources": {},
                                              "shadow": None})

    snapshot = state.snapshot()

    assert snapshot.safety_policy.mode == "off"
    assert snapshot.model_dump()["safety_policy"]["mode"] == "off"


def test_without_a_provider_the_block_is_null():
    snapshot = StateManager(robot_id="rosy_01").snapshot()

    assert snapshot.safety_policy is None
    assert "safety_policy" in snapshot.model_dump()


def test_a_raising_provider_never_breaks_the_snapshot():
    state = StateManager(robot_id="rosy_01")

    def boom():
        raise RuntimeError("shadow log gone")

    state.set_safety_policy_provider(boom)

    assert state.snapshot().safety_policy is None


def _block(shadow: dict) -> dict:
    return {"mode": "shadow", "mode_effective": "shadow", "mode_error": "", "revision": "abcd1234abcd1234",
            "sources": {}, "shadow": {**shadow, "record_errors": 0}}


def test_the_real_producer_round_trips_when_empty():
    status = SafetyPolicyStatus.model_validate(_block(ShadowLog().snapshot()))

    assert status.shadow.eval_ms.p50 is None
    assert status.shadow.eval_ms.n == 0
    assert status.shadow.last_stop is None


def test_the_real_producer_round_trips_after_records():
    log = ShadowLog()
    for t, verdict, reason in ((1.0, "allow", ""), (1.2345678, "stop", "pickup")):
        log.record(ShadowVerdict(t=t, source="navigation", commanded=(0.1, 0.0), output=(0.1, 0.0),
                                 verdict=verdict, limited=(0.0, 0.0), reason=reason, eval_ms=0.5))

    status = SafetyPolicyStatus.model_validate(_block(log.snapshot()))

    assert status.shadow.last_stop.reason == "pickup"
    assert status.shadow.last_stop.t == 1.235
    assert status.shadow.counts["allow"] == 1
    assert status.shadow.eval_ms.n == 2


def test_the_block_rides_the_heartbeat_json():
    state = StateManager(robot_id="rosy_01")
    log = ShadowLog()
    log.record(ShadowVerdict(t=1.0, source="manual", commanded=(0.1, 0.0), output=(0.1, 0.0),
                             verdict="stop", limited=(0.0, 0.0), reason="cliff", eval_ms=0.4))
    state.set_safety_policy_provider(lambda: _block(log.snapshot()))

    dumped = HeartbeatPayload(state_snapshot=state.snapshot()).model_dump(mode="json")

    policy = dumped["state_snapshot"]["safety_policy"]
    assert policy["mode_effective"] == "shadow"
    assert policy["shadow"]["last_stop"] == {"t": 1.0, "reason": "cliff", "source": "manual"}
    assert set(policy["shadow"]["eval_ms"]) == {"p50", "p99", "n"}


def test_a_failing_provider_is_logged_once_per_error_type(caplog):
    state = StateManager(robot_id="rosy_01")
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 4:
            return None
        raise RuntimeError("gone") if calls["n"] < 4 else ValueError("bad")

    state.set_safety_policy_provider(flaky)
    with caplog.at_level(logging.WARNING, logger="core_features.state.manager"):
        state.snapshot()
        state.snapshot()
        assert len(caplog.records) == 1
        state.snapshot()
        assert len(caplog.records) == 1
        state.snapshot()      # success resets
        state.snapshot()      # fails again: logged again
    assert len(caplog.records) == 2


def test_an_invalid_block_never_breaks_the_snapshot():
    state = StateManager(robot_id="rosy_01")
    state.set_safety_policy_provider(lambda: {"mode": 3})

    assert state.snapshot().safety_policy is None
