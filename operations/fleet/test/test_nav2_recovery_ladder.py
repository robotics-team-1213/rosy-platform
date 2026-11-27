"""D-1082 ladder: each resend changes a condition (recentre, then slow), the wall side slows early, and an exhausted
recovery records where and why (2026-11-27 rosy_45, three identical resends against the wall all failed)."""
import json
import math

import pytest

from fakes import run
from fleet.server import nav2_recovery_ladder as ladder
from fleet.server import nav2_trip_recovery as rec
from fleet.server import trip_lane_realign as realign
from fleet.server.nav2_route_sampling import NAV2_RECENTRE_AHEAD_M, sample_nav2_route
from fleet.site_map import SiteMap
from test_nav2_trip_recovery import _pose, _recover_once, _tick, _trip
from test_trip_lane_realign import Rig, _grant
from test_trip_nav2_route import _south_loop_map

STRAIGHT = [dict(edge_id="upper_west", forward=True, s_from=0., s_to=1.)]


@pytest.mark.parametrize("recovery, expected", [
    (None, (.15, "route_profile")),
    ({"state": "resumed", "attempt": 1}, (.15, "route_profile")),
    ({"state": "waiting", "attempt": 2}, (.15, "route_profile")),
    ({"state": "resumed", "attempt": 2}, (realign.REALIGN_SLOW_MPS, "recovery_slow")),
    ({"state": "resumed", "attempt": 3}, (realign.REALIGN_SLOW_MPS, "recovery_slow")),
])
def test_the_second_resend_onward_runs_under_the_slow_cap(recovery, expected):
    detail = {} if recovery is None else {"recovery": recovery}
    assert _grant(_south_loop_map(), STRAIGHT, detail) == expected


def test_the_slow_cap_ends_with_the_episode():
    robot, clock, _store, graph, pose, _c, runner, live = _trip()
    _recover_once(runner, clock, live)
    _recover_once(runner, clock, live)
    detail = live.view["detail"]
    assert ladder.recovery_slow(detail) and detail["recovery"]["attempts"][1]["speed_cap_mps"] == realign.REALIGN_SLOW_MPS
    assert detail["recovery"]["attempts"][0]["speed_cap_mps"] is None
    arc = graph.arcs["upper_east:fwd"]
    pose["v"] = _pose(*arc.point_at(arc.length_m - 0.01))
    detail["recovery"]["resumed_progress"] -= rec.RESET_M     # as if 1 m had passed since the resume
    _tick(runner, clock)
    assert "recovery" not in detail and not ladder.recovery_slow(detail)


def test_the_recovery_resend_recentres_inside_the_threshold():
    robot, clock, store, graph, pose, _c, runner, live = _trip()
    run(runner._stop(live, "stopped", "navigation", {}))
    x, y, t = graph.arcs["upper_east:fwd"].point_at(0.12)
    pose["v"] = _pose(x - math.sin(t) * 0.02, y + math.cos(t) * 0.02, t)   # 2 cm off: under NAV2_ROUTE_MIN_GAP_M
    _tick(runner, clock, 6)
    assert len(robot.routes) == 2 and live.view["detail"]["recovery"]["resent_at"] is not None
    index, s = live.at
    kw = dict(walls=getattr(store.active()[1], "walls", ()), here=(pose["v"].x, pose["v"].y))
    forced = sample_nav2_route(graph, live.segments, index, s, live.active_route["end_index"], recentre=True, **kw)
    plain = sample_nav2_route(graph, live.segments, index, s, live.active_route["end_index"], **kw)
    first = robot.routes[1][0][0]
    assert (first["x"], first["y"]) == pytest.approx(forced[0][:2], abs=1e-3) and forced[0][:2] != plain[0][:2]
    assert not ladder.recovery_resend(live)                    # once per recovery: a later replan is plain


def test_recentre_puts_the_first_point_ahead_from_a_small_offset():
    from fleet.routing.graph import build_graph
    graph = build_graph(_south_loop_map())
    arc = graph.arcs["upper_west:fwd"]
    segs = [dict(edge_id="upper_west", forward=True, s_from=0., s_to=arc.length_m)]
    px, py, t = arc.point_at(0.3)
    here = (px - math.sin(t) * 0.01, py + math.cos(t) * 0.01)
    pts = sample_nav2_route(graph, segs, 0, 0.3, 0, here=here, recentre=True)
    ahead = (pts[0][0] - here[0]) * math.cos(t) + (pts[0][1] - here[1]) * math.sin(t)
    assert ahead >= NAV2_RECENTRE_AHEAD_M - 1e-6
    assert sample_nav2_route(graph, segs, 0, 0.3, 0, recentre=True) == sample_nav2_route(graph, segs, 0, 0.3, 0)


def _walled(extra_edge=False):
    layout = json.loads(_south_loop_map().model_dump_json(by_alias=True))
    layout["walls"] = [{"id": "north", "face": [[-0.6, -0.12], [0.3, -0.12]]}]   # 0.13 m north of upper_west
    if extra_edge:
        layout["places"].append({"id": "C2", "name": "C2", "x": .91, "y": -.68, "kind": "charge", "yaw": math.pi / 2})
        layout["edges"].append({"id": "bay2", "from": "S5", "to": "C2", "direction": "two_way", "drive_mode": "lane",
                                "width_m": .2, "speed_cap_mps": .1, "polyline": [[.91, -.48], [.91, -.68]]})
    return SiteMap.model_validate(layout)


# upper_west runs west: "left" is south, so a negative left offset is toward the north wall.
def test_wall_side_offset_slows_without_a_resend_then_releases():
    rig = Rig(site=_walled())
    first = rig.tick(-0.03)
    replace, record = rig.tick(-0.03)
    assert not first[1]["slow"] and record["slow"] and not replace and record["kind"] == "near_edge"
    assert record["wall_clear_m"] == pytest.approx(0.10) and record["centre_wall_clear_m"] == pytest.approx(0.13)
    assert record["replaced"] == 0 and record["wall_side_at"] is not None
    _, record = rig.tick(0.0)                                   # back on the centre, aligned
    assert not record["slow"]
    rig.tick(-0.03), rig.tick(-0.03)
    slow = [rig.tick(-0.03, age=2.0)[1]["slow"] for _ in range(int(realign.SLOW_EVIDENCE_S / 0.5) + 1)]
    assert slow[0] and slow[-1] is False                        # 10 s without fresh evidence lifts it


@pytest.mark.parametrize("case", ["no_walls", "away_from_wall", "small_offset", "location", "not_navigating",
                                  "charge_bay"])
def test_wall_side_prevention_does_not_fire(case):
    site = _south_loop_map() if case == "no_walls" else _walled(extra_edge=case == "charge_bay")
    rig = Rig("bay2:fwd" if case == "charge_bay" else "upper_west:fwd", site)
    left = {"away_from_wall": 0.03, "small_offset": -0.01}.get(case, -0.03)
    kw = {"location": {"state": {"localization": {"state": "SUSPECT"}}},
          "not_navigating": {"nav": "IDLE"}}.get(case, {})
    records = [rig.tick(left, **kw) for _ in range(3)]
    assert not any(r for r, _ in records) and not records[-1][1]["slow"]


def test_an_exhausted_recovery_records_the_last_stop_and_each_attempt():
    robot, clock, *_rest, runner, live = _trip()
    for _ in range(rec.MAX_ATTEMPTS):
        _recover_once(runner, clock, live)
    live.view["detail"]["lane_departure"] = {"kind": "near_edge", "lat_m": -0.03, "wall_clear_m": 0.10}
    run(runner._stop(live, "stopped", "navigation", {"navigation": "FAILED"}))
    record = runner.view("p-rc")["detail"]["recovery"]
    assert record["state"] == "exhausted" and [a["attempt"] for a in record["attempts"]] == [1, 2, 3]
    assert [a["speed_cap_mps"] for a in record["attempts"]] == [None, realign.REALIGN_SLOW_MPS, realign.REALIGN_SLOW_MPS]
    assert record["final"]["lat_m"] == -0.03 and record["final"]["wall_clear_m"] == 0.10
    assert record["same_spot"]["count"] == 4 and record["same_spot"]["reason"] == "navigation"


def test_stops_at_different_spots_are_not_a_same_spot_repeat():
    robot, clock, _store, graph, pose, _c, runner, live = _trip()
    arc = graph.arcs["upper_east:fwd"]
    for k in range(rec.MAX_ATTEMPTS):
        pose["v"] = _pose(*arc.point_at(0.05 + 0.06 * k))
        _recover_once(runner, clock, live)
    pose["v"] = _pose(*arc.point_at(0.25))
    _tick(runner, clock)
    run(runner._stop(live, "stopped", "navigation", {}))
    record = live.view["detail"]["recovery"]
    assert record["state"] == "exhausted" and "same_spot" not in record


def test_a_wait_that_runs_out_counts_no_new_stop():
    live = type("L", (), {})()
    live.road_pose = _pose(0.5, -0.25, 0.0)
    live.view = {"detail": {}}
    record = {"reason": "stall", "attempts": [ladder.attempt_entry(live, "stall", k, 0.0) for k in (1, 2)]}
    ladder.exhaust(live, record, 1.0)
    assert record["state"] == "exhausted" and "same_spot" not in record
    ladder.exhaust(live, record, 2.0, "stall")
    assert record["same_spot"]["count"] == 3
