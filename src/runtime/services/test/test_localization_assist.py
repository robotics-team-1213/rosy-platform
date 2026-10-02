"""D-395 Phase 2 lane B: CORE's ROS-free side of fleet-assisted localization.

Contract: docs/plans/2026-10-01-d395-phase2-interfaces.md §1. The bridge hands
raw JSON from `localization/state|candidates|result` to `LocalizationAssist`;
these tests drive it the same way, without rclpy.
"""

from __future__ import annotations

import json

import pytest

from core_common.protocol.localization import (
    DecisionSource,
    LocalizationDecision,
    LocState,
    PoseFrame,
)
from core_features.localization import STATE_STALE_S, LocalizationAssist


class _Events:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def publish(self, type_, severity="info", source="", data=None):
        self.sent.append((type_, str(severity), dict(data or {})))

    def named(self, name):
        return [data for type_, _sev, data in self.sent if type_ == name]


class _Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _state(state="UNKNOWN", frame="map", request_id=None, **extra) -> str:
    status = {"state": state, "pose_frame": frame, "request_id": request_id, **extra}
    return json.dumps({"status": status, "pose": None, "stamp": 1.0})


def _report(request_id="req-1", **extra) -> str:
    body = {"request_id": request_id,
            "candidates": [{"x": 1.0, "y": 2.0, "yaw": 0.0, "scan_fit": 0.9},
                           {"x": 3.0, "y": 2.0, "yaw": 3.1, "scan_fit": 0.9}],
            "stamp": 5.0, **extra}
    return json.dumps(body)


@pytest.fixture
def assist():
    events = _Events()
    mono = _Clock()
    cancels: list[str] = []
    published: list[dict] = []
    suspects: list[dict] = []
    loc = LocalizationAssist(events, robot_id=lambda: "rosy_07", monotonic=mono)
    loc.clock = lambda: 4242.5
    loc.on_localized = lambda: cancels.append("cancel")
    loc.publish_decision = published.append
    loc.publish_suspect = suspects.append
    loc.events, loc.mono, loc.cancels = events, mono, cancels
    loc.published, loc.suspects = published, suspects
    return loc


def test_no_state_message_means_a_pre_d395_robot(assist):
    assert assist.status() is None
    assert not assist.reporting
    assert assist.candidates() is None


def test_state_message_fills_the_status(assist):
    assist.on_state(_state("CANDIDATES", request_id="req-1"))
    status = assist.status()
    assert status.state is LocState.CANDIDATES
    assert status.pose_frame is PoseFrame.MAP
    assert status.request_id == "req-1"
    assert assist.reporting


def test_frame_is_odom_while_core_substitutes_odom_for_the_map_pose(assist):
    assist.on_state(_state("LOCALIZED", frame="map"))
    assist.tick(odom_owns_pose=True)
    assert assist.status().pose_frame is PoseFrame.ODOM
    assist.tick(odom_owns_pose=False)
    assert assist.status().pose_frame is PoseFrame.MAP


def test_core_never_upgrades_an_odom_frame_to_map(assist):
    assist.on_state(_state("SUSPECT", frame="odom"))
    assist.tick(odom_owns_pose=False)
    assert assist.status().pose_frame is PoseFrame.ODOM


def test_a_silent_sensing_node_fails_closed_to_unknown(assist):
    assist.on_state(_state("LOCALIZED"))
    assist.mono.now += STATE_STALE_S + 0.1
    status = assist.status()
    assert status.state is LocState.UNKNOWN
    assert status.reason == "state_stale"


@pytest.mark.parametrize("raw", [
    "not json", "[]", json.dumps({"status": {"state": "LOST", "pose_frame": "map"}}),
    json.dumps({"pose": None}),
])
def test_a_malformed_state_is_ignored(assist, raw):
    assist.on_state(_state("LOCALIZED"))
    assist.on_state(raw)
    assert assist.status().state is LocState.LOCALIZED


def test_state_event_only_on_change(assist):
    assist.on_state(_state("UNKNOWN"))
    assist.on_state(_state("UNKNOWN"))
    assist.on_state(_state("CANDIDATES", request_id="req-1"))
    states = assist.events.named("localization.state")
    assert [item["state"] for item in states] == ["UNKNOWN", "CANDIDATES"]
    assert states[1]["previous"] == "UNKNOWN"
    assert states[1]["request_id"] == "req-1"


def test_entering_localized_cancels_navigation_once(assist):
    assist.on_state(_state("CANDIDATES", request_id="req-1"))
    assist.on_state(_state("LOCALIZED"))
    assist.on_state(_state("LOCALIZED"))
    assert assist.cancels == ["cancel"]


def test_candidates_carry_core_identity_and_emit_once_per_request(assist):
    assist.on_state(_state("CANDIDATES", request_id="req-1"))
    assist.on_candidates(_report("req-1"))
    assist.on_candidates(_report("req-1", stamp=7.0))   # 2 s re-report
    report = assist.candidates()
    assert report.robot_id == "rosy_07"
    assert report.stamp == 7.0
    events = assist.events.named("localization.candidates")
    assert events == [{"request_id": "req-1", "count": 2, "pickup": False}]


def test_a_robot_supplied_robot_id_is_overridden(assist):
    assist.on_state(_state("CANDIDATES", request_id="req-1"))
    assist.on_candidates(_report("req-1", robot_id="someone_else"))
    assert assist.candidates().robot_id == "rosy_07"


def test_candidates_are_withheld_outside_candidates_or_for_another_request(assist):
    assist.on_state(_state("CANDIDATES", request_id="req-2"))
    assist.on_candidates(_report("req-1"))
    assert assist.candidates() is None
    assist.on_state(_state("LOCALIZED"))
    assist.on_candidates(_report("req-3"))
    assert assist.candidates() is None


def _decision(request_id="req-1", **extra) -> LocalizationDecision:
    body = {"request_id": request_id, "candidate_index": 0, "source": "candidate",
            "cues": ["paint"], **extra}
    return LocalizationDecision.model_validate(body)


def test_a_decision_for_the_open_request_is_published_with_receipt_time(assist):
    assist.on_state(_state("CANDIDATES", request_id="req-1"))
    assist.decide(_decision())
    assert assist.published == [{
        "decision": _decision().model_dump(mode="json"), "received_s": 4242.5}]


def test_a_decision_for_another_request_is_stale(assist):
    assist.on_state(_state("CANDIDATES", request_id="req-2"))
    assert assist.is_stale(_decision("req-1"))
    assert not assist.is_stale(_decision("req-2"))


def test_a_candidate_decision_with_no_open_request_is_stale(assist):
    assist.on_state(_state("LOCALIZED"))
    assert assist.is_stale(_decision("req-1"))


def test_a_direct_pose_with_no_open_request_goes_to_the_robot(assist):
    assist.on_state(_state("SUSPECT"))
    human = assist.human_decision(1.0, 2.0, 0.5)
    assert human.source is DecisionSource.HUMAN
    assert not assist.is_stale(human)


def test_the_human_decision_answers_the_open_request(assist):
    assist.on_state(_state("CANDIDATES", request_id="req-9"))
    assert assist.human_decision(0.0, 0.0, 0.0).request_id == "req-9"


def test_without_a_transport_a_decision_cannot_be_sent(assist):
    assist.publish_decision = None
    with pytest.raises(RuntimeError):
        assist.decide(_decision())


def test_result_event_names_the_source_and_cues_core_sent(assist):
    assist.on_state(_state("CANDIDATES", request_id="req-1"))
    assist.decide(_decision(cues=["paint", "peers"]))
    assist.on_result(json.dumps({"request_id": "req-1", "accepted": True,
                                 "reason": None, "state": "CANDIDATES"}))
    assert assist.events.named("localization.result") == [{
        "request_id": "req-1", "accepted": True, "reason": None, "state": "CANDIDATES",
        "source": "candidate", "cues": ["paint", "peers"]}]
    assert assist.cancels == ["cancel"]


def test_a_rejected_result_does_not_cancel_navigation(assist):
    assist.on_result(json.dumps({"request_id": "req-1", "accepted": False,
                                 "reason": "no_asymmetric_cue", "state": "CANDIDATES"}))
    result = assist.events.named("localization.result")[0]
    assert result["source"] is None and result["cues"] == []
    assert assist.cancels == []


def test_a_malformed_result_is_ignored(assist):
    assist.on_result(json.dumps({"request_id": "req-1"}))
    assert assist.events.named("localization.result") == []


def test_suspect_is_published(assist):
    assist.suspect("fleet_monitor")
    assert assist.suspects == [{"reason": "fleet_monitor"}]


# --- gap 6: leaving LOCALIZED stops autonomy ------------------------------------


@pytest.fixture
def lost(assist):
    calls: list[str] = []
    assist.on_lost = lambda: calls.append("halt")
    assist.lost_calls = calls
    return assist


@pytest.mark.parametrize("after", ["SUSPECT", "CANDIDATES", "UNKNOWN"])
def test_leaving_localized_halts_once(lost, after):
    lost.on_state(_state("LOCALIZED"))
    lost.on_state(_state(after, request_id="req-1" if after == "CANDIDATES" else None))
    lost.on_state(_state(after, request_id="req-1" if after == "CANDIDATES" else None))
    assert lost.lost_calls == ["halt"]


def test_a_stale_state_topic_halts_with_its_reason(lost):
    lost.on_state(_state("LOCALIZED"))
    lost.mono.now += STATE_STALE_S + 0.1
    lost.tick(odom_owns_pose=False)
    assert lost.lost_calls == ["halt"]
    assert lost.events.named("localization.state")[-1]["reason"] == "state_stale"


# --- D-395 S1 finding 6: the stale window runs on the robot node's clock -----------


class _SlowSim:
    """Wall time and a sim clock that runs at `rtf` of it (Gazebo below real time)."""

    def __init__(self, rtf: float) -> None:
        self.wall, self.sim, self.rtf = 1000.0, 0.0, rtf

    def advance_wall(self, seconds: float) -> None:
        self.wall += seconds
        self.sim += seconds * self.rtf


def test_bind_clock_runs_the_stale_window_on_a_slow_sim_clock(lost):
    """RTF 0.1: the robot publishes every 0.5 sim s = 5 s wall; that is not stale."""
    sim = _SlowSim(rtf=0.1)
    lost.mono.now = sim.wall          # the wall clock the window used before the bind
    lost.bind_clock(lambda: sim.sim)
    lost.on_state(_state("LOCALIZED"))
    for _ in range(10):
        sim.advance_wall(5.0)
        lost.mono.now = sim.wall
        lost.tick(odom_owns_pose=False)
        assert lost.status().state is LocState.LOCALIZED
        lost.on_state(_state("LOCALIZED"))
    assert lost.lost_calls == []


def test_a_real_silence_is_still_stale_on_the_bound_clock(lost):
    sim = _SlowSim(rtf=0.1)
    lost.bind_clock(lambda: sim.sim)
    lost.on_state(_state("LOCALIZED"))
    sim.advance_wall(29.0)            # 2.9 sim s: still fresh
    lost.tick(odom_owns_pose=False)
    assert lost.status().state is LocState.LOCALIZED
    sim.advance_wall(2.0)             # 3.1 sim s of silence
    lost.tick(odom_owns_pose=False)
    assert lost.status().reason == "state_stale"
    assert lost.lost_calls == ["halt"]


def test_states_that_were_never_localized_do_not_halt(lost):
    lost.on_state(_state("UNKNOWN"))
    lost.on_state(_state("CANDIDATES", request_id="req-1"))
    lost.on_state(_state("SUSPECT"))
    assert lost.lost_calls == []


# --- review: result hardening, payload cap, autonomy predicate ---------------------


@pytest.mark.parametrize("body", [
    {"request_id": "bad id with spaces", "accepted": True, "reason": None, "state": "LOCALIZED"},
    {"request_id": "x" * 65, "accepted": True, "reason": None, "state": "LOCALIZED"},
    {"request_id": "req-1", "accepted": False, "reason": "r" * 65, "state": "CANDIDATES"},
    {"request_id": "req-1", "accepted": "yes", "reason": None, "state": "CANDIDATES"},
    {"request_id": "req-1", "accepted": True, "reason": None, "state": "LOST"},
])
def test_an_invalid_result_is_ignored(assist, body):
    assist.on_result(json.dumps(body))
    assert assist.events.named("localization.result") == []
    assert assist.cancels == []


def test_a_reason_of_64_characters_is_kept(assist):
    assist.on_result(json.dumps({"request_id": "req-1", "accepted": False,
                                 "reason": "r" * 64, "state": "CANDIDATES"}))
    assert assist.events.named("localization.result")[0]["reason"] == "r" * 64


def test_an_oversized_message_is_dropped(assist):
    big = json.dumps({"status": {"state": "LOCALIZED", "pose_frame": "map"},
                      "pad": "p" * (64 * 1024)})
    assist.on_state(big)
    assert assist.status() is None


def test_a_rejected_payload_is_not_logged(assist, caplog):
    secret = "SECRET-PAYLOAD-VALUE"
    with caplog.at_level("WARNING"):
        assist.on_result(json.dumps({"request_id": secret + " !", "accepted": True,
                                     "reason": None, "state": "LOCALIZED"}))
        assist.on_state(json.dumps({"status": {"state": secret, "pose_frame": "map"}}))
        assist.on_candidates(json.dumps({"request_id": secret + " !", "candidates": []}))
    assert caplog.records, "a rejection is still logged"
    assert secret not in caplog.text
    assert "ValidationError" in caplog.text


@pytest.mark.parametrize("state,frame,allowed", [
    ("LOCALIZED", "map", True), ("LOCALIZED", "odom", False),
    ("SUSPECT", "map", False), ("CANDIDATES", "map", False), ("UNKNOWN", "map", False),
])
def test_autonomy_needs_localized_in_the_map_frame(assist, state, frame, allowed):
    assist.on_state(_state(state, frame=frame, request_id="req-1" if state == "CANDIDATES" else None))
    assert assist.autonomy_allowed() is allowed


def test_a_pre_d395_robot_always_allows_autonomy(assist):
    assert assist.autonomy_allowed() is True


def test_core_substituting_odom_withdraws_autonomy(assist):
    assist.on_state(_state("LOCALIZED"))
    assist.tick(odom_owns_pose=True)
    assert assist.autonomy_allowed() is False
