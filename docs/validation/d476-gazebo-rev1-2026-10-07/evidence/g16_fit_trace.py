#!/usr/bin/env python3
"""G-16 fit trace, ROS-free: replay one saved Gazebo camera frame (g16_probe.py capture) through the
product keep-mode pipeline and show where each boundary's slope comes from.

Prints (1) the lateral span the 320x240 / 59.2 deg frame sees at near x (image-edge truncation of the
paint), (2) every extract_lines line and blob (crosswalk), (3) for each lane side, the paint cells
the final fit used against all paint cells of that side, and the PCA slope of each set, with the
fitted y extrapolated to the body rear (-0.076 m, where D-468 checks the footprint).

    PYTHONPATH="<repo>/contracts/foundation:<repo>/middleware/perception" \
        python g16_fit_trace.py runs/g16_C_frame0.png
"""
import math
import sys

import cv2
import numpy as np

from control.sensing.perception import lane_keep as LK
from control.sensing.perception import lane_keep_lines as L
from control.sensing.perception.camera_ground import simulation_ground_plane
from control.sensing.perception.lane_bev import BirdsEye

REAR = -0.076
CAMERA_X = 0.03317  # line_follow.yaml camera_x_offset_m (Gazebo sensor pose x)


def slope_at_rear(points):
    c, d = L._fit_axis(points)
    k = d[1]/d[0]
    return round(float(k), 4), round(float(c[1]+(REAR-c[0])*k), 4)


def main(path):
    g = simulation_ground_plane(source='GAZEBO', simulation_enabled=True, use_sim_time=True, width_px=320,
                                height_px=240, height_m=0.06343, pitch_rad=math.radians(8.0),
                                hfov_rad=2*math.atan(160/281.6), max_range_m=0.6)
    view = BirdsEye(g, 320, 240, CAMERA_X)
    xs, ys = view.x[:, 0], view.y[0, :]
    for x in (0.15, 0.18, 0.20, 0.22, 0.24):
        seen = ys[view.observable[int(np.argmin(abs(xs-x)))]]
        print(f'frame sees |y| <= {seen.max():.3f} m at x {x:.2f} (tape inner/outer |y| 0.080/0.105)')
    grid = view.sample(L.floor_white_mask(cv2.imread(path), g.horizon_row))
    s = LK.FIT_STRIDE
    cells = np.flatnonzero(grid[::s, ::s].ravel())
    pts = np.stack([view.x[::s, ::s].ravel()[cells], view.y[::s, ::s].ravel()[cells]], axis=1)
    used = []
    original = L._fit_axis

    def spy(p):
        used.append(p)
        return original(p)
    L._fit_axis = spy
    lines, blobs = L.extract_lines(pts, np.random.default_rng(LK.LaneKeeper(camera_x_offset_m=CAMERA_X)._seed))
    L._fit_axis = original
    for kind, group in (('line', lines), ('blob', blobs)):
        for e in group:
            c, d = e['centre'], e['direction']
            print(f'{kind}: centre ({c[0]:.3f}, {c[1]:.3f}) heading {math.degrees(math.atan2(d[1], d[0])):.1f} deg '
                  f'along {e["along"][0]:.3f}..{e["along"][1]:.3f} cells {e["cells"]}')
    for e in lines:
        c, d = e['centre'], e['direction']
        if abs(d[1]) > abs(d[0]):
            continue  # transverse
        side = 'left' if c[1] > 0 else 'right'
        fit = next(q for q in reversed(used) if len(q) == e['cells'] and np.allclose(q.mean(axis=0), c))
        band = (np.abs(pts[:, 1]) >= 0.075) & (np.abs(pts[:, 1]) <= 0.112) & (np.sign(pts[:, 1]) == np.sign(c[1]))
        tape = pts[band & (pts[:, 0] <= fit[:, 0].max()+1e-6)]
        kept = {tuple(q) for q in np.round(fit, 4)}
        missing = np.array([q for q in np.round(tape, 4) if tuple(q) not in kept]).reshape(-1, 2)
        far = tape[tape[:, 0] > 0.235]
        print(f'{side}: fit {len(fit)} cells x {fit[:, 0].min():.3f}..{fit[:, 0].max():.3f} -> slope, y at rear '
              f'{slope_at_rear(fit)}; tape-band cells over the same x {len(tape)} -> {slope_at_rear(tape)}; '
              f'of those x > 0.235 -> {slope_at_rear(far)}; tape cells left out of the fit {len(missing)}'
              + (f' (x {missing[:, 0].min():.3f}..{missing[:, 0].max():.3f}, |y| {np.abs(missing[:, 1]).min():.4f}..'
                 f'{np.abs(missing[:, 1]).max():.4f})' if len(missing) else ''))


if __name__ == '__main__':
    main(sys.argv[1])
