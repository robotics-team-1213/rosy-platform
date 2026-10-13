#!/usr/bin/env python3
"""Inspect an existing Fleet edge's heading ahead of a SIM/map pose."""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'operations/fleet'))
from fleet.routing.graph import build_graph
from fleet.site_map import from_lane_graph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('lane_graph_yaml')
    parser.add_argument('arc_id')
    parser.add_argument('x', type=float)
    parser.add_argument('y', type=float)
    args = parser.parse_args()
    arc = build_graph(from_lane_graph(args.lane_graph_yaml)).arcs[args.arc_id]
    distance, along, heading = arc.project(args.x, args.y)
    ahead = {}
    for step in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        _, _, future = arc.point_at(along + step)
        ahead[f'{step:.2f}'] = round(math.degrees(math.remainder(future - heading, math.tau)), 1)
    print(json.dumps({'arc_id': arc.id, 'map_offset_m': round(distance, 3),
                      'along_m': round(along, 3), 'ahead_heading_delta_deg': ahead}, indent=2))


if __name__ == '__main__':
    main()
