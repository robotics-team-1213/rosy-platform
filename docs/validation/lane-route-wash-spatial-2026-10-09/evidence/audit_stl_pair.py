"""Compare route_a paint components with the independent STL floor raster in SIM."""

import hashlib
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / 'middleware/perception/map/map_v2_fleet/scripts'
sys.path[:0] = [str(ROOT / 'middleware/perception'),
                str(ROOT / 'middleware/perception/test'),
                str(ROOT / 'contracts/foundation'), str(SCRIPTS)]

from control.sensing.perception.route_camera import RouteCameraFollower  # noqa: E402
from lane_graph import RASTER_M, paint_masks  # noqa: E402
from lane_scenarios import GRAPH  # noqa: E402
from lane_sim import simulation_ground_plane  # noqa: E402
from stl_scene import load_scene  # noqa: E402


def audit(path):
    data = np.load(path)
    frames, stamps, poses = data['frames'], data['stamp'], data['gt']
    assert frames.ndim == 4 and frames.shape[1:] == (240, 320, 3)
    assert poses.shape == (len(frames), 3) and len(stamps) == len(frames)
    assert np.all(np.isfinite(poses)) and np.all(np.diff(stamps) > 0)
    scene = load_scene(SCRIPTS.parent / '260919 MAP FILE.STL')
    x0, y1, floor_line, crosswalk = paint_masks(scene)
    n_components, stl_ids = cv2.connectedComponents(floor_line.astype(np.uint8), connectivity=8)
    # Axis-wise +/-6 mm raster allowance (diagonal ~8.5 mm), not a GT tolerance.
    kernel = np.ones((7, 7), np.uint8)
    line_near = cv2.dilate(floor_line.astype(np.uint8), kernel).astype(bool)
    bar_near = cv2.dilate(crosswalk.astype(np.uint8), kernel).astype(bool)
    ground = simulation_ground_plane(
        source='GAZEBO', simulation_enabled=True, use_sim_time=True,
        width_px=320, height_px=240, height_m=.06343, pitch_rad=math.radians(8),
        hfov_rad=2 * math.atan(160 / 281.6), max_range_m=.6)
    follower = RouteCameraFollower(GRAPH, ['west:r', 'ring_s:f'],
                                   start_pose=tuple(poses[0]), camera_x_offset_m=.03317)
    sides = {'left': [], 'right': []}
    for index, (frame, stamp, pose) in enumerate(zip(frames, stamps, poses)):
        follower.update(float(stamp), tuple(pose), frame, ground,
                        lane_half_width_m=.0925, bright_threshold=180,
                        roi_top_fraction=.4, roi_bottom_fraction=1., washed_fraction=.75)
        tracker = follower.last.get('tracker', {})
        paint = tracker.get('paint')
        assert paint is not None
        _, labels = cv2.connectedComponents(paint, connectivity=4)
        view = follower._tracker._view
        c, s = math.cos(pose[2]), math.sin(pose[2])
        wx = pose[0] + c * view.x - s * view.y
        wy = pose[1] + s * view.x + c * view.y
        cols = np.rint((wx - x0) / RASTER_M).astype(int)
        rows = np.rint((y1 - wy) / RASTER_M).astype(int)
        inside = ((rows >= 0) & (rows < floor_line.shape[0])
                  & (cols >= 0) & (cols < floor_line.shape[1]))
        rows = np.clip(rows, 0, floor_line.shape[0] - 1)
        cols = np.clip(cols, 0, floor_line.shape[1] - 1)
        for side in sides:
            label = tracker.get(side + '_label')
            assert label is not None  # this audit is for the saved 85/85 BOTH run
            all_cells = labels == label
            cells = all_cells & inside
            assert cells.any()
            line_hit = line_near[rows[cells], cols[cells]]
            bar_hit = bar_near[rows[cells], cols[cells]]
            ids, counts = np.unique(stl_ids[rows[cells], cols[cells]], return_counts=True)
            dominant = int(ids[np.argmax(counts)])
            sides[side].append({
                'index': index, 'stl_component': dominant,
                'component_fraction': float(counts.max() / cells.sum()),
                'line_only_fraction': float(np.mean(line_hit & ~bar_hit)),
                'bar_only_fraction': float(np.mean(bar_hit & ~line_hit)),
                'outside_cells': int((all_cells & ~inside).sum()),
            })
    return {
        'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'stl_sha256': scene.source_sha256,
        'stl_line_components': n_components - 1,
        'frames': len(frames),
        'unique_frame_hashes': len({hashlib.sha256(frame.tobytes()).digest() for frame in frames}),
        'sides': {side: {
            'dominant_stl_components': sorted({row['stl_component'] for row in records}),
            'min_component_fraction': min(row['component_fraction'] for row in records),
            'min_line_only_fraction': min(row['line_only_fraction'] for row in records),
            'max_bar_only_fraction': max(row['bar_only_fraction'] for row in records),
            'outside_cells': sum(row['outside_cells'] for row in records),
            'after_first_wash': {
                'min_component_fraction': min(row['component_fraction'] for row in records[7:]),
                'min_line_only_fraction': min(row['line_only_fraction'] for row in records[7:]),
                'max_bar_only_fraction': max(row['bar_only_fraction'] for row in records[7:]),
            },
            'samples': [records[i] for i in (7, 16, 21, 84)],
        } for side, records in sides.items()},
    }


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: audit_stl_pair.py <camera_wash075.npz>')
    print(json.dumps(audit(Path(sys.argv[1])), indent=2))
