#!/usr/bin/env python3
"""G-16 probe (sim2real_gaps.yaml): where does the Gazebo lane detector put each D-468
containment boundary against the STL paint, for a parked Pinky? Model PC only.

capture  gz set_pose (x, y, yaw), wait, then record N line/observation containment
         payloads, the matching line/keep_debug bundles and a few raw camera/front
         frames (PNG), plus the gz ground-truth model pose. Writes capture.json + frame_*.png.
analyze  ROS-free: for each payload boundary, the true paint (road_lines.stl, metres,
         Z-up, the mesh the world renders) in the body frame at the boundary's observed
         x range and at the footprint ends; the D-468 Corridor margin from the payload
         (raw and eroded by uncertainty_m) vs the STL margin; and, on the saved frames,
         where the true paint edges fall in the image vs the floor_white_mask bright runs.

Body footprint: pinky_pro core.yaml URDF nominal (front 0.042, rear -0.076, half 0.0566).
"""
import argparse
import json
import math
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

FRONT, REAR, HALF = 0.042, -0.076, 0.0566
PAINT_HALF = 0.0125


def set_pose(x, y, yaw):
    req = (f'name: "rosy", position: {{x: {x}, y: {y}, z: 0.01}}, '
           f'orientation: {{z: {math.sin(yaw/2)}, w: {math.cos(yaw/2)}}}')
    return subprocess.run(['gz', 'service', '-s', '/world/map_v2_fleet/set_pose', '--reqtype',
                           'gz.msgs.Pose', '--reptype', 'gz.msgs.Boolean', '--timeout', '3000',
                           '--req', req], capture_output=True, text=True).stdout.strip()


def gt_pose():
    out = subprocess.run(['gz', 'topic', '-e', '-n', '1', '-t', '/world/map_v2_fleet/dynamic_pose/info',
                          '--json-output'], capture_output=True, text=True, timeout=10).stdout
    for p in json.loads(out.splitlines()[0]).get('pose', []):
        if p.get('name') == 'rosy':
            pos, q = p.get('position', {}), p.get('orientation', {})
            w, z, qx, qy = q.get('w', 1.0), q.get('z', 0.0), q.get('x', 0.0), q.get('y', 0.0)
            return [pos.get('x', 0.0), pos.get('y', 0.0), math.atan2(2*(w*z+qx*qy), 1-2*(qy*qy+z*z))]
    return None


def capture(a):
    import cv2
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    from std_msgs.msg import String
    from control.sensing.perception.image_frame import image_msg_to_frame

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print('set_pose', set_pose(a.x, a.y, a.yaw), flush=True)
    time.sleep(a.settle)
    rclpy.init()
    node = rclpy.create_node('g16_probe')
    obs, keep, frames = [], {}, []

    def on_obs(m):
        p = json.loads(m.data)
        if p.get('source') == 'CAMERA_LINE':
            obs.append(p)

    def on_keep(m):
        p = json.loads(m.data)
        keep[round(float(p.get('stamp', 0.0)), 6)] = {k: p.get(k) for k in (
            'strategy', 'boundaries', 'candidates', 'reason', 'blobs', 'target_m')}

    def on_img(m):
        if len(frames) < a.frames:
            stamp = m.header.stamp.sec + m.header.stamp.nanosec*1e-9
            name = f'frame_{len(frames)}.png'
            cv2.imwrite(str(out/name), image_msg_to_frame(m))
            frames.append({'file': name, 'stamp': stamp})

    node.create_subscription(String, 'line/observation', on_obs, 50)
    node.create_subscription(String, 'line/keep_debug', on_keep, 50)
    node.create_subscription(Image, 'camera/front', on_img, qos_profile_sensor_data)
    gt0 = gt_pose()
    t0 = time.monotonic()
    while sum(1 for p in obs if p.get('containment')) < a.n and time.monotonic()-t0 < a.timeout:
        rclpy.spin_once(node, timeout_sec=0.1)
    gt1 = gt_pose()
    node.destroy_node()
    rclpy.shutdown()
    rows = []
    for p in obs:
        st = round(float(p.get('stamp', 0.0)), 6)
        rows.append({'stamp': p.get('stamp'), 'visible': p.get('visible'), 'error': p.get('error'),
                     'confidence': p.get('confidence'), 'containment': p.get('containment'),
                     'keep': keep.get(st)})
    json.dump({'request': [a.x, a.y, a.yaw], 'gt_start': gt0, 'gt_end': gt1, 'frames': frames,
               'rows': rows}, open(out/'capture.json', 'w'), indent=1)
    print(f'{len(rows)} observations, {sum(1 for r in rows if r["containment"])} with containment, '
          f'gt {gt0} -> {gt1}')


# ---------------------------------------------------------------- analysis (ROS-free)
def load_stl(path):
    d = Path(path).read_bytes()
    n = struct.unpack_from('<I', d, 80)[0]
    t = np.array([struct.unpack_from('<12f', d, 84+50*i)[3:] for i in range(n)])
    return t.reshape(n, 3, 3)[:, :, :2]


def paint_mask(tri, px, py):
    """bool array: points (px, py) world inside any paint triangle."""
    px, py = np.asarray(px, float)[:, None], np.asarray(py, float)[:, None]
    a, b, c = tri[None, :, 0], tri[None, :, 1], tri[None, :, 2]

    def cr(p, q):
        return (q[..., 0]-p[..., 0])*(py-p[..., 1])-(q[..., 1]-p[..., 1])*(px-p[..., 0])
    d1, d2, d3 = cr(a, b), cr(b, c), cr(c, a)
    inside = ((d1 >= 0) & (d2 >= 0) & (d3 >= 0)) | ((d1 <= 0) & (d2 <= 0) & (d3 <= 0))
    return inside.any(axis=1)


def paint_runs(tri, pose, x, span=0.2, step=0.0005):
    """Paint intervals (y_lo, y_hi) across the body-frame line at body x (left = +y)."""
    px0, py0, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    ks = np.arange(-span, span+step/2, step)
    hit = paint_mask(tri, px0+c*x-s*ks, py0+s*x+c*ks)
    runs, start = [], None
    for k, h in zip(ks, hit):
        if h and start is None:
            start = k
        if not h and start is not None:
            runs.append((float(start), float(k-step)))
            start = None
    if start is not None:
        runs.append((float(start), float(ks[-1])))
    return runs


def side_run(runs, side, y_hint):
    """The true paint run on ``side`` nearest the detector's fitted centre y_hint."""
    cands = [r for r in runs if (r[0]+r[1])/2 > 0] if side == 'left' else [r for r in runs if (r[0]+r[1])/2 < 0]
    return min(cands, key=lambda r: abs((r[0]+r[1])/2-y_hint)) if cands else None


def margin(left, right):
    """lane_return.Corridor.margin for (slope, intercept) left/right edges and the URDF body."""
    return min(min((left[0]*x+left[1]-HALF)/math.hypot(1, left[0]),
                   (-HALF-(right[0]*x+right[1]))/math.hypot(1, right[0])) for x in (FRONT, REAR))


def analyze(a):
    import cv2
    tri = load_stl(a.stl)
    cap = json.load(open(Path(a.out)/'capture.json'))
    pose = cap['gt_start']
    res = {'gt_pose': pose, 'stl_at_body': {}}
    for x in (REAR, 0.0, FRONT, 0.15, 0.25, 0.35, 0.45):
        res['stl_at_body'][f'{x:.3f}'] = paint_runs(tri, pose, x)
    # STL margin: nearest run each side of the body centre at the footprint ends (inner edges).
    ends = {}
    for x in (FRONT, REAR):
        runs = paint_runs(tri, pose, x)
        ends[x] = (min(r[0] for r in runs if (r[0]+r[1])/2 > 0), max(r[1] for r in runs if (r[0]+r[1])/2 < 0))
    res['stl_margin_inner_m'] = round(min(min(l-HALF, -HALF-r) for l, r in ends.values()), 4)
    per = []
    for row in cap['rows']:
        c = row.get('containment')
        if not c or not c.get('boundaries'):
            continue
        u = c.get('uncertainty_m') or 0.0
        e = {'stamp': row['stamp'], 'uncertainty_m': c.get('uncertainty_m'), 'sides': {}}
        lines = {}
        for b in c['boundaries']:
            slope, inner = b['slope'], b['intercept_m']
            sign = 1 if b['side'] == 'left' else -1
            centre_fit = inner+sign*PAINT_HALF*math.hypot(1, slope)
            lines[b['side']] = (slope, inner)
            xm = (b['observed_x_min_m']+b['observed_x_max_m'])/2
            errs = []
            for x in (b['observed_x_min_m'], xm, b['observed_x_max_m'], FRONT, REAR):
                run = side_run(paint_runs(tri, pose, x), b['side'], slope*x+centre_fit)
                if run is None:
                    errs.append({'x': round(x, 3), 'true': None})
                    continue
                true_c, true_in = (run[0]+run[1])/2, (run[0] if b['side'] == 'left' else run[1])
                errs.append({'x': round(x, 3), 'fit_centre': round(slope*x+centre_fit, 4),
                             'true_centre': round(true_c, 4), 'true_width': round(run[1]-run[0], 4),
                             'centre_err_inward_m': round(sign*(true_c-(slope*x+centre_fit)), 4),
                             'payload_inner': round(slope*x+inner, 4), 'true_inner': round(true_in, 4),
                             'inner_err_inward_m': round(sign*(true_in-(slope*x+inner)), 4)})
            e['sides'][b['side']] = {'slope': round(slope, 4), 'observed_x': [b['observed_x_min_m'], b['observed_x_max_m']],
                                     'at': errs}
        if set(lines) == {'left', 'right'}:
            m = margin(lines['left'], lines['right'])
            e['margin_raw_m'] = round(m, 4)
            e['margin_eroded_m'] = round(m-u, 4)
        e['keep_strategy'] = (row.get('keep') or {}).get('strategy')
        per.append(e)
    res['frames'] = per
    raw = [p['margin_raw_m'] for p in per if 'margin_raw_m' in p]
    if raw:
        res['margin_raw_m'] = {'n': len(raw), 'median': round(float(np.median(raw)), 4),
                               'min': round(min(raw), 4), 'max': round(max(raw), 4)}
    for side in ('left', 'right'):
        ce = [x['centre_err_inward_m'] for p in per for x in p['sides'].get(side, {}).get('at', [])[:3]
              if x.get('centre_err_inward_m') is not None]
        if ce:
            res[f'{side}_centre_err_inward_m'] = {'n': len(ce), 'median': round(float(np.median(ce)), 4),
                                                  'min': round(min(ce), 4), 'max': round(max(ce), 4)}
    # Image check: true paint edges projected with the declared Gazebo ground vs mask runs.
    res['image'] = image_check(a, cap, tri, pose, cv2)
    (Path(a.out)/'analysis.json').write_text(json.dumps(res, indent=1))
    summary = {k: v for k, v in res.items() if k not in ('frames', 'image')}
    summary['image'] = res['image'][:1] if res['image'] else None
    print(json.dumps(summary, indent=1))


def image_check(a, cap, tri, pose, cv2):
    sys.path.insert(0, a.control) if a.control else None
    from control.sensing.perception.camera_ground import simulation_ground_plane
    from control.sensing.perception.lane_keep_lines import floor_white_mask
    g = simulation_ground_plane(source='GAZEBO', simulation_enabled=True, use_sim_time=True, width_px=320,
                                height_px=240, height_m=0.06343, pitch_rad=math.radians(8.0),
                                hfov_rad=2*math.atan(160/281.6), max_range_m=0.6)
    cam_x = 0.03317
    out = []
    for f in cap['frames'][:a.image_frames]:
        bgr = cv2.imread(str(Path(a.out)/f['file']))
        mask = floor_white_mask(bgr, g.horizon_row)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        rows = []
        for x in (0.15, 0.20, 0.25, 0.30, 0.40):
            fwd = x-cam_x
            ray = math.atan2(g.height_m, fwd)-g.pitch_rad
            r = g.principal_y+g.focal_px*math.tan(ray)
            den = g.focal_px*math.sin(g.pitch_rad)+(r-g.principal_y)*math.cos(g.pitch_rad)
            col = lambda y: g.principal_x-y*den/g.height_m  # noqa: E731
            ri = int(round(r))
            if not 0 <= ri < 240:
                continue
            true = [[round(col(hi), 1), round(col(lo), 1)] for lo, hi in paint_runs(tri, pose, x)]
            m = mask[ri]
            runs, s = [], None
            for j, v in enumerate(list(m)+[0]):
                if v and s is None:
                    s = j
                if not v and s is not None:
                    runs.append([s, j-1])
                    s = None
            rows.append({'x': x, 'row': ri, 'm_per_px': round(g.height_m/den, 5), 'true_cols': true,
                         'mask_runs': runs, 'gray_row': gray[ri].tolist() if a.dump_gray else None})
        out.append({'file': f['file'], 'rows': rows})
    return out


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('capture')
    c.add_argument('--x', type=float, required=True)
    c.add_argument('--y', type=float, required=True)
    c.add_argument('--yaw', type=float, required=True)
    c.add_argument('--out', required=True)
    c.add_argument('--n', type=int, default=30)
    c.add_argument('--frames', type=int, default=3)
    c.add_argument('--settle', type=float, default=3.0)
    c.add_argument('--timeout', type=float, default=30.0)
    an = sub.add_parser('analyze')
    an.add_argument('out')
    an.add_argument('--stl', required=True)
    an.add_argument('--control', default='', help='path holding the control package (ROS-free host)')
    an.add_argument('--image-frames', type=int, default=1)
    an.add_argument('--dump-gray', action='store_true')
    a = p.parse_args()
    capture(a) if a.cmd == 'capture' else analyze(a)
    return 0


if __name__ == '__main__':
    sys.exit(main())
