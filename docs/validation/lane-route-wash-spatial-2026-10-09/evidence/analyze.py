"""Read-only BEV brightness replay for the B9 wash counterexample."""

import hashlib
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'middleware/perception'),
                str(ROOT / 'middleware/perception/test'),
                str(ROOT / 'contracts/foundation')]

from control.sensing.perception.camera_visibility import visibility_reason  # noqa: E402
from control.sensing.perception.lane_bev import BirdsEye  # noqa: E402
from lane_sim import simulation_ground_plane  # noqa: E402


def analyze(path):
    data = np.load(path)
    frames, stamps = data['frames'], data['stamp']
    assert frames.ndim == 4 and frames.shape[1:] == (240, 320, 3)
    assert len(frames) == len(stamps) and len(frames) > 0
    assert np.all(np.isfinite(stamps)) and np.all(np.diff(stamps) > 0)
    ground = simulation_ground_plane(
        source='GAZEBO', simulation_enabled=True, use_sim_time=True,
        width_px=320, height_px=240, height_m=.06343, pitch_rad=math.radians(8),
        hfov_rad=2 * math.atan(160 / 281.6), max_range_m=.6)
    view = BirdsEye(ground, 320, 240, .03317)
    near = view.observable & (view.x < .25)
    far = view.observable & (view.x >= .25)
    assert near.any() and far.any()
    rows = []
    for index, (frame, stamp) in enumerate(zip(frames, stamps)):
        paint = view.sample(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) > 180)
        all_fraction = float(paint.sum() / view.observable.sum())
        near_fraction = float(paint[near].mean())
        far_fraction = float(paint[far].mean())
        rows.append({
            'index': index, 'stamp_s': round(float(stamp), 3),
            'all': round(all_fraction, 4),
            'near': round(near_fraction, 4),
            'far': round(far_fraction, 4),
            'raw_quality': visibility_reason(frame),
            'global_40': all_fraction > .4,
            'near_40': near_fraction > .4,
            'global_75': all_fraction > .75,
        })
    return {
        'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'frames': len(rows),
        'global_40': sum(row['global_40'] for row in rows),
        'near_40': sum(row['near_40'] for row in rows),
        'global_75': sum(row['global_75'] for row in rows),
        'raw_unusable': sum(row['raw_quality'] != 'usable' for row in rows),
        'first_global_40': next((row for row in rows if row['global_40']), None),
        'first_near_40': next((row for row in rows if row['near_40']), None),
        'max_near': max(rows, key=lambda row: row['near']),
    }


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('usage: analyze.py <capture.npz> [capture.npz ...]')
    print(json.dumps({Path(p).name: analyze(Path(p)) for p in sys.argv[1:]}, indent=2))
