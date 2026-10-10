"""D-610 P1·P2·P5: AI-first robots, evidence, gates as flags, caps, closed loop, episodes, stalled/pose_lost."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from site_map_fixture import painted_track
from test_stuck_resolver import _row, _stuck
from fleet.stuck.ai_first import AiFirst, problem_key
from fleet.stuck.ai_routes import rosy_cam_lease
from fleet.stuck.closed_loop import reopen
from fleet.stuck.episodes import ProblemLog
from fleet.stuck.outcome import Outcomes
from fleet.stuck.problems import ProblemWatch
from fleet.stuck.resolver import Answer, Escalate, ResolverConfig, StuckResolver
from core_common.protocol.vision_preview import VisionLeaseSigner

WALL = 1_760_000_000.0
PROFILE = "qwen3-vl:8b-instruct@abc:d610-v1"


def test_ai_camera_lease_uses_only_fresh_same_map_sighting_including_pose_loss():
    signer = VisionLeaseSigner("x" * 32)
    pose = SimpleNamespace(state="LOCALIZED", x=0.2, y=0.3, map_id="track")
    sighting = {"robot_id": "rosy_01", "source_id": "ceiling", "map_id": "track", "stale": False,
                "x": 0.2, "y": 0.3, "calibration_revision": "rev1"}
    sightings = SimpleNamespace(snapshot=lambda: {"sightings": [sighting]})
    poses = SimpleNamespace(arbitrated_pose=lambda _rid: pose, active_map_id=lambda: "track")
    view = rosy_cam_lease("rosy_01", sightings, poses, signer, ("ceiling",))
    assert view["frame_path"] == "/api/vision/sources/ceiling/frame"
    lease = signer.verify(view["lease"], source_id="ceiling")
    assert lease["crop_map"] == [0.2, 0.3, 1.0] and lease["exp"] - lease["iat"] == 10
    for bad in ({**sighting, "stale": True}, {**sighting, "map_id": "other"}):
        sightings.snapshot = lambda: {"sightings": [bad]}
        assert rosy_cam_lease("rosy_01", sightings, poses, signer, ("ceiling",)) is None
    pose.state = "LOST"
    sightings.snapshot = lambda: {"sightings": [sighting]}
    assert rosy_cam_lease("rosy_01", sightings, poses, signer, ("ceiling",)) is not None


def _first(robots=("rosy_01",), keep=None):
    first = AiFirst(robots, keep)
    first.wall = lambda: WALL
    first.profiles = lambda: [PROFILE]
    return first


def _resolver(first):
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    r.ai_first = first
    return r


def _vlm(decision="BACK_AND_RETRY", stuck_id="stuck-1", reason="clear_behind", *, age=(0.5, 1.0), views=None):
    views = views if views is not None else {
        "rosy_cam": {"frame_id": "cam:1", "captured_at": WALL - age[0]},
        "front": {"frame_id": "front:1", "captured_at": WALL - age[1]}}
    return {"robot_id": "rosy_01", "stuck_id": stuck_id, "decision": decision, "reason": reason,
            "confidence": 0.8, "source": f"vlm:{PROFILE}", "observed_at": WALL, "ttl_s": 6.0,
            "evidence": {"views": views, "map_pose": {"state": "LOCALIZED", "age_s": 0.2}}}


def _with(row, proposal=None, **extra):
    if proposal is not None:
        row["ai_proposal"] = proposal
    row.update(extra)
    return row


def test_vlm_answer_with_both_fresh_views_is_sent_and_audited_with_the_wall_clock():
    r = _resolver(_first())
    assert r.step(0.0, [_with(_row(stuck=_stuck()), _vlm())]) == [
        Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "ai")]
    verdict = r.ai_verdicts[-1]
    assert verdict["verdict"] == "forwarded" and verdict["judged_at"] > 1e9     # D-610 10


@pytest.mark.parametrize("views, verdict", [
    ({"front": {"frame_id": "f", "captured_at": WALL}}, "evidence_missing:rosy_cam"),
    ({"rosy_cam": {"frame_id": "c", "captured_at": WALL}}, "evidence_missing:front"),
    ({"rosy_cam": {"frame_id": "c", "captured_at": WALL - 2.5}, "front": {"frame_id": "f", "captured_at": WALL}},
     "evidence_stale:rosy_cam"),
    ({"rosy_cam": {"frame_id": "c", "captured_at": WALL}, "front": {"frame_id": "f", "captured_at": WALL - 3.5}},
     "evidence_stale:front"),
])
def test_vlm_answer_without_both_fresh_views_falls_back_to_the_rules(views, verdict):
    r = _resolver(_first())
    actions = r.step(0.0, [_with(_row(stuck=_stuck()), _vlm(views=views))])
    assert r.ai_verdicts[-1]["verdict"] == verdict
    assert actions == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R2")]


def test_unknown_profile_is_refused():
    first = _first()
    first.profiles = lambda: ["other@x:d610-v1"]
    r = _resolver(first)
    r.step(0.0, [_with(_row(stuck=_stuck()), _vlm())])
    assert r.ai_verdicts[-1]["verdict"] == "profile_unknown"


def test_robot_outside_the_list_and_the_switch_off_keep_the_d577_gates():
    lost = _stuck(cause="lane_lost")
    for first in (_first(robots=()), _first()):
        if first.robots:
            first.enabled = False                        # the console switch (D-610 3)
        r = _resolver(first)
        r.step(10.0, [_with(_row(stuck=lost), _vlm("RESUME"))])
        assert r.ai_verdicts[-1]["verdict"] == "word_not_allowed"


def test_kept_gate_is_the_old_behaviour_and_a_dropped_gate_leaves_a_floor_note():
    lost = _stuck(cause="lane_lost")
    kept = _resolver(_first(keep={"rosy_01": ["ai_words"]}))
    kept.step(10.0, [_with(_row(stuck=lost), _vlm("RESUME"))])
    assert kept.ai_verdicts[-1]["verdict"] == "word_not_allowed"
    dropped = _resolver(_first())
    assert dropped.step(10.0, [_with(_row(stuck=lost), _vlm("RESUME"))]) == [
        Answer("rosy_01", "stuck-1", "RESUME", "ai")]
    assert "floor_would_hold:ai_words:word_not_allowed" in dropped.ai_verdicts[-1]["floor"]


def test_trip_robot_gets_wait_only_by_default_and_never_a_moving_ai_answer():
    r = _resolver(_first())
    r.step(0.0, [_with(_row(stuck=_stuck()), _vlm(), trip=True)])
    assert r.ai_verdicts[-1]["verdict"] == "trip"
    off = _resolver(_first(keep={"rosy_01": []}))       # trip_wait_only off: still no move with our credential
    off.step(0.0, [_with(_row(stuck=_stuck()), _vlm(), trip=True)])
    assert off.ai_verdicts[-1]["verdict"] == "trip"


@pytest.mark.parametrize("crosswalk, expected", [
    ({"state": "inside", "source": "camera"}, Answer("rosy_01", "stuck-1", "WAIT", "ai", escalate="crosswalk_human")),
    ({"state": "crossing"}, Answer("rosy_01", "stuck-1", "WAIT", "ai", escalate="crosswalk_human")),
    ({"state": "waiting"}, Answer("rosy_01", "stuck-1", "RESUME", "ai")),
])
def test_crosswalk_resume_only_when_cores_gate_object_will_scan(crosswalk, expected):
    row = _row(stuck=_stuck())
    row["state"]["line_follow"]["crosswalk"] = crosswalk
    r = _resolver(_first())
    assert r.step(0.0, [_with(row, _vlm("RESUME"))]) == [expected]


def test_human_class_key_goes_to_a_person():
    first = _first()
    row = _row(stuck=_stuck())
    key = problem_key(row, "stuck", "obstacle_ahead", False)
    assert key == "stuck:obstacle_ahead:lane"
    first.human_classes = lambda: frozenset({key})
    assert _resolver(first).step(0.0, [_with(row, _vlm())]) == [
        Answer("rosy_01", "stuck-1", "WAIT", "ai", escalate=f"human_class:{key}")]


def test_estop_robot_gets_no_answer():
    r = _resolver(_first())
    assert r.step(0.0, [_with(_row(stuck=_stuck(), estop=True), _vlm())]) == [
        Escalate("rosy_01", "stuck-1", "estop")]


def test_caps_problem_hour_and_oscillation():
    first = _first()
    for _ in range(3):
        first.sent("rosy_01", 0.0, "WAIT", 0.0)
    assert first.limit("rosy_01", 0.0, "WAIT", 1.0) == "ai_exhausted"
    for i in range(6):
        first.sent("rosy_01", float(i + 1), "BACK_AND_RETRY", float(i))
    assert first.limit("rosy_01", 99.0, "BACK_AND_RETRY", 10.0) == "ai_hourly_cap"
    assert first.limit("rosy_01", 99.0, "WAIT", 10.0) is None
    assert first.limit("rosy_01", 99.0, "BACK_AND_RETRY", 3700.0) is None
    swing = _first()
    swing.sent("rosy_01", 5.0, "BACK_AND_RETRY", 0.0)
    swing.sent("rosy_01", 5.0, "RESUME", 1.0)
    assert swing.limit("rosy_01", 5.0, "BACK_AND_RETRY", 2.0) == "ai_oscillation"


def test_core_refusal_is_never_resent_and_a_reopened_stuck_is_asked_again():
    first = _first()
    r = _resolver(first)
    row = _with(_row(stuck=_stuck()), _vlm())
    [answer] = r.step(0.0, [row])
    r.sent(answer, 0.0)
    first.refused("rosy_01", 0.0, "BACK_AND_RETRY")
    reopen(r, "rosy_01", "stuck-1", 21.0)
    r.step(21.0, [_with(_row(stuck=_stuck()), _vlm(reason="again"))])
    assert r.ai_verdicts[-1]["verdict"] == "core_refused_before"


def test_outcomes_resolved_unresolved_refused_superseded():
    loop = Outcomes()
    moved = _row(pose=(0.15, 0.0, 0.0))
    assert loop.answered("stuck", "rosy_01", "s1", "BACK_AND_RETRY", None, 0.0, _row()) is None
    assert loop.check(10.0, [moved]) == []
    assert loop.check(20.0, [moved])[0]["outcome"] == "resolved"
    loop.answered("stuck", "rosy_01", "s2", "RESUME", None, 0.0, _row())
    again = loop.check(5.0, [_row(stuck=_stuck("s3"))])[0]
    assert again["outcome"] == "unresolved" and again["near_miss"] is True       # obstacle_ahead after a move
    loop.answered("stuck", "rosy_01", "s4", "WAIT", None, 0.0, _row())
    assert loop.check(20.0, [_row(stuck=_stuck("s4"))])[0]["outcome"] == "unresolved"
    assert loop.answered("stuck", "rosy_01", "s5", "RESUME", "STUCK_DECISION_REFUSED", 0.0)["outcome"] == "refused"
    loop.answered("stuck", "rosy_01", "s6", "WAIT", None, 0.0, _row())
    assert loop.supersede("rosy_01", "s6")["outcome"] == "superseded"
    loop.answered("pose_lost", "rosy_01", "p1", "IDENTIFY", None, 0.0)
    assert loop.check(5.0, [_row()])[0]["outcome"] == "resolved"


def test_trend_proposes_a_class_and_only_a_person_changes_the_table():
    log = ProblemLog(wall=lambda: WALL)
    for i in range(5):
        log.opened(robot_id="rosy_01", problem_id=f"s{i}", kind="stuck", type_key="stuck:lane_lost:lane",
                   context={}, decision="BACK_AND_RETRY", tier="ai")
        log.outcome({"robot_id": "rosy_01", "problem_id": f"s{i}", "outcome": "unresolved" if i < 3 else "resolved"})
    log.opened(robot_id="rosy_01", problem_id="x", kind="stuck", type_key="stuck:obstacle_ahead:crosswalk",
               context={}, decision="RESUME", tier="ai")
    log.outcome({"robot_id": "rosy_01", "problem_id": "x", "outcome": "superseded", "near_miss": True})
    trend = {row["type_key"]: row for row in log.trend()}
    assert trend["stuck:lane_lost:lane"]["candidate"] and trend["stuck:lane_lost:lane"]["unresolved"] == 0.6
    assert trend["stuck:obstacle_ahead:crosswalk"]["candidate"]                    # one near miss is enough
    assert log.active() == frozenset()                                             # never by itself
    log.change("stuck:lane_lost:lane", "add", "kim", "keeps failing", trend["stuck:lane_lost:lane"])
    log.change("stuck:obstacle_ahead:crosswalk", "reject", "kim", "seen, fine", None)
    assert log.active() == {"stuck:lane_lost:lane"}
    assert not any(row["candidate"] for row in log.trend())
    log.change("stuck:lane_lost:lane", "remove", "admin", "fixed", None)
    assert log.active() == frozenset()


class _Board:
    def __init__(self, proposals):
        self.proposals, self.verdicts, self.log = proposals, [], None

    def problem_proposal(self, problem_id):
        return self.proposals.get(problem_id)


class _Loop:
    def __init__(self, first, proposals, robot):
        self._resolver = _resolver(first)
        self.ai_board, self.outcomes, self.episodes = _Board(proposals), Outcomes(), ProblemLog(wall=lambda: WALL)
        self._robot = robot

    def _clients(self):
        return {"rosy_01": self._robot}


def test_stalled_line_off_and_pose_lost_identify_are_sent_and_watched():
    from fakes import FakeRobot

    robot = FakeRobot("rosy_01")
    first = _first()
    stalled = {**_vlm("LINE_OFF", stuck_id=f"stalled:rosy_01:{int(WALL)}", reason="dark_hold")}
    lost = {**_vlm("IDENTIFY", stuck_id=f"pose_lost:rosy_01:{int(WALL)}", reason="no_marker")}
    loop = _Loop(first, {stalled["stuck_id"]: stalled, lost["stuck_id"]: lost}, robot)
    watch = ProblemWatch()
    row = _row()
    row["state"]["line_follow"].update(state="HOLD", linear=0.0, angular=0.0)
    asyncio.run(watch.run(loop, 0.0, [row]))
    assert watch.open == {}
    asyncio.run(watch.run(loop, 20.0, [row]))
    assert ("line_follow_mode", "OFF") in robot.calls
    row["map_pose"] = {"state": "UNKNOWN"}
    asyncio.run(watch.run(loop, 21.0, [row]))
    assert ("identify_lamp", None) in robot.calls
    assert {v["verdict"] for v in loop.ai_board.verdicts} == {"forwarded"}
    assert {e["kind"] for e in loop.episodes.episodes()} == {"stalled", "pose_lost"}


def test_stalled_on_a_trip_robot_is_wait_only():
    from fakes import FakeRobot

    robot = FakeRobot("rosy_01")
    stalled = _vlm("STOP", stuck_id=f"stalled:rosy_01:{int(WALL)}", reason="dark_hold")
    loop = _Loop(_first(), {stalled["stuck_id"]: stalled}, robot)
    watch, row = ProblemWatch(), _row()
    row["state"]["line_follow"].update(state="HOLD", linear=0.0, angular=0.0)
    row["trip"] = True
    asyncio.run(watch.run(loop, 0.0, [row]))
    asyncio.run(watch.run(loop, 20.0, [row]))
    assert loop.ai_board.verdicts[-1]["verdict"] == "trip" and robot.calls == []


def test_judged_at_is_wall_clock_on_the_d577_path_too():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    proposal = {"robot_id": "rosy_01", "stuck_id": "stuck-1", "decision": "BACK_AND_RETRY", "reason": "x",
                "confidence": 0.6, "evidence": {}, "source": "analyzer:stuck_scene@1", "observed_at": 0.0,
                "ttl_s": 6.0}
    r.step(0.0, [_with(_row(stuck=_stuck()), proposal)])
    assert abs(r.ai_verdicts[-1]["judged_at"] - time.time()) < 60
