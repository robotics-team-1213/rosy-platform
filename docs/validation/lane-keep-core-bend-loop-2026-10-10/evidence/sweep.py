"""Deterministic bend radius/entry and start-pose sensitivity, host only."""

import json
import math

import replay


def main():
    original_start = replay.START
    original_radius = replay.BEND_RADIUS_M
    original_in = replay.BEND_IN_M
    cases = []
    try:
        for radius, entry_delta in ((0.15, 0.0), (0.08, -0.03)):
            replay.BEND_RADIUS_M = radius
            replay.BEND_IN_M = (replay.VERTEX_X - radius * math.tan(math.radians(replay.TURN_DEG) / 2)
                                - original_start[0] + entry_delta)
            for lateral in (-0.02, 0.0, 0.02):
                for heading_deg in (-2.0, 0.0, 2.0):
                    replay.START = (original_start[0], lateral, math.radians(heading_deg))
                    result = replay.run(True)
                    cases.append({"radius_m": radius, "entry_delta_m": entry_delta,
                                  "start_lateral_m": lateral, "start_heading_deg": heading_deg,
                                  "end_state": result["final"]["junction_state"],
                                  "outside_ticks": result["outside_ticks"],
                                  "max_outside_cells": result["max_footprint_outside_cells"],
                                  "max_centre_deviation_m": result["max_centre_deviation_m"]})
    finally:
        replay.START = original_start
        replay.BEND_RADIUS_M = original_radius
        replay.BEND_IN_M = original_in
    assert len(cases) == 18
    print(json.dumps({"body_raster_m": 0.001, "cases": cases}, indent=2))


if __name__ == "__main__":
    main()
