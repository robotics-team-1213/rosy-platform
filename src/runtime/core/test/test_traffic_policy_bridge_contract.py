"""ROS-free proof that line candidates cannot bypass traffic policy."""

from types import SimpleNamespace

import pytest

from core.bridge.traffic_gate import apply_line_candidate
from core.bridge.translate import road_evidence
from core_events.events.bus import EventBus
from core_features.line_follow import (
    LineFollowManager,
    LineFollowMode,
    LineObservation,
)
from core_features.traffic_policy import (
    TrafficPolicyConfig,
    TrafficPolicyManager,
    TrafficPolicyMode,
)


CONTEXT = {
    "id": "crosswalk",
    "confidence": 0.8,
    "profile_revision": "ctx-crosswalk-v1",
}


def payload(*, colour="RED", conflict=False, distance=0.08, context=None):
    value = {
        "source": "CAMERA_ROAD",
        "stamp": 10.0,
        "map_id": "map_260905_update_v2",
        "scene_revision": "road-scene-v1",
        "lane": {"visible": True, "error": 0.0, "confidence": 0.9},
        "stop_line": {
            "visible": True,
            "image_row": 180.0,
            "distance_m": distance,
            "confidence": 0.9,
        },
        "crosswalk": {
            "visible": True,
            "image_row": 150.0,
            "distance_m": 0.16,
            "confidence": 0.8,
        },
        "signal": {
            "visible": colour is not None,
            "colour": colour,
            "confidence": 0.9 if colour else 0.0,
            "conflict": conflict,
        },
    }
    if context is not None:
        # Copy: callers and mutate-lambdas must not share one dict.
        value["context"] = dict(context)
    return value


def managers(now):
    events = EventBus("rosy_01")
    line = LineFollowManager(events, clock=lambda: now[0])
    line.set_mode(LineFollowMode.CAMERA_LINE)
    line.observe(LineObservation(
        source=LineFollowMode.CAMERA_LINE,
        stamp=10.0,
        visible=True,
        error=0.0,
        confidence=1.0,
    ), received_at=now[0], source_now=10.0)
    traffic = TrafficPolicyManager(
        events,
        config=TrafficPolicyConfig(
            mode=TrafficPolicyMode.ENFORCED,
            map_id="map_260905_update_v2",
            scene_revision="road-scene-v1",
        ),
        clock=lambda: now[0],
    )
    return line, traffic


def test_nested_wire_payload_is_strictly_decoded():
    sample = road_evidence(payload())

    assert sample.stop_line_visible is True
    assert sample.stop_line_distance_m == pytest.approx(0.08)
    assert sample.crosswalk_visible is True
    assert sample.signal_colour == "RED"


def test_scene_context_decodes_when_present_and_stays_none_when_absent():
    absent = road_evidence(payload())
    assert absent.context_id is None
    assert absent.context_confidence is None
    assert absent.context_profile_revision is None

    present = road_evidence(payload(context=CONTEXT))
    assert present.context_id == "crosswalk"
    assert present.context_confidence == pytest.approx(0.8)
    assert present.context_profile_revision == "ctx-crosswalk-v1"


@pytest.mark.parametrize("mutate", [
    lambda value: value["context"].pop("id"),
    lambda value: value["context"].pop("confidence"),
    lambda value: value["context"].pop("profile_revision"),
    lambda value: value["context"].update(confidence=1.5),
    lambda value: value["context"].update(confidence="0.8"),
    lambda value: value["context"].update(profile_revision=""),
    lambda value: value.update(context={"id": "crosswalk"}),
    lambda value: value.update(context=None),
])
def test_malformed_scene_context_is_rejected(mutate):
    value = payload(context=CONTEXT)
    mutate(value)

    with pytest.raises((KeyError, TypeError, ValueError)):
        road_evidence(value)


def test_scene_context_does_not_change_gating_outcomes():
    now = [100.0]
    line, traffic = managers(now)
    with_context = road_evidence(payload(context=CONTEXT))
    traffic.observe(with_context, received_at=now[0],
                    source_now=with_context.stamp)
    command = SimpleNamespace(applied=[])
    command.set_nav_twist = (
        lambda twist, now=None: command.applied.append(twist))

    assert apply_line_candidate(
        line, traffic, command, line.tick(), now[0]) is True
    assert command.applied[-1].linear == 0.0
    assert traffic.status().state == "STOP_REQUIRED"

    without_context = road_evidence(payload())
    traffic.observe(without_context, received_at=now[0],
                    source_now=without_context.stamp)
    assert traffic.status().state == "STOP_REQUIRED"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("map_id"),
        lambda value: value["signal"].update(conflict="false"),
        lambda value: value["stop_line"].update(visible=1),
        lambda value: value["signal"].update(visible=False, colour="GREEN"),
        lambda value: value["stop_line"].update(distance_m="0.08"),
    ],
)
def test_malformed_wire_payload_is_rejected(mutate):
    value = payload()
    mutate(value)

    with pytest.raises((KeyError, TypeError, ValueError)):
        road_evidence(value)


@pytest.mark.parametrize("colour", ["RED", "YELLOW"])
def test_red_or_yellow_gates_line_candidate_to_zero(colour):
    now = [100.0]
    line, traffic = managers(now)
    sample = road_evidence(payload(colour=colour))
    traffic.observe(sample, received_at=now[0], source_now=sample.stamp)
    command = SimpleNamespace(applied=[])
    command.set_nav_twist = (
        lambda twist, now=None: command.applied.append(twist))

    assert apply_line_candidate(
        line, traffic, command, line.tick(), now[0]) is True

    assert command.applied[-1].linear == 0.0
    assert traffic.status().state == "STOP_REQUIRED"


def test_stale_road_evidence_gates_line_candidate_to_zero():
    now = [100.0]
    line, traffic = managers(now)
    sample = road_evidence(payload(distance=None))
    traffic.observe(sample, received_at=now[0], source_now=sample.stamp)
    now[0] += 0.41
    line.observe(LineObservation(
        source=LineFollowMode.CAMERA_LINE,
        stamp=10.41,
        visible=True,
        error=0.0,
        confidence=1.0,
    ), received_at=now[0], source_now=10.41)
    command = SimpleNamespace(applied=[])
    command.set_nav_twist = (
        lambda twist, now=None: command.applied.append(twist))

    apply_line_candidate(line, traffic, command, line.tick(), now[0])

    assert command.applied[-1].linear == 0.0
    assert traffic.status().reason == "road_evidence_stale"


def test_new_road_evidence_invalidates_precomputed_policy_decision():
    now = [100.0]
    line, traffic = managers(now)
    sample = road_evidence(payload(distance=0.5))
    traffic.observe(sample, received_at=now[0], source_now=sample.stamp)
    decision = traffic.gate(0.08, 0.0)
    conflict = road_evidence(payload(conflict=True))
    traffic.observe(conflict, received_at=now[0], source_now=conflict.stamp)
    applied = []

    assert traffic.apply_if_current(decision, applied.append) is False
    assert applied == []
