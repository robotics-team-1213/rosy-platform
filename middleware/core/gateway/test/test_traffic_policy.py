"""Road evidence policy gates drive candidates without owning ROS output."""

import pytest

from core_events.events.bus import EventBus
from core_features.traffic_policy import (
    RoadEvidence,
    SignalHeadEvidence,
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


def head(*, stamp=10.0, map_id="map_260905_update_v2",
         scene_revision="road-scene-v1", red=False, yellow=False,
         green=False, confidence=0.9, frozen=False, stable=True):
    return SignalHeadEvidence(
        stamp=stamp, map_id=map_id, scene_revision=scene_revision,
        red=red, yellow=yellow, green=green, confidence=confidence,
        frozen=frozen, stable=stable)


def observe_signal(manager, now, sample):
    manager.observe_signal(
        sample, received_at=now[0], source_now=sample.stamp)


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


def stop_and_go_rig():
    now = [100.0]
    manager = TrafficPolicyManager(
        EventBus("rosy_01"),
        config=TrafficPolicyConfig(
            mode=TrafficPolicyMode.ENFORCED,
            map_id="map_260905_update_v2",
            scene_revision="road-scene-v1",
            policy_revision="traffic-policy-v1",
            stop_dwell_s=0.5,
            junction_rule="stop_and_go",
        ),
        clock=lambda: now[0],
    )
    return now, manager


def test_unsignalized_rule_proceeds_after_stop_and_dwell():
    now, manager = stop_and_go_rig()
    sample = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9)

    observe(manager, now, sample)
    assert manager.gate(0.06, -0.05).linear == 0.0
    now[0] += 0.51
    observe(manager, now, sample)

    decision = manager.gate(0.06, -0.05)

    assert decision.linear == pytest.approx(0.06 * 0.5)
    assert decision.angular == pytest.approx(-0.05)
    assert manager.status().state == "PROCEED"
    assert manager.status().reason == "unsignalized_proceed"


@pytest.mark.parametrize("colour,confidence", [
    ("RED", 0.9), ("RED", 0.3), ("GREEN", 0.9),
])
def test_unsignalized_rule_holds_when_a_signal_is_observed(
        colour, confidence):
    now, manager = stop_and_go_rig()
    sample = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9,
        signal_colour=colour, signal_confidence=confidence)

    observe(manager, now, sample)
    manager.gate(0.06, 0.0)
    now[0] += 0.51
    observe(manager, now, sample)

    assert manager.gate(0.06, 0.0).linear == 0.0
    assert manager.status().state == "HOLD"
    assert manager.status().reason == "signal_unexpected"


def test_unsignalized_rule_does_not_override_signal_conflict():
    now, manager = stop_and_go_rig()
    observe(manager, now, evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9,
        signal_conflict=True))

    assert manager.gate(0.06, 0.0).linear == 0.0
    assert manager.status().reason == "signal_conflict"


def test_signal_controlled_default_still_waits_without_signal(rig):
    now, manager = rig
    sample = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9)

    observe(manager, now, sample)
    manager.gate(0.06, 0.0)
    now[0] += 10.0
    observe(manager, now, sample)

    assert manager.gate(0.06, 0.0).linear == 0.0
    assert manager.status().state == "WAIT_SIGNAL"
    assert manager.status().reason == "signal_unknown"
    assert manager.status().junction_rule == "signal_controlled"


def test_junction_rule_is_validated_and_staged(rig):
    _now, manager = rig
    with pytest.raises(ValueError):
        TrafficPolicyConfig(junction_rule="right_on_red")

    staged = manager.stage(
        {"junction_rule": "stop_and_go"}, actor="operator:test")

    assert staged["staged"]["junction_rule"] == "stop_and_go"
    assert staged["active"]["junction_rule"] == "signal_controlled"

    manager.apply_staged(actor="operator:test")

    assert manager.status().junction_rule == "stop_and_go"


def _dwell_at_stop_line(now, manager, road, light=None):
    """Reach a dwell-complete stop with fresh evidence on both channels."""
    observe(manager, now, road)
    if light is not None:
        observe_signal(manager, now, light)
    manager.gate(0.06, 0.0)
    now[0] += 0.51
    observe(manager, now, road)
    if light is not None:
        observe_signal(manager, now, light)


@pytest.mark.parametrize("lamps,reason", [
    ({"green": True}, "signal_green"),
    ({"red": True}, "signal_red"),
])
def test_observer_colour_alone_drives_verdict_after_stop(rig, lamps, reason):
    now, manager = rig
    road = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9)
    light = head(**lamps)
    _dwell_at_stop_line(now, manager, road, light)

    decision = manager.gate(0.06, 0.0)

    expected = 0.06 * 0.5 if reason == "signal_green" else 0.0
    assert decision.linear == pytest.approx(expected)
    assert manager.status().state == (
        "PROCEED" if reason == "signal_green" else "WAIT_SIGNAL")
    assert manager.status().reason == reason


@pytest.mark.parametrize("lamps", [{}, {"red": True, "green": True}])
def test_indeterminate_head_is_signal_dark_not_signal_unknown(rig, lamps):
    now, manager = rig
    road = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9)
    light = head(**lamps)
    _dwell_at_stop_line(now, manager, road, light)

    assert manager.gate(0.06, 0.0).linear == 0.0
    assert manager.status().state == "WAIT_SIGNAL"
    assert manager.status().reason == "signal_dark"


def test_observer_disagreement_with_camera_holds(rig):
    now, manager = rig
    road = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9,
        signal_colour="GREEN", signal_confidence=0.9)
    light = head(red=True)
    _dwell_at_stop_line(now, manager, road, light)

    assert manager.gate(0.06, 0.0).linear == 0.0
    assert manager.status().state == "HOLD"
    assert manager.status().reason == "signal_source_conflict"


@pytest.mark.parametrize("head_confidence,expected", [
    (0.3, "WAIT_SIGNAL"),
    (0.8, "PROCEED"),
])
def test_agreement_blends_confidence_with_camera(rig, head_confidence,
                                                 expected):
    now, manager = rig
    road = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9,
        signal_colour="GREEN", signal_confidence=0.9)
    light = head(green=True, confidence=head_confidence)
    _dwell_at_stop_line(now, manager, road, light)

    decision = manager.gate(0.06, 0.0)

    assert manager.status().state == expected
    if expected == "PROCEED":
        assert decision.linear == pytest.approx(0.06 * 0.5)
    else:
        assert manager.status().reason == "signal_low_confidence"


def test_stale_head_falls_back_to_camera_alone(rig):
    now, manager = rig
    observe_signal(manager, now, head(green=True))
    now[0] += 0.41
    road = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9,
        signal_colour="RED", signal_confidence=0.9)
    observe(manager, now, road)
    manager.gate(0.06, 0.0)
    now[0] += 0.51
    observe(manager, now, road)

    assert manager.gate(0.06, 0.0).linear == 0.0
    assert manager.status().state == "WAIT_SIGNAL"
    assert manager.status().reason == "signal_red"


@pytest.mark.parametrize("light", [
    head(frozen=True),
    head(stable=False),
    head(scene_revision="wrong-scene"),
])
def test_unusable_head_is_silence(rig, light):
    now, manager = rig
    road = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9)
    _dwell_at_stop_line(now, manager, road, light)

    assert manager.gate(0.06, 0.0).linear == 0.0
    assert manager.status().state == "WAIT_SIGNAL"
    assert manager.status().reason == "signal_unknown"


@pytest.mark.parametrize("lamps", [{"green": True}, {}])
def test_stop_and_go_holds_on_any_usable_head_evidence(lamps):
    now, manager = stop_and_go_rig()
    road = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9)
    light = head(**lamps)
    _dwell_at_stop_line(now, manager, road, light)

    assert manager.gate(0.06, 0.0).linear == 0.0
    assert manager.status().state == "HOLD"
    assert manager.status().reason == "signal_unexpected"


def test_signal_head_evidence_form_is_validated():
    with pytest.raises(ValueError):
        SignalHeadEvidence(stamp=10.0, map_id="", scene_revision="s")
    with pytest.raises(ValueError):
        SignalHeadEvidence(
            stamp=10.0, map_id="m", scene_revision="s", confidence=1.5)
    with pytest.raises(ValueError):
        SignalHeadEvidence(
            stamp=float("nan"), map_id="m", scene_revision="s")


def test_observe_signal_rejects_future_stamp(rig):
    _now, manager = rig
    with pytest.raises(ValueError):
        manager.observe_signal(
            head(stamp=12.0), received_at=100.0, source_now=10.0)


def test_observe_signal_invalidates_prior_decision(rig):
    now, manager = rig
    observe(manager, now, evidence())
    decision = manager.gate(0.08, 0.0)

    observe_signal(manager, now, head(green=True))

    assert manager.apply_if_current(decision, lambda _: None) is False


def test_reset_clears_signal_head_evidence(rig):
    now, manager = rig
    road = evidence(
        stop_visible=True, stop_distance_m=0.08, stop_confidence=0.9)
    _dwell_at_stop_line(now, manager, road, head(green=True))
    manager.gate(0.06, 0.0)
    assert manager.status().reason == "signal_green"

    manager.reset("estop")

    _dwell_at_stop_line(now, manager, road)
    manager.gate(0.06, 0.0)
    assert manager.status().reason == "signal_unknown"


def test_status_exposes_signal_head_view(rig):
    now, manager = rig
    observe(manager, now, evidence())
    manager.gate(0.08, 0.0)

    status = manager.status()
    assert status.signal_source_kind == "camera"
    assert status.signal_head_age_s is None
    assert status.signal_head_frozen is False

    observe_signal(manager, now, head(green=True))
    manager.gate(0.08, 0.0)

    status = manager.status()
    assert status.signal_source_kind == "fused"
    assert status.signal_head_age_s == pytest.approx(0.0)

    now[0] += 0.41
    manager.gate(0.08, 0.0)

    status = manager.status()
    assert status.signal_source_kind == "camera"
    assert status.signal_head_age_s == pytest.approx(0.41)


def test_frozen_head_flags_status_but_stays_camera_kind(rig):
    now, manager = rig
    observe(manager, now, evidence())
    observe_signal(manager, now, head(green=True, frozen=True))
    manager.gate(0.08, 0.0)

    status = manager.status()
    assert status.signal_source_kind == "camera"
    assert status.signal_head_frozen is True


def test_signal_observer_is_absent_without_binding(core_client):
    _client, services = core_client()
    assert services.signal_observer is None


def test_signal_observer_binds_and_starts_when_configured(core_client):
    _client, services = core_client(config_overrides={
        "traffic_policy": {
            "mode": "ENFORCED",
            "map_id": "map_260905_update_v2",
            "scene_revision": "road-scene-v1",
            "signal_observer": {
                "url": "http://127.0.0.1:9",
                "roi_map": {"left": "red", "mid": "yellow", "right": "green"},
            },
        },
    })
    try:
        assert services.signal_observer is not None
        assert services.signal_observer.poller.config.url == (
            "http://127.0.0.1:9")
        snapshot = services.state.snapshot()
        assert snapshot.traffic_policy.signal_source_kind == "camera"
    finally:
        services.signal_observer.stop()


def test_signal_observer_without_map_scene_fails_the_build(core_client):
    with pytest.raises(ValueError):
        core_client(config_overrides={
            "traffic_policy": {
                "mode": "DISABLED",
                "map_id": "",
                "scene_revision": "",
                "signal_observer": {
                    "url": "http://127.0.0.1:9",
                    "roi_map": {"left": "red"},
                },
            },
        })


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
            "junction_rule": "stop_and_go",
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
    assert snapshot.traffic_policy.junction_rule == "stop_and_go"
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
