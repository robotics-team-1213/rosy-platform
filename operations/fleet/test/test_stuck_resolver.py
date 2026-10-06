"""D-438 resolver core: chains, budgets, deadline, rules R1-R3, CORE response handling."""

import math

import pytest

from fleet.meet.place import pose_on, project
from site_map_fixture import painted_track
from fleet.server.stuck_resolver import Answer, Escalate, ResolverConfig, StuckResolver


def _row(robot_id="rosy_01", stuck=None, *, mode="CAMERA_LINE", pose=(0.0, 0.0, 0.0),
         online=True, estop=False, localization=None):
    state = {"robot_id": robot_id, "safety": {"estop": estop},
             "pose": None if pose is None else {"x": pose[0], "y": pose[1], "yaw": pose[2]},
             "line_follow": {"mode": mode, "state": "HOLD" if stuck else "TRACKING",
                             "stuck": stuck}}
    if localization is not None:
        state["localization"] = localization
    return {"robot_id": robot_id, "online": online, "state": state}


def _frame(pose_frame):
    return {"state": "LOCALIZED", "pose_frame": pose_frame, "confidence": 1.0}


def _stuck(stuck_id="stuck-1", cause="obstacle_ahead", *, local=True, attempts=0, max_attempts=2):
    return {"stuck_id": stuck_id, "cause": cause, "phase": "ASKING", "local_enabled": local,
            "attempts": attempts, "max_attempts": max_attempts}


def test_r2_backs_off_from_a_static_obstacle_once_per_stuck():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    first = r.step(0.0, [_row(stuck=_stuck())])
    assert first == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R2")]
    r.sent(first[0], 0.0)
    assert r.step(1.0, [_row(stuck=_stuck())]) == []          # one answer per stuck


def test_r1_waits_for_a_peer_in_the_front_band():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    me = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    peer = _row("rosy_02", None, pose=(0.20, 0.03, 3.14))
    assert r.step(0.0, [me, peer]) == [Answer("rosy_01", "stuck-1", "WAIT", "R1")]


def _east_pair():
    painted = painted_track()
    door = next(item for item in painted.doors if item.edge_id == "east")
    near = pose_on(painted, "east", 1.2, direction=1)
    # Close enough for the 0.30 m peer band, still on the paint (side stays under 0.15 m).
    far = pose_on(painted, "east", 1.45, direction=-1)
    return painted, door, near, far


def test_on_track_head_on_yields_and_an_off_track_peer_stays_on_r1():
    _painted, door, near, far = _east_pair()
    yielder = StuckResolver(ResolverConfig(), painted=painted_track)
    actions = yielder.step(0.0, [_row("near", _stuck(), pose=near), _row("far", None, pose=far)])
    assert len(actions) == 1 and isinstance(actions[0], Answer)
    assert actions[0].decision == "YIELD" and actions[0].rule == "meet"
    assert actions[0].yield_m == pytest.approx(abs(1.2 - door.s_m), abs=0.05)
    assert abs(actions[0].yield_turn_rad) == pytest.approx(math.pi, abs=0.2)
    holder = StuckResolver(ResolverConfig(), painted=painted_track)
    held = holder.step(0.0, [_row("far", _stuck(), pose=far), _row("near", None, pose=near)])
    assert held == [Answer("far", "stuck-1", "WAIT", "meet")]


def test_a_finished_segment_sends_the_sidestep_without_restarting_the_same_one():
    _painted, door, near, far = _east_pair()
    resolver = StuckResolver(ResolverConfig(), painted=painted_track)
    first = resolver.step(0.0, [_row("near", _stuck(), pose=near), _row("far", None, pose=far)])[0]
    resolver.sent(first, 0.0)
    yielded = _stuck()
    yielded["phase"] = "YIELDED"
    assert resolver.step(1.0, [_row("near", yielded, pose=near), _row("far", None, pose=far)]) == []
    door_pose = pose_on(painted_track(), "east", door.s_m, direction=-1)
    nxt = resolver.step(2.0, [_row("near", yielded, pose=door_pose), _row("far", None, pose=far)])
    assert len(nxt) == 1 and nxt[0].decision == "YIELD"
    assert 0.05 < nxt[0].yield_m < 0.6


def test_three_robots_on_one_two_way_edge_escalate():
    painted = painted_track()
    poses = [pose_on(painted, "east", s, direction=1) for s in (1.0, 1.08, 1.16)]
    action = StuckResolver(ResolverConfig(), painted=painted_track).step(0.0, [
        _row("a", _stuck(), pose=poses[0]),
        _row("b", None, pose=poses[1]),
        _row("c", None, pose=poses[2]),
    ])[0]
    assert isinstance(action, Escalate) and action.reason == "meet"


def test_r1_ignores_a_peer_behind_or_beside_and_unknown_poses():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    me = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    behind = _row("rosy_02", None, pose=(-0.20, 0.0, 0.0))
    beside = _row("rosy_03", None, pose=(0.10, 0.40, 0.0))
    assert r.step(0.0, [me, behind, beside])[0].rule == "R2"
    r2 = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r2.step(0.0, [_row("rosy_01", _stuck(), pose=None),
                         _row("rosy_02", None, pose=(0.2, 0.0, 0.0))])[0].rule == "R2"


def test_r3_backs_off_on_lane_lost():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(0.0, [_row(stuck=_stuck(cause="lane_lost"))]) == [
        Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R3")]


def test_no_back_off_without_local_recovery_escalates():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(0.0, [_row(stuck=_stuck(local=False))]) == [
        Escalate("rosy_01", "stuck-1", "no_rule")]
    assert r.step(1.0, [_row(stuck=_stuck(local=False))]) == []      # escalate once


def test_attempts_exhausted_escalates():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(0.0, [_row(stuck=_stuck(attempts=2, max_attempts=2))]) == [
        Escalate("rosy_01", "stuck-1", "no_rule")]


def test_chain_budget_counts_restucks_of_any_close_kind():
    r = StuckResolver(ResolverConfig(rule_budget=2, restuck_s=30.0))
    for i, t in ((1, 0.0), (2, 10.0)):
        a = r.step(t, [_row(stuck=_stuck(f"stuck-{i}"))])[0]
        r.sent(a, t)
        r.step(t + 1.0, [_row(stuck=None)])                          # closed (any reason)
    assert r.step(20.0, [_row(stuck=_stuck("stuck-3"))]) == [
        Escalate("rosy_01", "stuck-3", "rule_budget")]


def test_chain_ends_after_restuck_window_or_mode_change():
    r = StuckResolver(ResolverConfig(rule_budget=1, restuck_s=30.0))
    r.sent(r.step(0.0, [_row(stuck=_stuck("stuck-1"))])[0], 0.0)
    r.step(1.0, [_row(stuck=None)])
    assert r.step(40.0, [_row(stuck=_stuck("stuck-2"))])[0].stuck_id == "stuck-2"  # new chain
    r.sent(Answer("rosy_01", "stuck-2", "BACK_AND_RETRY", "R2"), 40.0)
    r.step(41.0, [_row(stuck=None, mode="OFF")])
    assert isinstance(r.step(42.0, [_row(stuck=_stuck("stuck-3"))])[0], Answer)


def test_restuck_after_resolver_resume_goes_to_human():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    r.sent(Answer("rosy_01", "stuck-1", "RESUME", "R1"), 0.0)
    r.step(0.0, [_row(stuck=_stuck("stuck-1"))])
    r.step(1.0, [_row(stuck=None)])
    assert r.step(5.0, [_row(stuck=_stuck("stuck-2"))]) == [
        Escalate("rosy_01", "stuck-2", "restuck_after_resume")]


def test_deadline_escalates():
    r = StuckResolver(ResolverConfig(escalate_after_s=60.0))
    r.sent(r.step(0.0, [_row(stuck=_stuck())])[0], 0.0)
    assert r.step(61.0, [_row(stuck=_stuck())]) == [Escalate("rosy_01", "stuck-1", "deadline")]


def test_refused_retires_the_rule_and_tries_the_next():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    me = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    peer = _row("rosy_02", None, pose=(0.20, 0.0, 3.14))
    a = r.step(0.0, [me, peer])[0]
    assert a.rule == "R1"
    r.sent(a, 0.0)
    r.result(a, code="STUCK_DECISION_REFUSED")
    b = r.step(1.0, [me, peer])[0]
    assert (b.decision, b.rule) == ("BACK_AND_RETRY", "R2")


def test_mismatch_forgets_and_other_codes_escalate():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    a = r.step(0.0, [_row(stuck=_stuck())])[0]
    r.sent(a, 0.0)
    r.result(a, code="STUCK_ID_MISMATCH")
    assert r.step(1.0, [_row(stuck=_stuck())]) == []                 # same id: still answered
    r2 = StuckResolver(ResolverConfig(), painted=painted_track)
    a2 = r2.step(0.0, [_row(stuck=_stuck())])[0]
    r2.sent(a2, 0.0)
    assert r2.result(a2, code="CALIBRATION_ACTIVE") == Escalate("rosy_01", "stuck-1",
                                                               "core:CALIBRATION_ACTIVE")


def test_transport_failure_retries_once_then_escalates():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    a = r.step(0.0, [_row(stuck=_stuck())])[0]
    r.sent(a, 0.0)
    assert r.result(a, code="ROBOT_UNREACHABLE") is None
    again = r.step(1.0, [_row(stuck=_stuck())])
    assert again == [a]
    r.sent(a, 1.0)
    assert r.result(a, code="ROBOT_UNREACHABLE") == Escalate("rosy_01", "stuck-1",
                                                            "core:ROBOT_UNREACHABLE")


def test_human_claim_silences_the_resolver():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    r.claim("rosy_01", "stuck-1")
    assert r.step(0.0, [_row(stuck=_stuck())]) == []


def test_offline_and_estop_robots_are_left_alone():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(0.0, [_row(stuck=_stuck(), online=False)]) == []
    assert r.step(0.0, [_row(stuck=_stuck(), estop=True)]) == [
        Escalate("rosy_01", "stuck-1", "estop")]


def test_row_without_mode_keeps_the_chain():
    r = StuckResolver(ResolverConfig(escalate_after_s=60.0))
    me = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    peer = _row("rosy_02", None, pose=(0.20, 0.0, 3.14))
    a = r.step(0.0, [me, peer])[0]
    r.sent(a, 0.0)
    r.result(a, code="STUCK_DECISION_REFUSED")
    partial = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    del partial["state"]["line_follow"]["mode"]
    r.step(1.0, [partial, peer])
    assert r.step(2.0, [me, peer])[0].rule == "R2"                    # R1 stays retired
    assert r.step(61.0, [me, peer]) == [Escalate("rosy_01", "stuck-1", "deadline")]


def test_restuck_after_resume_without_a_closed_poll():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    r.sent(Answer("rosy_01", "stuck-1", "RESUME", "R1"), 0.0)
    assert r.step(1.0, [_row(stuck=_stuck("stuck-2"))]) == [
        Escalate("rosy_01", "stuck-2", "restuck_after_resume")]


def test_transport_resend_counts_once_against_the_budget():
    r = StuckResolver(ResolverConfig(rule_budget=2))
    a = r.step(0.0, [_row(stuck=_stuck())])[0]
    r.sent(a, 0.0)
    r.result(a, code="ROBOT_UNREACHABLE")
    r.sent(a, 1.0)
    r.result(a, code=None)
    r.step(2.0, [_row(stuck=None)])
    assert isinstance(r.step(3.0, [_row(stuck=_stuck("stuck-2"))])[0], Answer)


def test_active_calibration_escalates():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    row = _row(stuck=_stuck())
    row["state"]["activity"] = {"kind": "CALIBRATING"}
    assert r.step(0.0, [row]) == [Escalate("rosy_01", "stuck-1", "calibration")]


def test_r1_reach_covers_the_peer_body():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    me = _row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))
    peer = _row("rosy_02", None, pose=(0.35, 0.0, 3.14))
    assert r.step(0.0, [me, peer]) == [Answer("rosy_01", "stuck-1", "WAIT", "R1")]


def test_late_reply_from_an_older_chain_is_ignored():
    r = StuckResolver(ResolverConfig(restuck_s=30.0))
    old = r.step(0.0, [_row(stuck=_stuck("stuck-1"))])[0]
    r.sent(old, 0.0)
    r.step(1.0, [_row(stuck=None)])
    r.step(40.0, [_row(stuck=_stuck("stuck-2"))])                    # new chain
    assert r.result(old, code="CALIBRATION_ACTIVE") is None


def test_claims_are_pruned_when_the_chain_ends():
    r = StuckResolver(ResolverConfig(restuck_s=30.0))
    r.claim("rosy_01", "stuck-1")
    r.step(0.0, [_row(stuck=_stuck("stuck-1"))])
    r.step(1.0, [_row(stuck=None)])
    r.step(40.0, [_row(stuck=None)])
    assert r._claims == set()


def test_claim_survives_a_mode_change_while_the_stuck_is_open():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    r.claim("rosy_01", "stuck-1")
    r.step(0.0, [_row(stuck=_stuck("stuck-1"))])
    assert r.step(1.0, [_row(stuck=_stuck("stuck-1"), mode="OFF")]) == []


def test_budget_never_blocks_the_one_transport_resend():
    r = StuckResolver(ResolverConfig(rule_budget=2))
    a = r.step(0.0, [_row(stuck=_stuck("stuck-1"))])[0]
    r.sent(a, 0.0)
    r.result(a, code=None)
    r.step(1.0, [_row(stuck=None)])
    b = r.step(2.0, [_row(stuck=_stuck("stuck-2"))])[0]
    r.sent(b, 2.0)
    assert r.result(b, code="ROBOT_UNREACHABLE") is None
    assert r.step(3.0, [_row(stuck=_stuck("stuck-2"))]) == [b]           # resend, not rule_budget


def test_robots_that_leave_the_roster_lose_their_chain_and_claims():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    r.claim("rosy_02", "stuck-9")
    r.step(0.0, [_row(stuck=_stuck()), _row("rosy_02", _stuck("stuck-9"))])
    r.step(1.0, [_row(stuck=_stuck())])
    assert set(r._chains) == {"rosy_01"} and r._claims == set()


def _yielded():
    stuck = _stuck()
    stuck["phase"] = "YIELDED"
    return stuck


def _started_east_yield():
    _painted, door, near, far = _east_pair()
    resolver = StuckResolver(ResolverConfig(), painted=painted_track)
    first = resolver.step(0.0, [_row("near", _stuck(), pose=near), _row("far", None, pose=far)])[0]
    resolver.sent(first, 0.0)
    return resolver, door, far


def test_localized_map_pose_still_yields_and_odom_frame_does_not():
    _painted, _door, near, far = _east_pair()
    mapped = StuckResolver(ResolverConfig(), painted=painted_track).step(0.0, [
        _row("near", _stuck(), pose=near, localization=_frame("map")),
        _row("far", None, pose=far, localization=_frame("map")),
    ])
    assert mapped[0].decision == "YIELD" and mapped[0].rule == "meet"
    odom = StuckResolver(ResolverConfig(), painted=painted_track).step(0.0, [
        _row("near", _stuck(), pose=near, localization=_frame("odom")),
        _row("far", None, pose=far, localization=_frame("odom")),
    ])
    assert odom == [Answer("near", "stuck-1", "WAIT", "R1")]


def test_a_gap_beside_the_line_returns_to_the_paint_not_across_the_floor():
    resolver, _door, far = _started_east_yield()
    painted = painted_track()
    x, y, yaw = pose_on(painted, "east", 1.2, direction=1)
    gap = (x + 0.10 * math.cos(yaw + math.pi / 2), y + 0.10 * math.sin(yaw + math.pi / 2), yaw)
    assert project(painted, gap[0], gap[1], gap[2]) is None
    move = resolver.step(1.0, [_row("near", _yielded(), pose=gap), _row("far", None, pose=far)])
    assert len(move) == 1 and move[0].decision == "YIELD"
    assert move[0].yield_m == pytest.approx(0.10, abs=0.03)


def test_the_spur_gap_aims_at_the_hold_unless_the_pose_is_odom():
    resolver, door, far = _started_east_yield()
    painted = painted_track()
    room = next(item for item in painted.rooms if item.id == "east_room")
    dx, dy, _tangent = painted.line("east").point_at(door.s_m)
    mid = ((dx + room.hold_xy[0]) / 2, (dy + room.hold_xy[1]) / 2, 0.0)
    assert project(painted, mid[0], mid[1], mid[2]) is None
    move = resolver.step(1.0, [_row("near", _yielded(), pose=mid), _row("far", None, pose=far)])
    assert len(move) == 1 and move[0].decision == "YIELD"
    assert move[0].yield_m == pytest.approx(
        math.hypot(room.hold_xy[0] - mid[0], room.hold_xy[1] - mid[1]), abs=0.05)
    assert resolver.step(2.0, [
        _row("near", _yielded(), pose=mid, localization=_frame("odom")),
        _row("far", None, pose=far),
    ]) == []


def test_in_room_returns_only_after_the_passer_clears_the_door():
    resolver, door, far = _started_east_yield()
    painted = painted_track()
    room = next(item for item in painted.rooms if item.id == "east_room")
    hold = (room.hold_xy[0], room.hold_xy[1], 0.0)
    yielded = _yielded()
    assert resolver.step(1.0, [_row("near", yielded, pose=hold), _row("far", None, pose=far)]) == []
    past = pose_on(painted, "east", door.s_m - 0.70, direction=-1)
    blocked = resolver.step(2.0, [
        _row("near", yielded, pose=hold),
        _row("far", None, pose=past, localization=_frame("odom")),
    ])
    assert blocked == []
    back = resolver.step(3.0, [_row("near", yielded, pose=hold), _row("far", None, pose=past)])
    assert len(back) == 1 and back[0].decision == "YIELD"
    dx, dy, _tangent = painted.line("east").point_at(door.s_m)
    assert back[0].yield_m == pytest.approx(math.hypot(hold[0] - dx, hold[1] - dy), abs=0.05)
    resolver.sent(back[0], 3.0)
    assert resolver.step(4.0, [_row("near", yielded, pose=hold), _row("far", None, pose=past)]) == []
    facing = pose_on(painted, "east", door.s_m, direction=-1)
    turn = resolver.step(5.0, [_row("near", yielded, pose=facing), _row("far", None, pose=past)])
    assert len(turn) == 1 and turn[0].decision == "YIELD"
    assert turn[0].yield_m == pytest.approx(0.15, abs=0.04)
    resolver.sent(turn[0], 5.0)
    home = pose_on(painted, "east", door.s_m + 0.15, direction=1)
    done = resolver.step(6.0, [_row("near", yielded, pose=home), _row("far", None, pose=past)])
    assert done == [Answer("near", "stuck-1", "RESUME", "meet")]
    resolver.sent(done[0], 6.0)
    resolver.result(done[0], code="STUCK_DECISION_REFUSED")
    assert resolver.step(7.0, [_row("near", yielded, pose=home), _row("far", None, pose=past)]) == done


@pytest.mark.parametrize("unavailable", ["offline", "missing_state", "unknown", "lapsed"])
def test_rejoin_holds_when_a_roster_peer_has_no_current_map_pose(unavailable):
    from fleet.localization.trust import badge

    resolver, door, _far = _started_east_yield()
    painted = painted_track()
    room = next(item for item in painted.rooms if item.id == "east_room")
    me = _row("near", _yielded(), pose=(*room.hold_xy, 0.0))
    past = pose_on(painted, "east", door.s_m - 0.70, direction=-1)
    peer = _row("far", None, pose=past)
    if unavailable == "offline":
        peer["online"], peer["state"] = False, None
    elif unavailable == "missing_state":
        peer["state"] = None
    elif unavailable == "unknown":
        peer["state"]["localization"] = {"state": "UNKNOWN", "pose_frame": "odom"}
    peer["localization"] = badge(peer["state"], lapsed=unavailable == "lapsed")
    assert resolver.step(1.0, [me, peer]) == []
    # A new, verified map snapshot opens the same retained plan; no pose/draft reset.
    peer = _row("far", None, pose=past, localization=_frame("map"))
    peer["localization"] = badge(peer["state"])
    move = resolver.step(2.0, [me, peer])
    assert len(move) == 1 and move[0].decision == "YIELD"


@pytest.mark.parametrize("where", ["room", "door"])
def test_rejoin_never_moves_or_resumes_from_a_lapsed_own_pose(where):
    from fleet.localization.trust import badge

    resolver, door, _far = _started_east_yield()
    painted = painted_track()
    room = next(item for item in painted.rooms if item.id == "east_room")
    hold = (*room.hold_xy, 0.0)
    peer = _row("far", None, pose=pose_on(painted, "east", door.s_m - 0.70, direction=-1))
    # Entering the room is observed while trust is still valid.
    assert resolver.step(1.0, [_row("near", _yielded(), pose=hold),
                               _row("far", None, pose=_far)]) == []
    pose = hold if where == "room" else pose_on(painted, "east", door.s_m + 0.15, direction=1)
    me = _row("near", _yielded(), pose=pose)
    me["localization"] = badge(me["state"], lapsed=True)
    assert me["localization"]["trusted"] is False
    assert resolver.step(2.0, [me, peer]) == []
    me["localization"] = badge(me["state"])
    action = resolver.step(3.0, [me, peer])
    assert len(action) == 1 and action[0].decision == ("YIELD" if where == "room" else "RESUME")
