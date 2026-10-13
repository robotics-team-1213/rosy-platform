"""Host closed loop: rendered LaneKeeper evidence into the real CORE manager.

The robot, IR and LiDAR are synthetic. This script emits diagnostics only; it
does not use ROS, Fleet, a motor driver, or any device connection.
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
for relative in ("contracts/foundation", "middleware/perception",
                 "middleware/perception/test", "middleware/core/services",
                 "middleware/core/services/test"):
    sys.path.insert(0, str(ROOT / relative))

import numpy as np  # noqa: E402
import cv2  # noqa: E402

from control.sensing.perception.lane_keep import LaneKeeper  # noqa: E402
from core_features.line_follow.model import LineFollowMode, LineObservation  # noqa: E402
from lane_sim import CAM_X, GROUND, H, LW, distance_to_polyline, lane, offset_polyline  # noqa: E402
from test_junction_turn_site_basis import CLEAR, SITE, site_rig  # noqa: E402

DT = 0.2
TURN_DEG = 65.0
START = (-0.3, 0.0, 0.0)
VERTEX_X = 0.45
BEND_RADIUS_M = 0.15
# Tangent point of the fillet before a 65-degree vertex.
BEND_IN_M = VERTEX_X - BEND_RADIUS_M * math.tan(math.radians(TURN_DEG) / 2) - START[0]
BODY_CENTRE_ALLOWANCE_M = H - LW / 2 - SITE["body_half_width_m"]
BODY_X, BODY_Y = np.meshgrid(
    np.arange(SITE["body_rear_x_m"], SITE["body_front_x_m"] + 0.0005, 0.001),
    np.arange(-SITE["body_half_width_m"], SITE["body_half_width_m"] + 0.0005, 0.001))


def footprint_indices(world, pose):
    """Sample the declared body rectangle against the world raster at 1 mm."""
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    wx = x + BODY_X * c - BODY_Y * s
    wy = y + BODY_X * s + BODY_Y * c
    col = np.rint((wx - world.x0) * 1000).astype(int)
    row = np.rint((world.y1 - wy) * 1000).astype(int)
    inside = ((0 <= row) & (row < world.paint.shape[0])
              & (0 <= col) & (col < world.paint.shape[1]))
    return row, col, inside


def run(with_bend):
    turn = math.radians(TURN_DEG)
    centre = np.array([[-1.0, 0.0], [VERTEX_X, 0.0],
                       [VERTEX_X + 1.2 * math.cos(turn), 1.2 * math.sin(turn)]])
    world = lane(centre)
    corridor = np.zeros_like(world.paint)
    polygon = np.vstack((offset_polyline(centre, H), offset_polyline(centre, -H)[::-1]))
    cv2.fillPoly(corridor, [np.rint(world.px(polygon) * 16).astype(np.int32)], 1, shift=4)
    corridor[world.paint > 0] = 0  # the white tape is not traversable floor
    rig = site_rig(**SITE)
    rig.x, rig.y, rig.yaw = START
    keeper = LaneKeeper(camera_x_offset_m=CAM_X, corner_turning=True)
    rows = []
    for step in range(160):
        rig.now = round(rig.now + DT, 6)
        stamp = round(rig.now * 1e9)
        rig.m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame="odom",
                                  x=rig.x, y=rig.y, yaw=rig.yaw, received_at=rig.now)
        rig.m.observe_scan_points(CLEAR, received_at=rig.now)
        rig.m.observe(LineObservation(LineFollowMode.IR_LINE, rig.now, False, None, 0.0,
                                      ir_calibrated=True, calibration_revision="r"),
                      received_at=rig.now)
        observation = keeper.update(world.render((rig.x, rig.y, rig.yaw)), GROUND,
                                    lane_half_width_m=H, bend_expected=False)
        rig.m.observe(LineObservation(LineFollowMode.CAMERA_LINE, rig.now,
                                      observation is not None,
                                      None if observation is None else observation.error,
                                      0.0 if observation is None else observation.confidence),
                      received_at=rig.now)
        if with_bend and step == 1:
            accepted = rig.m.set_junction(
                "bend", "B1", 30.0, None, TURN_DEG, None,
                expect={"map_id": "lab-a", "bend_in_m": BEND_IN_M,
                        "bend_tol_m": 0.12, "bend_radius_m": BEND_RADIUS_M})
            if accepted != (True, 1, "armed"):
                raise AssertionError(f"bend instruction rejected: {accepted}")
        decision = rig.m.tick(rig.now)
        status = rig.m.status()
        row, col, inside = footprint_indices(world, (rig.x, rig.y, rig.yaw))
        paint_cells = int(np.count_nonzero(world.paint[row[inside], col[inside]]))
        outside_cells = int(np.count_nonzero(~inside) + np.count_nonzero(
            corridor[row[inside], col[inside]] == 0))
        rows.append({"step": step, "pose": [rig.x, rig.y, rig.yaw],
                     "strategy": keeper.last.get("strategy"), "keep_reason": keeper.last.get("reason"),
                     "junction_state": status.junction.state, "core_reason": status.reason,
                     "linear": decision.linear, "angular": decision.angular,
                     "footprint_paint_cells": paint_cells, "footprint_outside_cells": outside_cells,
                     "centre_deviation_m": distance_to_polyline((rig.x, rig.y), centre)})
        middle = rig.yaw + decision.angular * DT / 2
        rig.x += decision.linear * DT * math.cos(middle)
        rig.y += decision.linear * DT * math.sin(middle)
        rig.yaw += decision.angular * DT
        if status.junction.state in ("aborted", "unresolved") or (with_bend and step > 1
                and status.junction.state == "idle"):
            break
    final = rows[-1]
    return {"instruction": "bend" if with_bend else "none", "steps": len(rows),
            "handoff": next((r for r in rows if r["junction_state"] == "bending"), None),
            "first_keep_stop": next((r for r in rows if r["strategy"] == "none"), None),
            "first_footprint_paint": next((r for r in rows if r["footprint_paint_cells"]), None),
            "paint_contact_ticks": sum(bool(r["footprint_paint_cells"]) for r in rows),
            "max_footprint_paint_cells": max(r["footprint_paint_cells"] for r in rows),
            "first_footprint_outside": next((r for r in rows if r["footprint_outside_cells"]), None),
            "outside_ticks": sum(bool(r["footprint_outside_cells"]) for r in rows),
            "max_footprint_outside_cells": max(r["footprint_outside_cells"] for r in rows),
            "final": final, "max_centre_deviation_m": max(r["centre_deviation_m"] for r in rows),
            "body_centre_allowance_m": BODY_CENTRE_ALLOWANCE_M,
            "centre_allowance_exceeded": any(r["centre_deviation_m"] > BODY_CENTRE_ALLOWANCE_M
                                              for r in rows)}


def main():
    without = run(False)
    with_bend = run(True)
    assert without["first_keep_stop"] is not None
    assert without["final"]["linear"] == 0.0
    assert with_bend["handoff"] is not None
    assert with_bend["final"]["junction_state"] == "idle"
    print(json.dumps({"scene": "65-degree left bend, 1 mm paint raster, synthetic clear IR and LiDAR",
                      "dt_s": DT, "bend_in_m": BEND_IN_M,
                      "without_bend": without, "with_bend": with_bend}, indent=2))


if __name__ == "__main__":
    main()
