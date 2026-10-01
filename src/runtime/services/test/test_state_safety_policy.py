"""D-400: robot state carries the safety policy block when a provider is set."""

from core_common.protocol.schemas import SafetyPolicyStatus, StateSnapshot
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


def test_an_invalid_block_never_breaks_the_snapshot():
    state = StateManager(robot_id="rosy_01")
    state.set_safety_policy_provider(lambda: {"mode": 3})

    assert state.snapshot().safety_policy is None
