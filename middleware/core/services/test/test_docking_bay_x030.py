"""b8xy C2 at x 0.214 (real scans, 2026-11-21): the LiDAR says straight in the lane, the camera heading lies by ~9 deg: the zone verdict must follow the LiDAR."""

from __future__ import annotations

import json
import math
from pathlib import Path

from core_common.robot_body import PINKY_PRO
from core_features.docking.bay_scan_pose import locate
from core_features.docking.bay_zone import classify, lane_edge, lane_extent, scan_geometry
from core_features.docking.detector import DockObservation
from core_features.docking.model import DockingConfig

DATA = json.loads((Path(__file__).parent / "data_b8xy_c2_x0214.json").read_text())
CFG = DockingConfig()


class _Dock:
    metadata: dict = {}


def _camera(along, lateral, heading):
    yaw = math.pi - heading
    ax, ay = math.cos(yaw), math.sin(yaw)
    return DockObservation(x=along * ax + lateral * ay, y=along * ay - lateral * ax, yaw=yaw, confidence=1.0, at=0.0)


def _pose():
    ref = PINKY_PRO.scan_view(DATA["seat_reference"], forward_deg=180.0).points
    live = PINKY_PRO.scan_view(DATA["live_x0214"], forward_deg=180.0).points
    return locate(ref, live)


def test_the_real_scan_at_x_0214_is_a_good_pose_straight_inside_the_lane():
    m = _pose()
    assert m.x == __import__("pytest").approx(0.2137, abs=0.01) and abs(m.y) < 0.012 and abs(m.heading) < math.radians(2.0)
    assert m.inliers >= CFG.bay_scan_inlier_min and m.margin >= CFG.bay_scan_margin_min
    geo = scan_geometry(m, 0.32, CFG)
    assert geo is not None and lane_extent(CFG, geo[1], geo[2]) < lane_edge(CFG)


def test_a_camera_heading_that_is_9_deg_off_does_not_refuse_a_robot_the_lidar_sees_straight():
    geo = scan_geometry(_pose(), 0.32, CFG)
    for lateral, heading in ((-0.015, math.radians(-9.2)), (-0.006, math.radians(-6.1)), (0.0, math.radians(-8.5))):
        verdict = classify(None, _Dock(), 0.32, _camera(geo[0], lateral, heading), CFG, geo)
        assert verdict.kind == "acquire", (lateral, heading, verdict)


def test_a_camera_that_disagrees_beyond_the_gate_still_stops_it_and_a_lidar_skew_still_fails_the_footprint():
    geo = scan_geometry(_pose(), 0.32, CFG)
    assert classify(None, _Dock(), 0.32, _camera(geo[0], 0.0, math.radians(-25.0)), CFG, geo).kind == "manual"      # camera vs LiDAR > 10 deg
    skewed = (geo[0], 0.03, math.radians(12.0))                                                                       # LiDAR says skewed 12 deg, 3 cm off
    verdict = classify(None, _Dock(), 0.32, _camera(skewed[0], 0.03, math.radians(12.0)), CFG, skewed)
    assert verdict.kind != "acquire"