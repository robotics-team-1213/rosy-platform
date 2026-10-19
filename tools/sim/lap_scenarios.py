"""Short drives over each hard place of the map_v2_fleet lap (fleet_trips --scenario NAME).

The whole lap stops at its first failure, so one 25 min run teaches one place. A scenario starts the
robot on the lap route shortly before one place and ends shortly after it: run them side by side and
repeat them to see every failing place and how often it fails (v2 lap r21-r40).
Distances are metres along the lap route from its start (fleet_trips LAP route, east road south side).
"""

#: the lap route as Fleet plans it (r27 plan): (segment, travel direction, s_from, s_to or None = segment end)
LAP_ROUTE = (('east', 'rev', 0.92, None), ('ring_n', 'fwd', 0.0, None), ('west', 'rev', 0.0, None),
             ('ring_s', 'fwd', 0.0, None), ('east', 'rev', 0.0, 0.92))

#: name -> (start, end) along LAP_ROUTE (m) and what the place is
SCENARIOS = {
    'ne_corner': (0.30, 1.30, "east road's north-east bend"),
    'east_s_curve': (1.20, 2.00, "east road's S-curve after the bend (r36 drift)"),
    'east_nw_turn': (1.80, 2.60, "east road's turns north (r39, r40 left the lane at 2.25)"),
    # a lane trip cannot end inside the ring (Fleet extends it to the next exit), so both end on the west road
    'ring_entry': (2.50, 3.80, 'the north road through the ring to the west road (r38)'),
    'ring_exit_west': (3.20, 3.95, "the ring's north arc out to the west road (r23, r25, r37)"),
    'west_nw_corner': (3.70, 4.70, "west road's north-west corner"),
    'west_crosswalk': (4.60, 5.30, 'west road crosswalk beside the wall (r29)'),
    'west_sw_corner': (5.10, 5.90, "west road's south-west corner (r27)"),
    'spoke_ring_s': (5.80, 7.10, 'the spoke through the ring back to the east road'),
    'east_crosswalk': (7.00, 7.58, "east road's crosswalk to the lap start"),
}


def route_pose(graph, d, lane_pose):
    """(x, y, yaw) d metres along LAP_ROUTE; lane_pose is fleet_trips.lane_pose."""
    import math
    for segment, direction, s_from, s_to in LAP_ROUTE:
        points = graph['segments'][segment]['points']
        end = sum(math.dist(a, b) for a, b in zip(points, points[1:])) if s_to is None else s_to
        if d <= end - s_from:
            return lane_pose(graph, segment, direction, s_from + d)
        d -= end - s_from
    raise ValueError('past the end of the lap route')
