"""D-577 (d): the stuck_scene analyzer — facts from CORE's own words and trusted poses, no command words."""

from __future__ import annotations

from rosy_situation.analyzers import Analyzer

TRUSTED = {"trusted": True, "legacy": False}
LEGACY = {"trusted": True, "legacy": True}


def _row(rid, x=0.0, y=0.0, yaw=0.0, *, mode="CAMERA_LINE", reason="camera_line_not_visible", loc=LEGACY,
         linear=0.0):
    return {"robot_id": rid, "online": True, "localization": loc,
            "state": {"pose": {"x": x, "y": y, "yaw": yaw},
                      "line_follow": {"mode": mode, "state": "HOLD", "reason": reason, "linear": linear,
                                      "angular": 0.0, "stuck": None}}}


def _snap(t, rows, pending=(), answers=()):
    return {"observed_at": t, "state": {"robots": list(rows)},
            "line_stuck": {"pending": list(pending), "answers": list(answers)}}


def _kinds(facts):
    return sorted((f["kind"], tuple(f["robot_ids"])) for f in facts)


def test_rear_blocked_from_the_hub_row_and_from_a_refusal_until_the_robot_moves():
    a = Analyzer()
    stuck = {"robot_id": "rosy_41", "stuck_id": "s1", "rear_state": "blocked", "rear_clearance_m": 0.04}
    assert _kinds(a(_snap(1, [_row("rosy_41")], [stuck]))) == [("rear_blocked", ("rosy_41",))]
    refusal = {"robot_id": "rosy_41", "stuck_id": "s2", "at": "t2", "message": "BACK_AND_RETRY refused: rear_blocked"}
    old = {"robot_id": "rosy_41", "stuck_id": "s0", "at": "t0", "message": "BACK_AND_RETRY refused: rear_blocked"}
    b = Analyzer()
    assert b(_snap(1, [_row("rosy_41")], answers=[old])) == []          # history at start is not news
    assert _kinds(b(_snap(2, [_row("rosy_41")], answers=[old, refusal]))) == [("rear_blocked", ("rosy_41",))]
    assert _kinds(b(_snap(3, [_row("rosy_41", x=0.02)], answers=[old, refusal]))) == [("rear_blocked", ("rosy_41",))]
    assert b(_snap(4, [_row("rosy_41", x=0.2)], answers=[old, refusal])) == []
    assert b(_snap(5, [_row("rosy_41")], answers=[old, refusal])) == []   # same refusal is not new again


def test_path_blocked_by_robot_needs_trusted_map_poses():
    pending = [{"robot_id": "a", "stuck_id": "s"}]
    rows = [_row("a", loc=TRUSTED), _row("b", x=0.25, loc=TRUSTED)]
    assert _kinds(Analyzer()(_snap(1, rows, pending))) == [("path_blocked_by_robot", ("a", "b"))]
    legacy = [_row("a"), _row("b", x=0.25)]                             # odom frames: never compared
    assert Analyzer()(_snap(1, legacy, pending)) == []
    behind = [_row("a", loc=TRUSTED), _row("b", x=-0.25, loc=TRUSTED)]
    assert Analyzer()(_snap(1, behind, pending)) == []


def test_stalled_reports_an_unreported_hold_after_20_s():
    a = Analyzer()
    assert a(_snap(0, [_row("r", reason="low_light")])) == []
    assert a(_snap(19, [_row("r", reason="low_light")])) == []
    facts = a(_snap(20, [_row("r", reason="low_light")]))
    assert _kinds(facts) == [("stalled", ("r",))] and facts[0]["value"]["reason"] == "low_light"
    assert a(_snap(21, [_row("r", linear=0.05)])) == []                   # moving resets
    assert a(_snap(50, [_row("r", mode="OFF")])) == []


def test_facts_pass_fleet_validation():
    from fleet.server.ai_facts import AiFact

    a = Analyzer()
    stuck = {"robot_id": "r", "stuck_id": "s1", "rear_state": "blocked", "rear_clearance_m": 0.04}
    for fact in a(_snap(1000.0, [_row("r")], [stuck])):
        AiFact.model_validate(fact).check(1000.0)


def test_trip_route_fact_checks_only_the_planned_edge_and_reports_stale_as_unknown():
    from fleet.server.ai_facts import AiFact

    route_map = {"version": 5, "map": {"edges": [{"id": "east", "polyline": [[0, 0], [1, 0]],
                                                 "width_m": 0.2}]}}
    trip = {"robot_id": "r", "trip_id": "t", "map_version": 5, "segment_index": 0,
            "plan": {"segments": [{"edge_id": "east", "forward": True, "s_from": 0.2, "s_to": 0.8}]},
            "pose": {"x": 0.5, "y": 0.0, "state": "LOCALIZED", "source": "sighting", "age_s": 0.1}}
    analyzer = Analyzer()

    def check(pose, site_map=route_map, route=trip):
        snapshot = {**_snap(1000.0, [_row("r", mode="OFF")]), "trips": {"open": [{**route, "pose": pose}]},
                    "route_map": site_map}
        fact = analyzer(snapshot)[0]
        AiFact.model_validate(fact).check(1000.0)
        return fact["value"]

    assert check(trip["pose"])["status"] == "ON_ROUTE"
    assert check({**trip["pose"], "y": 0.12})["status"] == "OFF_ROUTE"
    assert check({**trip["pose"], "x": 0.95})["status"] == "OFF_ROUTE"  # beyond planned s_to
    assert check({**trip["pose"], "age_s": 2.0})["status"] == "UNKNOWN"
    assert check(trip["pose"], {**route_map, "version": 6})["status"] == "UNKNOWN"
    assert check(trip["pose"], route={**trip, "segment_index": 99})["status"] == "UNKNOWN"


def test_one_proposal_per_stuck_wait_when_the_rear_is_blocked():
    a = Analyzer()
    stuck = {"robot_id": "r", "stuck_id": "s1", "cause": "no_motion", "detail": "lane_departure"}
    a(_snap(1, [_row("r")], [stuck]))
    assert [(p["decision"], p["reason"]) for p in a.proposals] == [("BACK_AND_RETRY", "no_motion_back_off")]
    a(_snap(2, [_row("r")], [stuck]))
    assert a.proposals == []                                            # same proposal is not sent twice
    a(_snap(3, [_row("r")], [{**stuck, "rear_state": "blocked"}]))
    assert [(p["decision"], p["reason"]) for p in a.proposals] == [("WAIT", "rear_blocked")]
    a(_snap(4, [_row("r")], [{**stuck, "cause": "crosswalk_blocked", "stuck_id": "s2"}]))
    assert a.proposals == []                                            # a crosswalk is a person's


def test_proposals_pass_fleet_validation():
    from fleet.server.ai_facts import AiProposal

    a = Analyzer()
    a(_snap(1000.0, [_row("r")], [{"robot_id": "r", "stuck_id": "s1", "cause": "lane_lost"}]))
    for proposal in a.proposals:
        AiProposal.model_validate(proposal)
