#!/usr/bin/env python3
"""B8 replay (laptop, no ROS): recorded SIM frames through the product LaneKeeper.

  PYTHONPATH=middleware/perception:contracts/foundation python b8_replay.py <run>

Same keeper settings as the D-495 SIM line_observer: camera_x_offset_m 0.03317 (payload
line_follow.yaml), corner_turning on, lane_half_width_m 0.0925, GAZEBO ground (height 0.06343,
pitch 8 deg, hfov 2 atan(160/281.6), max range 0.6). Reports how many frames reproduce the
live bundle's strategy/reason and error. The keeper resets on a camera gap > its frame gap,
as the node does."""
import json
import math
import os
import sys

import numpy as np

from control.sensing.perception.camera_ground import simulation_ground_plane
from control.sensing.perception.lane_keep import LaneKeeper
KEEP_MAX_FRAME_GAP_S = 0.5  # line_observer_node.py (it imports rclpy, so copied here)


def ground(w, h):
    return simulation_ground_plane(source='GAZEBO', simulation_enabled=True, use_sim_time=True,
                                   width_px=w, height_px=h, height_m=0.06343,
                                   pitch_rad=math.radians(8.0),
                                   hfov_rad=2.0 * math.atan(160.0 / 281.6), max_range_m=0.6)


def replay(run):
    rec = np.load(os.path.join(run, 'rec', 'frames.npz'))
    live = {round(json.loads(l)['stamp'], 3): json.loads(l)
            for l in open(os.path.join(run, 'rec', 'keep.jsonl'))}
    k = LaneKeeper(camera_x_offset_m=0.03317, corner_turning=True)
    g = ground(rec['frames'].shape[2], rec['frames'].shape[1])
    last, same, n, out = None, 0, 0, []
    for f, s in zip(rec['frames'], rec['stamp']):
        if last is None or not 0.0 <= s - last <= KEEP_MAX_FRAME_GAP_S:
            k.reset()
        last = s
        k.update(f, g, lane_half_width_m=0.0925)
        mine = (k.last.get('strategy'), k.last.get('reason'), k.last.get('error'))
        b = live.get(round(float(s), 3))
        if b is not None:
            n += 1
            same += mine == (b.get('strategy'), b.get('reason'), b.get('error'))
        out.append(mine)
    return n, same, out


if __name__ == '__main__':
    n, same, _ = replay(sys.argv[1])
    print(f'{sys.argv[1]}: {same}/{n} frames reproduce the live keeper bundle')
