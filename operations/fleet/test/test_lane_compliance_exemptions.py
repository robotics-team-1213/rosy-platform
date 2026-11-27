"""D-1084: the lane watch judges moving robots on road edges only, and a departure needs the camera pose
and the robot's bound SLAM pose to agree. Cases are the Fleet R readings of 2026-11-27 16:44Z."""

import asyncio
import math

from core_common.robot_body import PINKY_PRO
from fleet.guide.situation import situation
from fleet.localization.lane_compliance import (ACT, OFF_LANE, OK, ON_LANE, PARKING, POSE_MISMATCH,
                                                LaneComplianceConfig, evaluate_bay_dock)
from fleet.localization.lane_compliance_helpers import parking_edge
from fleet.localization.map_binding import Fit
from fleet.routing.graph import build_graph
from fleet.server.lane_compliance_service import LaneComplianceMonitor
from fleet.site_map import SiteMap
from rosy.world.state.projections.map_pose import MapPose

# A road A->B (0.3 m) and the world_261026 parking corner: P1/P2 kind park, C2 kind charge. The guide bar
# is named "guide_21" on purpose: the place kinds, not the bar_ prefix, make it a parking edge.
SITE = {
    "map_id": "site_v1",
    "places": [{"id": "A", "name": "A", "x": 0, "y": 0, "kind": "junction"},
               {"id": "B", "name": "B", "x": 2, "y": 0, "kind": "junction"},
               {"id": "P1", "name": "P1", "x": 0.0, "y": 1.0, "kind": "park"},
               {"id": "P2", "name": "P2", "x": 0.5, "y": 1.0, "kind": "park"},
               {"id": "C2", "name": "C2", "x": 0.5, "y": 1.5, "kind": "charge"}],
    "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [2, 0]], "width_m": 0.3,
               "speed_cap_mps": 0.2},
              {"id": "bay_2", "from": "P2", "to": "C2", "polyline": [[0.5, 1.0], [0.5, 1.5]], "width_m": 0.18,
               "direction": "two_way", "speed_cap_mps": 0.05},
              {"id": "guide_21", "from": "P2", "to": "P1", "polyline": [[0.5, 1.0], [0.0, 1.0]], "width_m": 0.15,
               "speed_cap_mps": 0.05}]}
GRAPH = build_graph(SiteMap.model_validate(SITE))
FIT = Fit(yaw=0.2, tx=0.3, ty=-0.2, residuals=(0.0,))


def cam(x, y, yaw):
    return MapPose(x, y, yaw, "LOCALIZED", "sighting", 0.0, 0.1, map_id="site_v1", odom_stamp=5.0)


def slam_state(x, y, yaw, now):
    from datetime import datetime, timezone
    rx, ry = FIT.inverse((x, y))
    return {"map_id": "native", "map_grid_id": "occupancy:abc", "pose_frame": "map", "mode": "IDLE",
            "localization": {"state": "LOCALIZED", "pose_frame": "map"},
            "pose": {"x": rx, "y": ry, "yaw": yaw - FIT.yaw},
            "odom_pose": {"x": rx, "y": ry, "yaw": yaw - FIT.yaw, "stamp": now - 0.1},
            "evidence": {"pose": {"evidence": "fresh",
                                  "received_at": datetime.fromtimestamp(now - 0.1, timezone.utc).isoformat()}}}


class Poses:
    def __init__(self, poses, moving=(), slam=None, clock=None):
        self.poses, self.moving, self.slam, self.clock = poses, set(moving), slam or {}, clock

    def moved(self, robot_id, *_):
        return robot_id in self.moving

    async def refresh(self, *_a, **_k):
        return None

    def arbitrated_pose(self, robot_id):
        return self.poses.get(robot_id)

    def cached_motion_sample(self, robot_id):
        pose = self.slam.get(robot_id)
        return None if pose is None else (slam_state(*pose, self.clock[0]), 0.0, 0.0)


class Maps:
    def active(self):
        return (7, None, GRAPH, None)


class Client:
    def __init__(self):
        self.sent = []

    async def line_follow_lane_cue(self, body):
        self.sent.append(body)
        return {"accepted": True}


def _store(tmp_path, robot_ids):
    from fleet.server.site_map_store import SiteMapStore
    store = SiteMapStore(tmp_path / "maps.sqlite3")
    version = store.import_if_empty(SiteMap.model_validate(SITE), source="test")
    pairs = [{"site": list(p), "robot": list(FIT.inverse(p))} for p in [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]]
    holdout = [{"site": [0.5, 0.5], "robot": list(FIT.inverse((0.5, 0.5)))}]
    for robot_id in robot_ids:
        store.map_bindings.approve(robot_id, slam_state(1.0, 0.0, 0.0, 1_700_000_100.0),
                                   ("site_v1", version), pairs, holdout, "bob")
    return store


def _run(monitor, clock, n):
    for _ in range(n):
        asyncio.run(monitor.tick())
        clock[0] += 0.5


def test_parking_edges_come_from_place_kinds():
    assert parking_edge(GRAPH, "bay_2") and parking_edge(GRAPH, "guide_21")
    assert not parking_edge(GRAPH, "ab") and not parking_edge(GRAPH, None)


def test_still_robots_at_the_bays_and_on_the_guide_bar_raise_nothing():
    # rosy_42 on the C2 entry line (offset -0.065), rosy_45 on the guide bar (+0.036, heading -14 deg against
    # a 180 deg lane), rosy_47 parked inside C2; rosy_44 still but over a road edge. All idle: no WARN/ACT,
    # no "차선 위" return, no lane cue, and the counts never grow.
    clock, client = [100.0], Client()
    poses = Poses({"rosy_42": cam(0.565, 1.25, math.pi / 2), "rosy_45": cam(0.25, 0.964, math.radians(-14)),
                   "rosy_47": cam(0.5, 1.45, math.pi / 2), "rosy_44": cam(1.0, 0.15, 0.0)})
    monitor = LaneComplianceMonitor(lambda: list(poses.poses), poses=poses, site_maps=Maps(),
                                    config=LaneComplianceConfig(persist_n=1), wall=lambda: clock[0],
                                    clients=lambda: {r: client for r in poses.poses})
    _run(monitor, clock, 6)
    for robot_id in ("rosy_42", "rosy_45", "rosy_47"):
        view = monitor.view(robot_id)
        assert view["level"] == OK and (view["warn_count"], view["act_count"]) == (0, 0), robot_id
        assert view["exempt"] == "parking" and view["return"]["state"] == PARKING, robot_id
    road = monitor.view("rosy_44")
    assert road["margin_m"] < 0 and road["level"] == OK and road["exempt"] == "still" and road["act_count"] == 0
    assert all(body["state"] == ON_LANE and body.get("side") is None for body in client.sent)


def test_counts_do_not_grow_while_still_and_act_needs_motion():
    clock = [100.0]
    poses = Poses({"r": cam(1.0, 0.15, 0.0)}, moving={"r"})
    monitor = LaneComplianceMonitor(lambda: ["r"], poses=poses, site_maps=Maps(),
                                    config=LaneComplianceConfig(persist_n=3), wall=lambda: clock[0])
    _run(monitor, clock, 2)
    assert monitor.view("r")["act_count"] == 2 and monitor.view("r")["level"] == OK
    poses.moving.clear()
    _run(monitor, clock, 5)
    assert (monitor.view("r")["act_count"], monitor.view("r")["level"]) == (2, OK)
    poses.moving.add("r")
    _run(monitor, clock, 1)
    view = monitor.view("r")      # camera alone, no binding: judged as before, the reason recorded
    assert (view["act_count"], view["level"], view["body_pose_reason"]) == (3, ACT, "no_binding")


def test_moving_off_lane_is_act_only_when_camera_and_slam_agree(tmp_path):
    clock, client = [1_700_000_100.0], Client()
    poses = Poses({"both": cam(1.0, 0.25, 0.0), "camera": cam(1.0, 0.25, 0.0)}, moving={"both", "camera"},
                  slam={"both": (1.0, 0.26, 0.0), "camera": (1.0, 0.0, 0.0)}, clock=clock)
    monitor = LaneComplianceMonitor(lambda: ["both", "camera"], poses=poses,
                                    site_maps=_store(tmp_path, ["both", "camera"]),
                                    config=LaneComplianceConfig(persist_n=1, return_persist_s=0.0),
                                    wall=lambda: clock[0], clients=lambda: {"both": client, "camera": client})
    _run(monitor, clock, 3)
    both = monitor.view("both")
    assert both["level"] == ACT and both["return"]["state"] == OFF_LANE and both["pose_mismatch"] is None
    assert both["body_pose"]["source"] == "approved_slam" and both["yaw_source"] == "body"
    one = monitor.view("camera")
    assert one["level"] == OK and one["return"]["state"] == POSE_MISMATCH
    assert one["pose_mismatch"]["camera_margin_m"] < 0 <= one["pose_mismatch"]["body_margin_m"]
    assert abs(one["pose_mismatch"]["gap_m"] - 0.25) < 1e-3 and one["return"]["pose_gap_m"] == one["pose_gap_m"]
    sent = {body["cue_id"].split("-")[0]: body for body in client.sent}
    assert sent["both"]["state"] == OFF_LANE and sent["camera"]["state"] == ON_LANE


def test_body_yaw_decides_the_side_and_the_bay_verdict_keeps_the_camera_input(tmp_path):
    clock, client = [1_700_000_100.0], Client()
    # Backing into C2: the ceiling yaw is 8 deg off (north bays), the robot's own yaw is right.
    camera = cam(0.5, 1.3, -math.pi / 2 + math.radians(8))
    poses = Poses({"r": camera}, moving={"r"}, slam={"r": (0.5, 1.3, -math.pi / 2)}, clock=clock)
    monitor = LaneComplianceMonitor(lambda: ["r"], poses=poses, site_maps=_store(tmp_path, ["r"]),
                                    config=LaneComplianceConfig(return_persist_s=0.0), wall=lambda: clock[0],
                                    clients=lambda: {"r": client})
    _run(monitor, clock, 2)
    view = monitor.view("r")
    assert view["exempt"] == "parking" and view["return"]["state"] == PARKING
    assert view["return"]["docking"] == evaluate_bay_dock(camera.x, camera.y, camera.yaw, None, GRAPH)
    assert client.sent[-1]["docking"] == view["return"]["docking"] and client.sent[-1]["state"] == ON_LANE


def test_docking_mode_and_parking_handoff_are_parking():
    clock = [100.0]
    poses = Poses({"r": cam(1.0, 0.15, 0.0)}, moving={"r"})
    monitor = LaneComplianceMonitor(lambda: ["r"], poses=poses, site_maps=Maps(),
                                    config=LaneComplianceConfig(persist_n=1), wall=lambda: clock[0])
    monitor.parking_handoff = lambda robot_id: True
    _run(monitor, clock, 3)
    assert monitor.view("r")["exempt"] == "parking" and monitor.view("r")["level"] == OK


def _guide(pose, watch, stopped_s=0.0):
    return situation("rosy_45", online=True, pose=pose, tracking_row=None, camera_ok=None, graph=GRAPH,
                     zone_of={}, body_radius_m=PINKY_PRO.rotation_radius_m,
                     body_half_width_m=PINKY_PRO.half_width_m, stopped_s=stopped_s, lane_watch=watch)


def _codes(record):
    return {f["code"]: f["severity"] for f in record["findings"]}


def test_guide_findings_follow_the_lane_watch():
    off_road = cam(1.0, -0.25, math.pi)                        # off the road and facing against it
    moving = {"moving": True, "exempt": None, "pose_mismatch": None, "body_pose": None}
    assert {"OFF_LANE", "WRONG_WAY"} <= set(_codes(_guide(off_road, moving)))
    assert not {"OFF_LANE", "WRONG_WAY"} & set(_codes(_guide(off_road, {**moving, "moving": False})))
    assert not {"OFF_LANE", "WRONG_WAY"} & set(_codes(_guide(off_road, None, stopped_s=4.0)))
    mismatch = _codes(_guide(off_road, {**moving, "pose_mismatch": {"gap_m": 0.05}}))
    assert mismatch.get("POSE_MISMATCH") == "info" and "OFF_LANE" not in mismatch
    turned = _codes(_guide(off_road, {**moving, "body_pose": {"x": 1.0, "y": -0.25, "yaw": 0.0}}))
    assert "WRONG_WAY" not in turned and "OFF_LANE" in turned      # the robot's own yaw goes the lane's way
    parked = _codes(_guide(cam(0.25, 0.964, math.radians(-14)), {**moving, "moving": False, "exempt": "parking"}))
    assert parked == {"PARKING": "info"}
