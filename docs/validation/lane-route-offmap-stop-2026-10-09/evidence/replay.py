"""Shadow-only route_a replay on B9 camera/GT frames; never publishes motion."""
import copy
import json
import math
import sys
from pathlib import Path

import numpy as np
import yaml
import cv2

if len(sys.argv) != 2:
    raise SystemExit("usage: python replay.py <isolated-workspace-with-src-and-b9runs>")
root = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(root / "src/rosy-platform/contracts/foundation"),
                str(root / "src/rosy-platform/middleware/perception")]
from control.sensing.perception.camera_ground import simulation_ground_plane
from control.sensing.perception.route_camera import RouteCameraFollower
from control.sensing.perception.lane_debug import render_debug

graph = yaml.safe_load((root / "src/rosy-platform/middleware/perception/map/map_v2_fleet/lane_graph.yaml")
                       .read_text())
ground = simulation_ground_plane(source="GAZEBO", simulation_enabled=True,
                                 use_sim_time=True, width_px=320, height_px=240,
                                 height_m=0.06343, pitch_rad=math.radians(8),
                                 hfov_rad=2 * math.atan(160 / 281.6), max_range_m=0.6)
kwargs = dict(lane_half_width_m=0.0925, bright_threshold=180,
              roi_top_fraction=0.4, roi_bottom_fraction=1.0,
              washed_fraction=0.4)

for name in ("base1", "base2"):
    with np.load(root / "b9runs" / name / "rec/frames.npz") as data:
        stamps, poses, images = (data[k].copy() for k in ("stamp", "gt", "frames"))
    valid = [i for i, (t, pose) in enumerate(zip(stamps, poses))
             if t >= (72 if name == "base1" else 119) and np.isfinite(pose).all()]
    assert len(valid) > 150 and np.all(np.diff(stamps) >= 0)
    follower = RouteCameraFollower(graph, ["west:r", "ring_s:f"],
                                   start_pose=tuple(poses[valid[0]]),
                                   camera_x_offset_m=0.03317)
    rows = []
    for i in valid:
        t = float(stamps[i])
        prior_t, target_t = ((95.375, 95.5) if name == "base1"
                             else (142.25, 142.375))
        if abs(t - target_t) < 0.001:
            assert abs(float(stamps[i - 1]) - prior_t) < 0.001
            actual = tuple(float(v) for v in poses[i])
            frozen = tuple(float(v) for v in poses[i - 1])
            heading = follower._fix.heading
            offroute = (actual[0] - 0.08 * math.sin(heading),
                        actual[1] + 0.08 * math.cos(heading), actual[2])
            for label, pose in (("actual", actual), ("frozen", frozen),
                                ("offroute80", offroute), ("stale", None)):
                probe = copy.deepcopy(follower)
                candidate = probe.update(t, pose, images[i], ground, **kwargs)
                print("counterfactual", name, label,
                      "out", candidate is not None, "tier", probe.tier,
                      "camera", probe.last.get("camera_tier"),
                      "near_node", probe.last.get("near_node"),
                      "lateral", None if probe._fix is None else
                      round(float(probe._fix.lateral_m), 4))
        out = follower.update(t, tuple(poses[i]), images[i], ground, **kwargs)
        fix = follower._fix
        targets = (95.5, 97.0, 99.125) if name == "base1" else (142.375, 144.0, 145.875)
        if any(abs(t - chosen) < 0.001 for chosen in targets):
            cv2.imwrite(str(root / f"{name}-shadow-{t:.3f}.png"),
                        render_debug(images[i], follower, out, mode="route_a shadow",
                                     pose=tuple(poses[i]), graph=graph))
            print("snapshot", name, t, "camera", follower.last.get("camera_tier"),
                  "source", follower.last.get("tracker", {}).get("source"),
                  "fresh_length", follower.last.get("tracker", {}).get("fresh_length"),
                  "target", follower.last.get("tracker", {}).get("target"))
        rows.append(dict(t=round(t, 3), tier=follower.tier,
                         output=out is not None,
                         lateral=None if fix is None else round(float(fix.lateral_m), 4),
                         near_node=follower.last.get("near_node"),
                         camera_tier=follower.last.get("camera_tier")))
    print(name, "start", valid[0], poses[valid[0]].round(3).tolist(),
          "tiers", {tier: sum(x["tier"] == tier for x in rows)
                    for tier in sorted(set(x["tier"] for x in rows))})
    window = (95.25, 99.375) if name == "base1" else (142.0, 146.125)
    print(json.dumps([x for x in rows if window[0] <= x["t"] <= window[1]], indent=2))
