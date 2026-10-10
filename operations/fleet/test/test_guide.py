"""D-536: robot situation and coordinate guides on the live site map (map_v2_fleet, demo one-way)."""

from __future__ import annotations

import asyncio
import math

from core_common.robot_body import PINKY_PRO
from fleet.guide.situation import GuideConfig, add_near, lane_context, situation, uncertainty_m
from fleet.localization.map_pose import MapPose
from fleet.routing.graph import build_graph
from fleet.server.guide_service import GuideService
from test_blocks import _demo_map

GRAPH = build_graph(_demo_map())
ZONES = {edge: "roundabout" for edge in ("ring_n", "ring_s", "ring_e", "ring_w")}
R, HALF = PINKY_PRO.rotation_radius_m, PINKY_PRO.half_width_m


def _pose(x, y, yaw, state="LOCALIZED", reckon=0.0, refused=None):
    return MapPose(x, y, yaw, state, "sighting", reckon, 0.1, 0.1, "map_v2_fleet",
                   odom_refused=2 if refused else 0, odom_refused_reason=refused)


def _on(arc_id, s, lateral=0.0, turn=0.0):
    arc = GRAPH.arcs[arc_id]
    x, y, yaw = arc.point_at(s)
    return x - math.sin(yaw) * lateral, y + math.cos(yaw) * lateral, yaw + turn


def _record(pose, **kw):
    args = dict(online=True, pose=pose, tracking_row=None, camera_ok=None, graph=GRAPH, zone_of=ZONES,
                body_radius_m=R, body_half_width_m=HALF)
    args.update(kw)
    return situation("rosy_26", **args)


def _codes(record):
    return [f["code"] for f in record["findings"]]


def test_a_robot_on_its_lane_has_no_finding_and_a_full_record():
    record = _record(_pose(*_on("east:fwd", 1.0)))
    assert _codes(record) == []
    lane = record["lane"]
    assert lane["edge_id"] == "east" and lane["one_way"] and abs(lane["lateral_m"]) < 1e-3
    assert abs(lane["heading_err_deg"]) < 0.5 and lane["zone"] is None
    assert lane["next_place"]["place_id"] == GRAPH.arcs["east:fwd"].end_place
    assert record["pose"]["u_m"] == uncertainty_m(0.0) == 0.12 and record["body_radius_m"] == R


def test_off_lane_points_back_to_the_lane_centre():
    x, y, yaw = _on("east:fwd", 1.0, lateral=0.09)
    record = _record(_pose(x, y, yaw))
    assert _codes(record) == ["OFF_LANE"]
    target = record["findings"][0]["target"]
    cx, cy, cyaw = GRAPH.arcs["east:fwd"].point_at(1.0)
    assert math.hypot(target["x"] - cx, target["y"] - cy) < 1e-2 and abs(target["yaw"] - cyaw) < 1e-3
    assert "왼쪽" in record["findings"][0]["text"]


def test_wrong_way_on_a_one_way_lane_shows_the_lane_direction():
    record = _record(_pose(*_on("east:fwd", 1.0, turn=math.pi)))
    assert _codes(record) == ["WRONG_WAY"]
    assert abs(record["lane"]["heading_err_deg"]) > 170


def test_standing_in_the_roundabout_is_critical_after_ten_seconds():
    pose = _pose(*_on("ring_n:fwd", 0.15))
    assert _codes(_record(pose, stopped_s=5.0)) == []
    record = _record(pose, stopped_s=12.0)
    assert _codes(record) == ["STOPPED_IN_ZONE"] and record["findings"][0]["severity"] == "crit"
    assert record["lane"]["zone"] == "roundabout"


def test_camera_not_seeing_and_clock_ahead_are_explained_with_the_fix():
    record = _record(_pose(None, None, None, state="UNKNOWN", refused="future"),
                     tracking_row={"robot_id": "rosy_26", "status": "NO_POSE"}, camera_ok="ceiling_north")
    assert _codes(record) == ["CAMERA_NOT_SEEING", "ODOM_CLOCK_AHEAD"] and record["pose"] is None
    assert record["findings"][0]["action"] == {"kind": "relearn", "source_id": "ceiling_north"}
    assert "LED" not in record["findings"][0]["text"]  # nothing anonymous to blink at
    assert _codes(_record(_pose(None, None, None, state="UNKNOWN"))) == ["POSE_UNKNOWN"]


def test_camera_not_seeing_with_an_anonymous_blob_suggests_led_identify():
    """D-596: a blob no robot is matched to is named by the LED, standing or not."""
    record = _record(_pose(None, None, None, state="UNKNOWN"), anonymous_seen=True,
                     tracking_row={"robot_id": "rosy_26", "status": "NO_POSE"}, camera_ok="ceiling_north")
    (finding,) = record["findings"]
    assert finding["code"] == "CAMERA_NOT_SEEING" and "LED로 찾기" in finding["text"]
    assert finding["action"] == {"kind": "identify", "robot_id": "rosy_26"}


def test_an_offline_robot_has_no_guide_and_off_map_is_said():
    assert _codes(_record(_pose(*_on("east:fwd", 1.0)), online=False)) == []
    assert _codes(_record(_pose(5.0, 5.0, 0.0))) == ["OFF_MAP"]
    assert lane_context(GRAPH, 5.0, 5.0, 0.0, ZONES) is None


def test_two_body_circles_too_close_are_critical_for_both():
    a = situation("a", online=True, pose=_pose(*_on("east:fwd", 1.0)), tracking_row=None, camera_ok=None,
                  graph=GRAPH, zone_of=ZONES, body_radius_m=R, body_half_width_m=HALF)
    b = situation("b", online=True, pose=_pose(*_on("east:fwd", 1.0 + 2 * R + 0.02)), tracking_row=None,
                  camera_ok=None, graph=GRAPH, zone_of=ZONES, body_radius_m=R, body_half_width_m=HALF)
    far = situation("c", online=True, pose=_pose(*_on("east:fwd", 2.5)), tracking_row=None, camera_ok=None,
                    graph=GRAPH, zone_of=ZONES, body_radius_m=R, body_half_width_m=HALF)
    records = [a, b, far]
    add_near(records, GuideConfig())
    assert _codes(a) == ["TOO_CLOSE"] and _codes(b) == ["TOO_CLOSE"] and _codes(far) == []


class _Gather:
    def __init__(self, robots):
        self.robots = robots

    async def __call__(self):
        return {"robots": self.robots}


class _Poses:
    def __init__(self, poses):
        self.poses = poses

    def arbitrated_pose(self, robot_id):
        return self.poses.get(robot_id)


class _Maps:
    def active(self):
        return (3, None, GRAPH)


class _Tracking:
    def snapshot(self):
        return {"sources": [{"source_id": "ceiling_north", "status": "OK"}],
                "robots": [{"robot_id": "rosy_60", "status": "NO_POSE"}],
                "unknown": [{"x": 1.0, "y": 1.0, "marker_id": None}]}


def test_the_service_builds_one_record_per_robot_and_keeps_the_still_clock():
    now = [100.0]
    still = {"velocity": {"linear": 0.0, "angular": 0.0}}
    service = GuideService(
        gather=_Gather([{"robot_id": "rosy_26", "online": True, "state": still},
                        {"robot_id": "rosy_60", "online": True, "state": still}]),
        poses=_Poses({"rosy_26": _pose(*_on("ring_s:fwd", 0.15)), "rosy_60": _pose(None, None, None, "UNKNOWN")}),
        site_maps=_Maps(), tracking=_Tracking(), zones=lambda: {"roundabout": (tuple(ZONES), 1)},
        clock=lambda: now[0])
    first = asyncio.run(service.view())
    assert first["map_version"] == 3 and first["camera"] == "ceiling_north"
    rows = {r["robot_id"]: r for r in first["robots"]}
    assert _codes(rows["rosy_26"]) == [] and _codes(rows["rosy_60"]) == ["CAMERA_NOT_SEEING"]
    assert rows["rosy_60"]["findings"][0]["action"]["kind"] == "identify"  # D-596: a blob is anonymous
    assert rows["rosy_60"]["worst"] == "warn" and rows["rosy_26"]["worst"] is None
    now[0] += 11.0
    rows = {r["robot_id"]: r for r in asyncio.run(service.view())["robots"]}
    assert _codes(rows["rosy_26"]) == ["STOPPED_IN_ZONE"] and rows["rosy_26"]["worst"] == "crit"


def test_guide_route_is_read_only_and_needs_a_viewer(tmp_path):
    from test_trip_runner import VIEWER, Ports, _app

    client, *_rest = _app(tmp_path, Ports())
    assert client.get("/api/fleet/guide").status_code in (401, 403)
    body = client.get("/api/fleet/guide", headers=VIEWER).json()
    assert set(body) == {"map_version", "camera", "robots"}
    for row in body["robots"]:
        assert {"robot_id", "online", "body_radius_m", "pose", "lane", "findings", "worst"} <= set(row)
    assert client.post("/api/fleet/guide", headers=VIEWER).status_code == 405
