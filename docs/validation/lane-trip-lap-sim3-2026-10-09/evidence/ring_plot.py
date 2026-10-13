#!/usr/bin/env python3
"""Lap SIM 3 (no ROS): top view of the 260919 paint around the roundabout with run tracks.
  python ring_plot.py out.png <log.jsonl>[:label] ...   (repo root on sys.path for stl_scene)"""
import json, math, sys
from pathlib import Path
from PIL import Image, ImageDraw
sys.path.insert(0, 'middleware/perception/map/map_v2_fleet/scripts')
from stl_scene import load_scene
scene = load_scene('middleware/perception/map/map_v2_fleet/260919 MAP FILE.STL')
X0, X1, Y0, Y1, S = -0.75, 0.10, -0.55, 0.30, 1000  # px per m
W, H = int((X1 - X0) * S), int((Y1 - Y0) * S)
img = Image.new('RGB', (W, H), (40, 40, 40))
d = ImageDraw.Draw(img)
px = lambda x, y: ((x - X0) * S, (Y1 - y) * S)
for t in scene.lines:
    d.polygon([px(v[0], v[1]) for v in t], fill=(230, 230, 230))
C, R = (-0.3357, 0.0011), 0.2514
d.ellipse([px(C[0] - R, C[1] + R), px(C[0] + R, C[1] - R)], outline=(0, 160, 0))
cols = [(255, 60, 60), (60, 140, 255), (255, 200, 0), (200, 0, 255), (0, 220, 220), (255, 128, 0)]
for k, arg in enumerate(sys.argv[2:]):
    path = arg
    last = None
    for l in open(path):
        r = json.loads(l)
        if not r.get('gt'):
            continue
        x, y, yaw = r['gt']
        if not (X0 < x < X1 and Y0 < y < Y1):
            last = None
            continue
        p = px(x, y)
        if last:
            d.line([last, p], fill=cols[k % len(cols)], width=2)
        last = p
        if r.get('reason') in ('junction_corner_hold', 'camera_line_not_visible', 'stuck_back_off'):
            d.ellipse([p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3], outline=cols[k % len(cols)])
img.save(sys.argv[1])
