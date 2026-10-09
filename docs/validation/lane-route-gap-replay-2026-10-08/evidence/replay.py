#!/usr/bin/env python3
"""Replay the saved ROS-SIM blind bend with and without a route pose error."""
import argparse
import copy
import json
import math
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "contracts/foundation"), str(ROOT / "middleware/perception")]
from control.sensing.perception.camera_ground import simulation_ground_plane  # noqa: E402
from control.sensing.perception.route_camera import RouteCameraFollower  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("frames_npz")
    args = parser.parse_args()
    frames = np.load(args.frames_npz)
    if len(frames["stamp"]) <= 192:
        raise ValueError("expected the 226-frame guard1 recording")
    graph = yaml.safe_load((ROOT / "middleware/perception/map/map_v2_fleet/lane_graph.yaml")
                           .read_text(encoding="utf-8"))
    ground = simulation_ground_plane(
        source="GAZEBO", simulation_enabled=True, use_sim_time=True,
        width_px=320, height_px=240, height_m=0.06343,
        pitch_rad=math.radians(8), hfov_rad=2 * math.atan(160 / 281.6),
        max_range_m=0.6)
    subject = RouteCameraFollower(
        graph, ["west:r", "ring_s:f"], start_pose=tuple(frames["gt"][76]),
        camera_x_offset_m=0.03317)
    kwargs = dict(lane_half_width_m=0.0925, bright_threshold=180,
                  roi_top_fraction=0.4, roi_bottom_fraction=1.0,
                  washed_fraction=0.4)
    for i in range(76, 192):
        subject.update(float(frames["stamp"][i]), tuple(frames["gt"][i]),
                       frames["frames"][i], ground, **kwargs)
    pose = tuple(float(v) for v in frames["gt"][192])
    heading = subject._fix.heading
    off_route = (pose[0] - 0.08 * math.sin(heading),
                 pose[1] + 0.08 * math.cos(heading), pose[2])
    result = {}
    for name, candidate in (("recorded", pose), ("lateral_80mm", off_route)):
        follower = copy.deepcopy(subject)
        output = follower.update(float(frames["stamp"][192]), candidate,
                                 frames["frames"][192], ground, **kwargs)
        result[name] = {"output": output is not None, "state": follower.state,
                        "camera_tier": follower.last["camera_tier"],
                        "fix_lateral_m": round(follower._fix.lateral_m, 4)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
