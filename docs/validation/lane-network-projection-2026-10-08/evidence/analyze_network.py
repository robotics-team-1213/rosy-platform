#!/usr/bin/env python3
"""Project recorded SIM GT poses onto every lane_graph segment."""
import argparse
import json

import numpy as np
import yaml


def distance(point, points):
    start, end = points[:-1], points[1:]
    step = end - start
    along = np.clip(((point - start) * step).sum(axis=1) / (step * step).sum(axis=1), 0, 1)
    return float(np.linalg.norm(point - start - along[:, None] * step, axis=1).min())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('frames_npz')
    parser.add_argument('lane_graph_yaml')
    parser.add_argument('--start-index', type=int, required=True)
    args = parser.parse_args()
    poses = np.load(args.frames_npz)['gt']
    if not 0 <= args.start_index < len(poses):
        raise ValueError('start index outside recording')
    with open(args.lane_graph_yaml, encoding='utf-8') as source:
        graph = yaml.safe_load(source)
    segments = {name: np.asarray(spec['points'], float)
                for name, spec in graph['segments'].items()}
    rows = []
    for index in range(args.start_index, len(poses)):
        pose = poses[index]
        if not np.isfinite(pose).all():
            continue
        distances = {name: distance(pose[:2], points) for name, points in segments.items()}
        nearest = min(distances, key=distances.get)
        rows.append((index, pose, nearest, distances[nearest]))
    if not rows:
        raise ValueError('no finite GT pose after start index')
    worst = max(rows, key=lambda row: row[3])
    print(json.dumps({'frames': len(rows), 'nearest_max_m': round(worst[3], 4),
                      'nearest_max_frame': worst[0], 'nearest_segment': worst[2],
                      'nearest_max_gt': [round(float(v), 4) for v in worst[1]],
                      'nearest_over_40mm_frames': sum(row[3] > 0.04 for row in rows),
                      'nearest_over_half_width_frames': sum(row[3] > 0.0925 for row in rows)},
                     indent=2))


if __name__ == '__main__':
    main()
