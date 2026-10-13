#!/usr/bin/env python3
"""Cut B8 SIM recordings into small keeper fixture clips (laptop, no ROS).

  PYTHONPATH=middleware/perception:contracts/foundation \
    python b8_fixtures.py <runs dir> <out.npz>

Each clip is a run of consecutive camera frames (8 Hz) ending a few frames after the first
keeper bundle that matches the clip's event, so a test can replay it from LaneKeeper.reset()
with the D-495 SIM keeper settings (b8_replay.ground, camera_x_offset_m 0.03317, corner
turning on, half-width 0.0925). Stored per frame: BGR frame, image stamp, ground-truth pose
(x, y, yaw in the map frame), and the live keeper's strategy / reason / error.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from b8_analyze import CENTRE_Y  # noqa: E402

# (clip, run, event predicate on (bundle, gt), frames before, frames after)
CLIPS = (
    ('south_centre_straight', 'south_c1',
     lambda b, g: g[0] >= -1.10 and abs(g[2]) < 0.1 and abs(g[1] - CENTRE_Y) < 0.01, 0, 12),
    ('south_centre_lost', 'south_c1',
     lambda b, g: b.get('reason') == 'no_boundary' and g[0] > -0.95, 8, 2),
    ('corner_exit_offset', 'bend_9',
     lambda b, g: g[0] >= -1.20 and g[1] < -0.40 and abs(g[2]) < 0.3, 0, 12),
    ('premature_corner_left', 'bend_9',
     lambda b, g: b.get('strategy') == 'corner_left' and g[0] > -1.0, 4, 8),
    ('bend_flipping', 'bend_9',
     lambda b, g: b.get('reason') == 'flipping' and g[0] > -0.86, 18, 2),
    ('bend_fork', 'bend_10',
     lambda b, g: b.get('reason') == 'junction_fork' and g[0] > -0.86, 6, 4),
    ('spoke_transverse', 'bend_15',
     lambda b, g: b.get('reason') == 'junction_transverse' and g[0] > -0.86, 4, 2),
)


def main():
    runs, out = sys.argv[1], sys.argv[2]
    frames, meta = [], []
    for clip, run, hit, before, after in CLIPS:
        rec = np.load(os.path.join(runs, run, 'rec', 'frames.npz'))
        live = {round(json.loads(l)['stamp'], 3): json.loads(l)
                for l in open(os.path.join(runs, run, 'rec', 'keep.jsonl'))}
        stamps = [round(float(s), 3) for s in rec['stamp']]
        # skip frames recorded before this run's teleport (the previous run's last pose)
        start = next(i for i, g in enumerate(rec['gt']) if g[0] < -1.0)
        at = next(i for i in range(start, len(stamps))
                  if stamps[i] in live and hit(live[stamps[i]], rec['gt'][i]))
        for i in range(max(start, at - before), min(len(stamps), at + after + 1)):
            b = live.get(stamps[i], {})
            frames.append(rec['frames'][i])
            meta.append({'clip': clip, 'run': run, 'stamp': stamps[i],
                         'gt': [round(float(v), 4) for v in rec['gt'][i]],
                         'event': i == at, 'strategy': b.get('strategy'),
                         'reason': b.get('reason'), 'error': b.get('error')})
    np.savez_compressed(out, frames=np.asarray(frames, np.uint8),
                        meta=np.asarray(json.dumps(meta)))
    for clip, *_ in CLIPS:
        print(clip, sum(m['clip'] == clip for m in meta))
    print(len(frames), 'frames ->', out, os.path.getsize(out), 'bytes')


if __name__ == '__main__':
    main()
