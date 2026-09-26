"""Road evidence policy gates drive candidates without owning ROS output."""

import pytest

from core_events.events.bus import EventBus
from core_features.traffic_policy import (
    RoadEvidence,
    TrafficPolicyConfig,
    TrafficPolicyManager,
    TrafficPolicyMode,
)


@pytest.fixture
def rig():
    now = [100.0]
    manager = TrafficPolicyManager(
        EventBus("rosy_01"),
        config=TrafficPolicyConfig(
            mode=TrafficPolicyMode.ENFORCED,
            map_id="map_260905_update_v2",
            scene_revision="road-scene-v1",
            policy_revision="traffic-policy-v1",
            approach_distance_m=0.35,
            stop_distance_m=0.12,
            stop_dwell_s=0.5,
            stale_after_s=0.4,
            min_confidence=0.5,
        ),
        clock=lambda: now[0],
    )
    return now, manager


def evidence(*, stamp=10.0, map_id="map_260905_update_v2",
             scene_revision="road-scene-v1", stop_visible=False,
             stop_distance_m=None, stop_confidence=0.0,
             crosswalk_visible=False, signal_colour=None,
             signal_confidence=0.0, signal_conflict=False,
             context_id=None, context_confidence=None,
             context_profile_revision=None):
    return RoadEvidence(
        source="CAMERA_ROAD",
        stamp=stamp,
        map_id=map_id,
        scene_revision=scene_revision,
        stop_line_visible=stop_visible,
        stop_line_distance_m=stop_distance_m,
        stop_line_confidence=stop_confidence,
        crosswalk_visible=crosswalk_visible,
        signal_colour=signal_colour,
        signal_confidence=signal_confidence,
        signal_conflict=signal_conflict,
        context_id=context_id,
        context_confidence=context_confidence,
        context_profile_revision=context_profile_revision,
    )


def observe(manager, now, sample):
    manager.observe(sample, received_at=now[0], source_now=sample.stamp)


def test_disabled_policy_preserves_candidate_without_evidence():
    manager = TrafficPolicyManager(
        EventBus("rosy_01"),
        config=TrafficPolicyConfig(mode=TrafficPolicyMode.DISABLED),
    )

    decision = manager.gate(0.08, -0.2)

    assert (decision.linear, decision.angular) == pytest.approx((0.08, -0.2))
    assert manager.status().state == "DISABLED"

    manager.reset("estop")

    assert manager.status().state == "DISABLED"
    assert manager.status().reason == "policy_disabled"


def test_enforced_policy_holds_without_fresh_evidence(rig):
    _now, manager = rig

    decision = manager.gate(0.08, 0.1)

    assert (decision.linear, decision.angular) == (0.0, 0.0)
    assert manager.status().state == "HOLD"
    assert manager.status().reason == "no_road_evidence"


def test_clear_road_follows_candidate(rig):
    now, manager = rig
    observe(manager, now, evidence())

    decision = manager.gate(0.08, -0.2)

    assert (decision.linear, decision.angular) == pytest.approx((0.08, -0.2))
    assert manager.status().state == "FOLLOW"


def test_approach_distance_adaptively_reduces_linear_speed(rig):
    now, manager = rig
    observe(manager, now, evidence(
        stop_visible=True, stop_distance_m=0.20, stop_confidence=0.9))

    decision = manager.gate(0.08, 0.1)

    assert 0.0 < decision.linear < 0.08
    assert decision.angular == pytest.approx(0.1)
    assert manager.status().state == "APPROACH"


def test_green_at_stop_line_requires_complete_stop_and_dwell(rig):
    now, manager = rig
    sample = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9,
        signal_colour="GREEN", signal_confidence=0.9)
    observe(manager, now, sample)

    first = manager.gate(0.06, 0.0)
    now[0] += 0.49
    observe(manager, now, sample)
    dwelling = manager.gate(0.06, 0.0)
    now[0] += 0.02
    observe(manager, now, sample)
    proceed = manager.gate(0.06, 0.0)

    assert first.linear == dwelling.linear == 0.0
    assert proceed.linear > 0.0
    assert manager.status().state == "PROCEED"


@pytest.mark.parametrize("colour", ["RED", "YELLOW"])
def test_red_and_yellow_wait_after_required_stop(rig, colour):
    now, manager = rig
    sample = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9,
        signal_colour=colour, signal_confidence=0.9)
    observe(manager, now, sample)

    assert manager.gate(0.06, 0.0).linear == 0.0
    now[0] += 0.51
    observe(manager, now, sample)
    assert manager.gate(0.06, 0.0).linear == 0.0
    assert manager.status().state == "WAIT_SIGNAL"
    assert manager.status().reason == f"signal_{colour.lower()}"


@pytest.mark.parametrize(
    "sample,reason",
    [
        (evidence(signal_conflict=True), "signal_conflict"),
        (evidence(map_id="wrong-map"), "map_mismatch"),
        (evidence(scene_revision="wrong-scene"), "scene_mismatch"),
        (evidence(stop_visible=True, stop_distance_m=None,
                  stop_confidence=0.9), "stop_distance_unavailable"),
    ],
)
def test_conflicting_or_unbound_evidence_holds(rig, sample, reason):
    now, manager = rig
    observe(manager, now, sample)

    assert manager.gate(0.08, 0.0).linear == 0.0
    assert manager.status().state == "HOLD"
    assert manager.status().reason == reason


def test_stale_evidence_holds(rig):
    now, manager = rig
    observe(manager, now, evidence())
    now[0] += 0.41

    assert manager.gate(0.08, 0.0).linear == 0.0
    assert manager.status().reason == "road_evidence_stale"


def test_monitor_only_reports_violation_but_does_not_gate_candidate(rig):
    now, manager = rig
    manager.set_mode(TrafficPolicyMode.MONITOR_ONLY)
    observe(manager, now, evidence(signal_conflict=True))

    decision = manager.gate(0.08, 0.2)

    assert (decision.linear, decision.angular) == pytest.approx((0.08, 0.2))
    assert manager.status().state == "HOLD"
    assert manager.status().enforced is False


def test_decision_cannot_apply_after_new_evidence_or_policy_revision(rig):
    now, manager = rig
    observe(manager, now, evidence())
    stale_decision = manager.gate(0.08, 0.0)
    observe(manager, now, evidence(signal_conflict=True))
    applied = []

    assert manager.apply_if_current(stale_decision, applied.append) is False
    assert applied == []

    current = manager.gate(0.08, 0.0)
    manager.set_mode(TrafficPolicyMode.MONITOR_ONLY)
    assert manager.apply_if_current(current, applied.append) is False
    assert applied == []


def test_reset_clears_stop_progress_and_requires_new_evidence(rig):
    now, manager = rig
    sample = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9,
        signal_colour="GREEN", signal_confidence=0.9)
    observe(manager, now, sample)
    manager.gate(0.06, 0.0)
    now[0] += 0.6
    observe(manager, now, sample)
    assert manager.gate(0.06, 0.0).linear > 0.0

    manager.reset("estop")

    assert manager.gate(0.06, 0.0).linear == 0.0
    assert manager.status().reason == "no_road_evidence"


def test_core_services_wires_policy_and_estop_resets_evidence(core_client):
    _client, services = core_client(config_overrides={
        "traffic_policy": {
            "mode": "ENFORCED",
            "map_id": "map_260905_update_v2",
            "scene_revision": "road-scene-v1",
            "policy_revision": "traffic-policy-v1",
        },
    })
    sample = evidence()
    services.traffic_policy.observe(
        sample, received_at=100.0, source_now=sample.stamp)
    assert services.traffic_policy.gate(0.05, 0.0, now=100.0).linear > 0.0

    services.safety.trigger_estop("test")

    assert services.traffic_policy.gate(
        0.05, 0.0, now=100.0).linear == 0.0
    assert services.traffic_policy.status().reason == "no_road_evidence"
    snapshot = services.state.snapshot()
    assert snapshot.traffic_policy.policy_revision == "traffic-policy-v1"
    assert snapshot.traffic_policy.reason == "no_road_evidence"


def test_policy_configuration_is_staged_then_applied_atomically(rig):
    now, manager = rig
    observe(manager, now, evidence())
    old_decision = manager.gate(0.05, 0.0)

    staged = manager.stage({
        "mode": "MONITOR_ONLY",
        "policy_revision": "traffic-policy-v2",
        "approach_distance_m": 0.40,
    }, actor="operator:test")

    assert manager.mode is TrafficPolicyMode.ENFORCED
    assert staged["staged"]["mode"] == "MONITOR_ONLY"
    assert staged["active"]["policy_revision"] == "traffic-policy-v1"

    applied = manager.apply_staged(actor="operator:test")

    assert manager.mode is TrafficPolicyMode.MONITOR_ONLY
    assert applied["active"]["policy_revision"] == "traffic-policy-v2"
    assert applied["staged"] is None
    assert manager.apply_if_current(old_decision, lambda _: None) is False
    assert manager.status().reason == "no_road_evidence"


def test_invalid_staged_configuration_does_not_replace_active_policy(rig):
    _now, manager = rig

    with pytest.raises(ValueError):
        manager.stage({
            "stop_distance_m": 0.50,
            "approach_distance_m": 0.20,
        }, actor="operator:test")

    assert manager.configuration()["active"]["stop_distance_m"] == 0.12
    assert manager.configuration()["staged"] is None


def test_simulation_signal_control_requires_explicit_capability():
    disabled = TrafficPolicyManager(EventBus("rosy_01"))
    with pytest.raises(RuntimeError, match="unavailable"):
        disabled.set_simulation_signal("GREEN", actor="operator:test")

    enabled = TrafficPolicyManager(
        EventBus("rosy_01"), simulation_signal_control=True)
    result = enabled.set_simulation_signal("GREEN", actor="operator:test")

    assert result == {"available": True, "colour": "GREEN"}
    with pytest.raises(ValueError):
        enabled.set_simulation_signal("BLUE", actor="operator:test")


def test_road_evidence_context_fields_are_all_or_none():
    with pytest.raises(ValueError):
        evidence(context_id="crosswalk")
    with pytest.raises(ValueError):
        evidence(context_id="crosswalk", context_confidence=0.8)

    plain = evidence()
    assert plain.context_id is None
    assert plain.context_confidence is None
    assert plain.context_profile_revision is None


def test_road_evidence_context_confidence_is_bounded():
    with pytest.raises(ValueError):
        evidence(
            context_id="crosswalk",
            context_confidence=1.5,
            context_profile_revision="ctx-crosswalk-v1")
    with pytest.raises(ValueError):
        evidence(
            context_id=" ",
            context_confidence=0.8,
            context_profile_revision="ctx-crosswalk-v1")


def test_road_evidence_accepts_complete_context():
    contextual = evidence(
        context_id="crosswalk",
        context_confidence=0.8,
        context_profile_revision="ctx-crosswalk-v1")

    assert contextual.context_id == "crosswalk"
    assert contextual.context_confidence == pytest.approx(0.8)
    assert contextual.context_profile_revision == "ctx-crosswalk-v1"


def test_scene_context_evidence_does_not_change_the_verdict(rig):
    now, manager = rig
    stopped = dict(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9)
    plain = evidence(**stopped)
    contextual = evidence(
        context_id="crosswalk",
        context_confidence=0.8,
        context_profile_revision="ctx-crosswalk-v1",
        **stopped)

    manager.observe(plain, received_at=now[0], source_now=plain.stamp)
    assert manager.gate(0.08, 0.0, now=now[0]).linear == 0.0
    assert manager.status().state == "STOP_REQUIRED"

    manager.observe(contextual, received_at=now[0],
                    source_now=contextual.stamp)
    assert manager.gate(0.08, 0.0, now=now[0]).linear == 0.0
    assert manager.status().state == "STOP_REQUIRED"
