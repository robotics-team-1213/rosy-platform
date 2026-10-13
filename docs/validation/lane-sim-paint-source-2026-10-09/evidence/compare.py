"""Compare threshold paint with map-projected paint on the fixed B8 SIM frames.

The projection uses GT pose and a flat floor. It does not model wall occlusion
and is a diagnostic paint source, not a real-camera label or driving oracle.
"""

import collections
import json
import math
from pathlib import Path

import numpy as np

from control.sensing.perception.camera_ground import simulation_ground_plane
from control.sensing.perception.lane_bev import BirdsEye
from control.sensing.perception.lane_keep import LaneKeeper
from control.sensing.perception.lane_keep_lines import floor_white_mask
from control.sensing.perception.paint_localizer import PaintMap


REPO = Path(__file__).resolve().parents[4]
FIXTURE = REPO / "docs/validation/lane-trip-perception-2026-10-07/fixtures/b8_keeper_clips.npz"
CAMERA_X = 0.03317
HALF = 0.0925


def projected_paint(paint, ground, pose):
    rows, cols = np.indices((240, 320), dtype=float)
    angle = ground.pitch_rad + np.arctan((rows - ground.principal_y) / ground.focal_px)
    with np.errstate(divide="ignore", invalid="ignore"):
        forward = ground.height_m / np.tan(angle) + CAMERA_X
        denominator = (ground.focal_px * math.sin(ground.pitch_rad)
                       + (rows - ground.principal_y) * math.cos(ground.pitch_rad))
        left = -ground.height_m * (cols - ground.principal_x) / denominator
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    wx, wy = x + forward * c - left * s, y + forward * s + left * c
    map_row = np.rint((paint.y1 - wy) / paint.raster_m).astype(np.int64)
    map_col = np.rint((wx - paint.x0) / paint.raster_m).astype(np.int64)
    valid = (angle > 0) & np.isfinite(forward) & np.isfinite(left)
    valid &= (forward > CAMERA_X) & (forward <= ground.max_range_m + CAMERA_X)
    valid &= ((map_row >= 0) & (map_row < paint.paint.shape[0])
              & (map_col >= 0) & (map_col < paint.paint.shape[1]))
    mask = np.zeros((240, 320), np.uint8)
    mask[valid] = paint.paint[map_row[valid], map_col[valid]]
    return mask


def run():
    data = np.load(FIXTURE)
    frames, meta = data["frames"], json.loads(str(data["meta"]))
    assert frames.shape == (89, 240, 320, 3) and len(meta) == 89
    paint = PaintMap.from_bundle()
    ground = simulation_ground_plane(
        source="GAZEBO", simulation_enabled=True, use_sim_time=True,
        width_px=320, height_px=240, height_m=0.06343, pitch_rad=math.radians(8),
        hfov_rad=2 * math.atan(160 / 281.6), max_range_m=0.6)
    view = BirdsEye(ground, 320, 240, CAMERA_X)
    keepers = {source: {} for source in ("threshold", "map_projection")}
    by_clip = collections.defaultdict(list)
    for index, (frame, item) in enumerate(zip(frames, meta)):
        clip = item["clip"]
        mask = projected_paint(paint, ground, item["gt"])
        observed = view.sample(floor_white_mask(frame, ground.horizon_row)) > 0
        projected = view.sample(mask) > 0
        union = (observed | projected).sum()
        iou = float((observed & projected).sum() / union) if union else None
        decisions = {}
        for source in keepers:
            keeper = keepers[source].setdefault(
                clip, LaneKeeper(camera_x_offset_m=CAMERA_X, corner_turning=True))
            keeper.update(frame, ground, lane_half_width_m=HALF,
                          paint_mask=mask if source == "map_projection" else None,
                          bend_expected=True)
            last = keeper.last
            decisions[source] = {"strategy": last["strategy"],
                                 "reason": last.get("reason"),
                                 "drive": last["target_m"] is not None,
                                 "boundaries": [{"side": b["side"], "length_m": b["length_m"]}
                                                for b in last["boundaries"]]}
        by_clip[clip].append({"index": index, "bev_iou": iou, **decisions})
    result = {}
    for clip, rows in sorted(by_clip.items()):
        result[clip] = {
            "frames": len(rows),
            "bev_iou_median": round(float(np.median([r["bev_iou"] for r in rows])), 3),
            "strategies": {source: dict(collections.Counter(r[source]["strategy"] for r in rows))
                           for source in keepers},
            "threshold_drive_map_hold": [r["index"] for r in rows
                                         if r["threshold"]["drive"] and not r["map_projection"]["drive"]],
            "threshold_hold_map_drive": [r["index"] for r in rows
                                         if not r["threshold"]["drive"] and r["map_projection"]["drive"]],
        }
    assert sum(r["frames"] for r in result.values()) == 89
    assert result["south_centre_lost"]["threshold_drive_map_hold"] == list(range(15, 21))
    assert result["bend_fork"]["threshold_drive_map_hold"] == []
    return result


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
