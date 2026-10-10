"""D-438 resolver core: chains, budgets, deadline, rules R1-R3, CORE response handling."""

import math

import pytest

from fleet.meet.place import pose_on, project
from site_map_fixture import painted_track, painted_without_crosswalks
from fleet.server.stuck_resolver import Answer, Escalate, ResolverConfig, StuckResolver


def _row(robot_id="rosy_01", stuck=None, *, mode="CAMERA_LINE", pose=(0.0, 0.0, 0.0),
         online=True, estop=False, localization=None):
    state = {"robot_id": robot_id, "safety": {"estop": estop},
             "pose": None if pose is None else {"x": pose[0], "y": pose[1], "yaw": pose[2]},
             "line_follow": {"mode": mode, "state": "HOLD" if stuck else "TRACKING",
                             "stuck": stuck, "crosswalk": None}}
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
    r = StuckResolver(ResolverConfig(), painted=painted_without_crosswalks)
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


@pytest.mark.parametrize("peer_pose", [(0.20, 0.03, 3.14), (0.80, 0.0, 3.14), (-0.20, 0.0, 0.0),
                                       (0.20, 0.30, 3.14), None])
def test_the_shared_peer_ahead_matches_the_resolvers_r1(peer_pose):
    from fleet.server.stuck_resolver import peer_ahead

    me = _row("rosy_01", _stuck(local=False), pose=(0.0, 0.0, 0.0))
    peer = _row("rosy_02", None, pose=peer_pose)
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    fired = r.step(0.0, [me, peer]) == [Answer("rosy_01", "stuck-1", "WAIT", "R1")]
    assert peer_ahead(me, [me, peer], ResolverConfig()) is fired
    assert peer_ahead(_row("rosy_01", _stuck(), pose=None), [me, peer], ResolverConfig()) is None


def _trip(row):
    return {**row, "trip": True}


def test_trip_robot_gets_only_the_stopping_r1_wait():
    """D-517 5 (M4): a trip robot is answered, but only WAIT; a moving rule goes to a human (D-494 14)."""
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    me = _trip(_row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0)))
    peer = _row("rosy_02", None, pose=(0.20, 0.03, 3.14))
    assert r.step(0.0, [me, peer]) == [Answer("rosy_01", "stuck-1", "WAIT", "R1")]
    alone = StuckResolver(ResolverConfig(), painted=painted_track)
    assert alone.step(0.0, [_trip(_row(stuck=_stuck()))]) == [Escalate("rosy_01", "stuck-1", "no_rule")]
    lost = StuckResolver(ResolverConfig(), painted=painted_track)
    assert lost.step(0.0, [_trip(_row(stuck=_stuck(cause="lane_lost")))]) == [
        Escalate("rosy_01", "stuck-1", "no_rule")]


def test_trip_robot_head_on_waits_instead_of_yielding():
    _painted, _door, near, far = _east_pair()
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    actions = r.step(0.0, [_trip(_row("near", _stuck(), pose=near)), _row("far", None, pose=far)])
    assert actions == [Answer("near", "stuck-1", "WAIT", "R1")]


def test_trip_robot_refused_wait_goes_to_a_human_not_a_back_off():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    rows = [_trip(_row("rosy_01", _stuck(), pose=(0.0, 0.0, 0.0))), _row("rosy_02", None, pose=(0.20, 0.0, 3.14))]
    wait = r.step(0.0, rows)[0]
    r.sent(wait, 0.0)
    assert r.result(wait, code="STUCK_DECISION_REFUSED") is None
    assert r.step(1.0, rows) == [Escalate("rosy_01", "stuck-1", "no_rule")]


# ---- D-577 1: lane_lost answers only safe moves (R3 under all preconditions, else R5 WAIT + human) ----

def _lost(**kw):
    return _stuck(cause="lane_lost", **kw)


def _hold(reason):
    return [Answer("rosy_01", "stuck-1", "WAIT", "R5", escalate=f"lane_lost_hold:{reason}")]


def test_d577_r3_needs_every_precondition():
    r = StuckResolver(ResolverConfig(), painted=painted_without_crosswalks)
    me = _row(stuck=_lost())
    me["map_pose"] = {"state": "LOCALIZED", "age_s": 0.5}
    assert r.step(0.0, [me]) == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R3")]


def test_d577_peer_behind_holds_instead_of_backing_off():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    me = _row(stuck=_lost(), pose=(0.0, 0.0, 0.0), localization=_frame("map"))
    peer = _row("rosy_02", None, pose=(-0.20, 0.03, 0.0), localization=_frame("map"))
    assert r.step(0.0, [me, peer]) == _hold("peer_behind")


@pytest.mark.parametrize("legacy", ["me", "peer"])
def test_d577_legacy_odom_pose_never_clears_the_rear_band(legacy):
    """D-577 남은 항목 1: a robot without `localization` reports odom, not the painted map."""
    r = StuckResolver(ResolverConfig(), painted=painted_without_crosswalks)
    me = _row(stuck=_lost(), pose=(0.0, 0.0, 0.0),
              localization=None if legacy == "me" else _frame("map"))
    peer = _row("rosy_02", None, pose=(-3.0, 0.0, 0.0),
                localization=None if legacy == "peer" else _frame("map"))
    assert r.step(0.0, [me, peer]) == _hold("peer_unknown")


def test_d577_a_peer_ahead_does_not_block_r3():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    me = _row(stuck=_lost(), pose=(0.0, 0.0, 0.0), localization=_frame("map"))
    peer = _row("rosy_02", None, pose=(0.20, 0.0, 3.14), localization=_frame("map"))
    assert r.step(0.0, [me, peer]) == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R3")]


@pytest.mark.parametrize("stuck, extra, reason", [
    (_lost(attempts=2, max_attempts=2), {}, "attempts"),
    (_lost(local=False), {}, "local_disabled"),
    (_lost(), {"crosswalk": {"state": "WAITING", "zone_id": "cw-1"}}, "crosswalk"),
    (_lost(), {"map_pose": {"state": "DEGRADED", "age_s": 0.2}}, "pose"),
    (_lost(), {"map_pose": {"state": "LOCALIZED", "age_s": 2.5}}, "pose"),
    (_lost(), {"map_pose": {"state": "LOCALIZED", "age_s": None}}, "pose"),
])
def test_d577_each_false_precondition_is_r5(stuck, extra, reason):
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    row = _row(stuck=stuck)
    if "crosswalk" in extra:
        row["state"]["line_follow"]["crosswalk"] = extra["crosswalk"]
    if "map_pose" in extra:
        row["map_pose"] = extra["map_pose"]
    assert r.step(0.0, [row]) == _hold(reason)


def test_d577_unknown_map_pose_leaves_the_rear_to_core():
    r = StuckResolver(ResolverConfig(), painted=painted_without_crosswalks)
    row = _row(stuck=_lost())
    row["map_pose"] = {"state": "UNKNOWN", "age_s": None, "sourced": False}
    assert r.step(0.0, [row]) == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R3")]


def test_d577_r5_is_once_per_stuck_and_spends_no_budget():
    r = StuckResolver(ResolverConfig(rule_budget=1), painted=painted_without_crosswalks)
    first = r.step(0.0, [_row(stuck=_lost(local=False))])
    assert first == _hold("local_disabled")
    r.sent(first[0], 0.0)
    assert r.step(1.0, [_row(stuck=_lost(local=False))]) == []      # one R5 per stuck
    assert r._chains["rosy_01"].rule_answers == 0
    # The stuck closes and reopens inside the restuck window: R3 still has the whole budget.
    r.step(2.0, [_row(stuck=None)])
    assert r.step(3.0, [_row(stuck=_lost(stuck_id="stuck-2"))]) == [
        Answer("rosy_01", "stuck-2", "BACK_AND_RETRY", "R3")]


def test_d577_r5_still_stops_after_the_rule_budget():
    r = StuckResolver(ResolverConfig(rule_budget=1), painted=painted_without_crosswalks)
    back = r.step(0.0, [_row(stuck=_lost())])[0]
    r.sent(back, 0.0)
    r.step(1.0, [_row(stuck=None)])
    assert r.step(2.0, [_row(stuck=_lost(stuck_id="stuck-2", attempts=1))]) == [
        Answer("rosy_01", "stuck-2", "WAIT", "R5", escalate="lane_lost_hold:rule_budget")]


def test_d577_refused_back_off_holds_and_goes_to_a_human():
    r = StuckResolver(ResolverConfig(), painted=painted_without_crosswalks)
    back = r.step(0.0, [_row(stuck=_lost())])[0]
    r.sent(back, 0.0)
    assert r.result(back, code="STUCK_DECISION_REFUSED") is None
    assert r.step(1.0, [_row(stuck=_lost())]) == _hold("refused")


def test_d577_trip_robot_lane_lost_stays_no_rule():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    row = {**_row(stuck=_lost(local=False)), "trip": True}
    assert r.step(0.0, [row]) == [Escalate("rosy_01", "stuck-1", "no_rule")]


def test_d577_lane_lost_never_resumes_property():
    """1000 random rosters: no path sends RESUME (or YIELD) for a lane_lost stuck."""
    import random

    rnd = random.Random(577)
    painted = painted_track()
    track = [pose_on(painted, "east", s, direction=d) for s in (0.4, 1.0, 1.2, 1.45) for d in (1, -1)]
    for _ in range(1000):
        r = StuckResolver(ResolverConfig(rule_budget=rnd.choice((0, 1, 2))), painted=painted_track)
        rows = []
        for i in range(rnd.randint(1, 3)):
            pose = rnd.choice(track + [None, (rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-3, 3))])
            stuck = None
            if i == 0 or rnd.random() < 0.5:
                stuck = _stuck(f"s{i}", rnd.choice(("lane_lost", "obstacle_ahead")),
                               local=rnd.random() < 0.7, attempts=rnd.randint(0, 3))
                stuck["phase"] = rnd.choice(("ASKING", "YIELDED", "BACKING"))
            row = _row(f"r{i}", stuck, pose=pose, localization=rnd.choice((None, _frame("map"))))
            if rnd.random() < 0.3:
                row["trip"] = True
            if rnd.random() < 0.5:
                row["map_pose"] = {"state": rnd.choice(("LOCALIZED", "DEGRADED", "UNKNOWN")),
                                   "age_s": rnd.choice((None, 0.1, 3.0))}
            rows.append(row)
        for t in range(4):
            for action in r.step(float(t), rows):
                if isinstance(action, Answer):
                    cause = _row_cause(rows, action.robot_id)
                    if cause == "lane_lost":
                        assert action.decision in ("WAIT", "BACK_AND_RETRY"), action
                    r.sent(action, float(t))
                    if rnd.random() < 0.3:
                        r.result(action, code=rnd.choice((None, "STUCK_DECISION_REFUSED")))


def _row_cause(rows, robot_id):
    row = next(item for item in rows if item["robot_id"] == robot_id)
    return row["state"]["line_follow"]["stuck"]["cause"]


# ---- D-577 safety review (REVISE): fail closed on lost pose, untrusted peers, unknown crosswalk ----

def _clear(row):
    row["state"]["line_follow"]["crosswalk"] = None        # CORE reports "no crosswalk zone"
    return row


def test_d577_lost_map_pose_holds():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    row = _clear(_row(stuck=_lost()))
    row["map_pose"] = {"state": "UNKNOWN", "age_s": None, "sourced": True}
    assert r.step(0.0, [row]) == _hold("pose")


def test_d577_no_map_pose_source_leaves_r3():
    r = StuckResolver(ResolverConfig(), painted=painted_without_crosswalks)
    row = _clear(_row(stuck=_lost()))
    row["map_pose"] = {"state": "UNKNOWN", "age_s": None, "sourced": False}
    assert r.step(0.0, [row]) == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R3")]


def test_d577_absent_crosswalk_report_fails_closed():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    row = _row(stuck=_lost())
    del row["state"]["line_follow"]["crosswalk"]           # today's CORE: no crosswalk report at all
    assert r.step(0.0, [row]) == _hold("crosswalk_unknown")


@pytest.mark.parametrize("peer_kw", [
    {"pose": None},                                                       # online, no pose
    {"pose": (-1.0, 0.0, 0.0), "localization": {"state": "CANDIDATES", "pose_frame": "odom",
                                                "confidence": 0.2}},     # untrusted pose
])
def test_d577_unknown_peer_pose_holds(peer_kw):
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    me = _clear(_row(stuck=_lost(), localization=_frame("map")))
    peer = _row("rosy_02", None, **peer_kw)
    assert r.step(0.0, [me, peer]) == _hold("peer_unknown")


def test_d577_own_untrusted_pose_with_a_peer_online_holds():
    r = StuckResolver(ResolverConfig(), painted=painted_without_crosswalks)
    me = _clear(_row(stuck=_lost(), localization={"state": "SUSPECT", "pose_frame": "map",
                                                   "confidence": 0.3}))
    peer = _row("rosy_02", None, pose=(2.0, 0.0, 0.0), localization=_frame("map"))
    assert r.step(0.0, [me, peer]) == _hold("peer_unknown")


def test_d577_trusted_peer_far_away_allows_r3():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    me = _clear(_row(stuck=_lost(), localization=_frame("map")))
    peer = _row("rosy_02", None, pose=(-1.0, 0.0, 0.0), localization=_frame("map"))
    assert r.step(0.0, [me, peer]) == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R3")]


def test_d577_r5_wait_is_resent_once_after_a_transport_failure():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    row = _row(stuck=_lost(local=False))
    first = r.step(0.0, [row])[0]
    r.sent(first, 0.0)
    assert r.result(first, code="ROBOT_UNREACHABLE") is None            # one resend
    again = r.step(1.0, [row])
    assert again == [first]
    r.sent(again[0], 1.0)
    assert r.result(again[0], code="ROBOT_UNREACHABLE") == Escalate(
        "rosy_01", "stuck-1", "lane_lost_hold:local_disabled")
    assert r.step(2.0, [row]) == []


# ---- D-577 개정 2026-10-10: acting AI facts only stop a back-off ----

def test_d577_acting_ai_fact_turns_a_back_off_into_r5_wait_and_a_human():
    row = _row(stuck=_stuck())
    row["ai_facts"] = [{"kind": "rear_blocked", "robot_ids": ["rosy_01"], "stage": "acting"}]
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(0.0, [row]) == [Answer("rosy_01", "stuck-1", "WAIT", "R5",
                                         escalate="obstacle_ahead_hold:ai:rear_blocked")]
    plain = StuckResolver(ResolverConfig(), painted=painted_track)
    assert plain.step(0.0, [_row(stuck=_stuck())]) == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R2")]


# ---- D-577 개정 2026-10-10: AI PC proposes, Fleet validates the envelope, rules on refusal/timeout ----

def _proposal(decision="BACK_AND_RETRY", stuck_id="stuck-1", reason="obstacle_ahead_back_off"):
    return {"robot_id": "rosy_01", "stuck_id": stuck_id, "decision": decision, "reason": reason,
            "confidence": 0.6, "evidence": {}, "source": "analyzer:stuck_scene@1", "observed_at": 0.0, "ttl_s": 6.0}


def _ai_row(proposal=None, stuck=None, wait=True):
    row = _row(stuck=stuck or _stuck())
    if proposal is not None:
        row["ai_proposal"] = proposal
    if wait:
        row["ai_wait"] = True
    return row


def test_d577_valid_ai_proposal_is_forwarded():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(0.0, [_ai_row(_proposal())]) == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "ai")]
    assert [v["verdict"] for v in r.ai_verdicts] == ["forwarded"]
    wait = StuckResolver(ResolverConfig(), painted=painted_track)
    assert wait.step(0.0, [_ai_row(_proposal("WAIT", reason="rear_blocked"))]) == [
        Answer("rosy_01", "stuck-1", "WAIT", "ai", escalate="ai_wait:rear_blocked")]


@pytest.mark.parametrize("proposal, stuck, verdict, fallback", [
    (_proposal("MANUAL"), None, "word_not_allowed", "BACK_AND_RETRY"),
    (_proposal("RESUME"), _stuck(cause="lane_lost"), "word_not_allowed", None),
    (_proposal(stuck_id="stuck-0"), None, "stuck_mismatch", "BACK_AND_RETRY"),
    (_proposal(), _stuck(attempts=2), "attempts", None),
    (_proposal(), _stuck(local=False), "local_disabled", None),
])
def test_d577_invalid_ai_proposal_falls_back_to_the_rules(proposal, stuck, verdict, fallback):
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    actions = r.step(10.0, [_ai_row(proposal, stuck, wait=False)])
    assert [v["verdict"] for v in r.ai_verdicts] == [verdict]
    assert not any(isinstance(a, Answer) and a.rule == "ai" for a in actions)
    if fallback:
        assert actions == [Answer("rosy_01", "stuck-1", fallback, "R2")]


def test_d577_no_ai_proposal_in_time_falls_back_to_the_rules():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(0.0, [_ai_row()]) == []                   # the AI PC still has its time
    assert r.step(4.0, [_ai_row()]) == []
    assert r.step(5.1, [_ai_row()]) == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R2")]
    assert r.ai_verdicts == []


# ---- D-577 개정 2026-10-10 Safety-Review: every AI proposal passes the rules' gates ----

def _judged(proposal, row, *rows):
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    actions = r.step(10.0, [row, *rows])
    return r.ai_verdicts[0]["verdict"], [a for a in actions if isinstance(a, Answer) and a.rule == "ai"]


def _with(row, **line_follow):
    row["state"]["line_follow"].update(line_follow)
    return row


@pytest.mark.parametrize("decision", ["ABORT", "BACK_AND_RETRY"])
def test_d577_ai_abort_resume_back_off_hold_where_a_crosswalk_is_unknown_or_occupied(decision):
    row = _ai_row(_proposal(decision), wait=False)
    del row["state"]["line_follow"]["crosswalk"]
    assert _judged(None, row)[0] == "crosswalk_unknown"
    row = _with(_ai_row(_proposal(decision), wait=False), crosswalk={"zone_id": "cw-1"})
    assert _judged(None, row)[0] == "crosswalk"


def test_d577_forwarded_ai_abort_also_raises_a_human_row():
    verdict, sent = _judged(None, _ai_row(_proposal("ABORT", reason="scene_blocked"), wait=False))
    assert verdict == "forwarded"
    assert sent == [Answer("rosy_01", "stuck-1", "ABORT", "ai", escalate="ai_abort:scene_blocked")]


@pytest.mark.parametrize("decision, stuck, extra, verdict", [
    ("BACK_AND_RETRY", _stuck(local=False), {}, "local_disabled"),
    ("BACK_AND_RETRY", _stuck(attempts=2), {}, "attempts"),
    ("BACK_AND_RETRY", None, {"map_pose": {"state": "LOCALIZED", "age_s": 5.0}}, "pose"),
    ("BACK_AND_RETRY", None, {"map_pose": {"state": "DEGRADED", "age_s": 0.1}}, "pose"),
    ("BACK_AND_RETRY", None, {"ai_facts": [{"kind": "rear_blocked", "robot_ids": ["rosy_01"], "stage": "acting"}]},
     "ai_fact:rear_blocked"),
    ("BACK_AND_RETRY", None, {"ai_facts": [{"kind": "path_blocked_by_robot", "robot_ids": ["rosy_01"],
                                            "stage": "acting"}]}, "ai_fact:path_blocked_by_robot"),
])
def test_d577_ai_moving_words_need_every_r3_precondition(decision, stuck, extra, verdict):
    row = _ai_row(_proposal(decision), stuck, wait=False)
    row.update(extra)
    assert _judged(None, row) == (verdict, [])


def test_d577_ai_back_off_holds_for_an_untrusted_peer_pose_and_resume_is_never_an_ai_word():
    peer = _row("rosy_02", pose=(0.2, 0.0, 0.0))             # LEGACY odom pose: not a map pose
    no_motion = _ai_row(_proposal(), _stuck(cause="no_motion"), wait=False)
    assert _judged(None, no_motion, peer)[0] == "peer_unknown"   # R6's waiver is not the AI's
    for cause in ("obstacle_ahead", "lane_lost", "no_motion"):   # the rules never RESUME a stuck
        assert _judged(None, _ai_row(_proposal("RESUME"), _stuck(cause=cause), wait=False)) == (
            "word_not_allowed", [])


@pytest.mark.parametrize("stuck, setup, verdict", [
    (None, lambda row: row["state"]["line_follow"].pop("crosswalk"), "crosswalk_unknown"),
    (None, lambda row: row.update(trip=True), "trip"),
    (_stuck(cause="crosswalk_blocked"), lambda row: None, "word_not_allowed"),
])
def test_d577_a_held_ai_abort_stops_with_r5_wait_and_a_human_not_the_rules_motion(stuck, setup, verdict):
    row = _ai_row(_proposal("ABORT"), stuck, wait=False)
    setup(row)
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(10.0, [row]) == [Answer("rosy_01", "stuck-1", "WAIT", "R5", escalate=f"ai_abort_held:{verdict}")]
    assert [v["verdict"] for v in r.ai_verdicts] == [verdict]


def test_d577_a_proposal_after_the_stuck_was_answered_is_audited_not_acted_on():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    answer = r.step(10.0, [_ai_row(wait=False)])
    assert answer == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R2")]
    r.sent(answer[0], 10.0)
    assert r.step(11.0, [_ai_row(_proposal("ABORT"), wait=False)]) == []
    assert r.step(12.0, [_ai_row(_proposal("ABORT"), wait=False)]) == []
    assert [v["verdict"] for v in r.ai_verdicts] == ["after_answer"]


def test_d577_ai_back_off_with_a_peer_ahead_waits_for_r1_first():
    peer = _row("rosy_02", pose=(0.2, 0.0, 0.0))
    peer["state"]["localization"] = _frame("map")
    row = _ai_row(_proposal(), wait=False)
    row["state"]["localization"] = _frame("map")
    assert _judged(None, row, peer)[0] == "peer_ahead"


def test_d577_ai_never_forwards_a_moving_word_the_r3_gate_would_hold():
    import random

    from fleet.server.stuck_lane_lost import lane_lost_hold
    from fleet.server.stuck_resolver import _Chain

    rng = random.Random(577)
    for _ in range(1000):
        cause = rng.choice(["obstacle_ahead", "lane_lost", "no_motion"])
        decision = rng.choice(["WAIT", "BACK_AND_RETRY", "RESUME", "ABORT"])
        stuck = _stuck(cause=cause, local=rng.random() < 0.7, attempts=rng.randint(0, 2))
        if rng.random() < 0.3:
            stuck["rear_state"] = "blocked"
        row = _ai_row(_proposal(decision), stuck, wait=False)
        if rng.random() < 0.3:
            row["map_pose"] = {"state": rng.choice(["LOCALIZED", "DEGRADED"]), "age_s": rng.uniform(0, 4)}
        crosswalk = rng.choice(["absent", None, {"zone_id": "cw"}])
        if crosswalk == "absent":
            del row["state"]["line_follow"]["crosswalk"]
        else:
            row["state"]["line_follow"]["crosswalk"] = crosswalk
        if rng.random() < 0.3:
            row["trip"] = True
        rows = [row] + ([_row("rosy_02", pose=(rng.uniform(-0.4, 0.4), rng.uniform(-0.2, 0.2), 0.0))]
                        if rng.random() < 0.6 else [])
        if rng.random() < 0.5:                                # trusted map poses: the peer band is real
            for each in rows:
                each["state"]["localization"] = _frame("map")
        r = StuckResolver(ResolverConfig(), painted=painted_track)
        for answer in r.step(10.0, rows):
            if not isinstance(answer, Answer) or answer.rule != "ai":
                continue
            assert not row.get("trip") or answer.decision == "WAIT"
            assert answer.decision != "RESUME"
            if answer.decision == "BACK_AND_RETRY":
                assert lane_lost_hold(row, stuck, rows, _Chain(0.0, ""), ResolverConfig()) is None
                assert stuck.get("rear_state") != "blocked"
            if answer.decision != "WAIT":
                assert row["state"]["line_follow"].get("crosswalk", "absent") is None


# ---- D-573 6 개정 2026-10-10: CORE reports crosswalk null / zone / unknown with the gate off ----

def test_d573_core_unknown_crosswalk_holds_as_unknown():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    row = _row(stuck=_lost())
    row["state"]["line_follow"]["crosswalk"] = {"state": "unknown", "source": "camera", "reason": "pose_stale"}
    assert r.step(0.0, [row]) == _hold("crosswalk_unknown")


@pytest.mark.parametrize("state", ["inside", "ahead"])
def test_d573_core_zone_holds_as_crosswalk(state):
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    row = _row(stuck=_lost())
    row["state"]["line_follow"]["crosswalk"] = {"state": state, "source": "camera"}
    assert r.step(0.0, [row]) == _hold("crosswalk")


def test_d573_core_null_crosswalk_with_every_other_precondition_opens_r3():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    me = _clear(_row(stuck=_lost(), localization=_frame("map")))
    me["map_pose"] = {"state": "LOCALIZED", "age_s": 0.2}
    peer = _row("rosy_02", None, pose=(3.0, 0.0, 0.0), localization=_frame("map"))
    assert r.step(0.0, [me, peer]) == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R3")]


# ---- D-577 남은 항목 2: a failed R5 send is resent as R5, never replaced by R3 ----

def test_d577_failed_r5_send_is_resent_as_the_same_r5_even_if_r3_now_holds():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    me = _clear(_row(stuck=_lost(), localization=_frame("map")))
    behind = _row("rosy_02", None, pose=(-0.20, 0.03, 0.0), localization=_frame("map"))
    first = r.step(0.0, [me, behind])
    assert first == _hold("peer_behind")
    r.sent(first[0], 0.0)
    assert r.result(first[0], code="ROBOT_UNREACHABLE") is None        # one transport resend
    gone = _row("rosy_02", None, pose=(3.0, 0.0, 0.0), localization=_frame("map"))
    assert r.step(1.0, [me, gone]) == first                            # not R3


# ---- D-573 1 / review 2026-10-10: the site-map crosswalk is the reference for R3 ----
# painted_track() carries map_v2_fleet's two lane_graph crosswalks; one spans x 0.309..0.429, y -0.582..-0.438.

def _clear_trusted(pose):
    row = _clear(_row(stuck=_lost(), pose=pose, localization=_frame("map")))
    row["map_pose"] = {"state": "LOCALIZED", "age_s": 0.2}
    return row


@pytest.mark.parametrize("pose", [(0.37, -0.50, 0.0),       # on it
                                  (0.37, -0.20, 0.0)])     # 0.24 m beside it: within body + back-off reach
def test_d573_map_crosswalk_near_the_trusted_pose_holds_even_with_core_null(pose):
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(0.0, [_clear_trusted(pose)]) == _hold("crosswalk")


def test_d573_map_crosswalk_far_from_the_trusted_pose_leaves_r3():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    assert r.step(0.0, [_clear_trusted((0.0, 0.0, 0.0))]) == [Answer("rosy_01", "stuck-1", "BACK_AND_RETRY", "R3")]


def test_d573_map_with_crosswalks_and_no_trusted_pose_holds():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    legacy = _clear(_row(stuck=_lost()))                          # no localization: odom, not the map
    assert r.step(0.0, [legacy]) == _hold("crosswalk_unknown")


def test_d573_map_with_crosswalks_and_an_unsourced_unknown_pose_holds():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    row = _clear(_row(stuck=_lost(), localization=_frame("map")))
    row["map_pose"] = {"state": "UNKNOWN", "age_s": None, "sourced": False}
    assert r.step(0.0, [row]) == _hold("crosswalk_unknown")


# ---- merge of XW removal and D-573 6 crosswalk holds: the stricter answer wins ----

def test_overlap_mapped_crosswalk_with_unknown_report_and_an_ai_back_off_waits_for_a_human():
    r = StuckResolver(ResolverConfig(), painted=painted_track)
    r.at_crosswalk = lambda rid: True
    for trip in (False, True):
        row = _ai_row(_proposal(), _lost(), wait=False)
        row["state"]["line_follow"]["crosswalk"] = {"state": "unknown", "source": "camera", "reason": "pose_stale"}
        if trip:
            row["trip"] = True
        r = StuckResolver(ResolverConfig(), painted=painted_track)
        r.at_crosswalk = lambda rid: True
        assert r.step(10.0, [row]) == [Answer("rosy_01", "stuck-1", "WAIT", "R5", escalate="crosswalk_human")]
