#!/usr/bin/env python3
"""Summarize edge_south1 GT distance to the west map edge, after the last teleport."""
import argparse
import json

import numpy as np
import yaml


def distance(point, points):
    a, b = points[:-1], points[1:]
    delta = b - a
    fraction = np.clip(np.sum((point - a) * delta, axis=1) / np.sum(delta * delta, axis=1), 0, 1)
    return float(np.min(np.linalg.norm(point - (a + fraction[:, None] * delta), axis=1)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('frames_npz')
    parser.add_argument('lane_graph_yaml')
    parser.add_argument('--start-index', type=int, required=True)
    args = parser.parse_args()
    frames = np.load(args.frames_npz)
    with open(args.lane_graph_yaml, encoding='utf-8') as source:
        graph = yaml.safe_load(source)
    points = np.asarray(graph['segments']['west']['points'], float)
    rows = [(i, pose, distance(pose[:2], points))
            for i, pose in enumerate(frames['gt'])
            if i >= args.start_index and np.isfinite(pose).all()]
    bend = [d for _, pose, d in rows if -0.95 <= pose[0] <= -0.78 and pose[1] < -0.3]
    if not rows or not bend:
        raise ValueError('no valid post-spawn path or bend-window frames')
    worst = max(rows, key=lambda row: row[2])
    print(json.dumps({
        'post_spawn_frames': len(rows), 'bend_frames': len(bend),
        'bend_median_m': round(float(np.median(bend)), 4),
        'bend_max_m': round(max(bend), 4),
        'west_max_m': round(worst[2], 4), 'west_max_frame': worst[0],
        'west_max_gt': [round(float(v), 4) for v in worst[1]],
        'west_over_40mm_frames': sum(d > 0.04 for _, _, d in rows),
        'west_over_half_width_frames': sum(d > 0.0925 for _, _, d in rows),
    }, indent=2))


if __name__ == '__main__':
    main()
