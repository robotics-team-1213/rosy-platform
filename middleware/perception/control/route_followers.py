"""Subject: build the route_a/route_b/route_ab camera follower from a lane graph file (ROS-free).

line_observer_node owns the parameters and the fail-closed warning; this owns the graph read and
the per-mode follower choice. Raises OSError, yaml.YAMLError or ValueError when it cannot build one.
"""

import os

import yaml

from .sensing.perception.paint_localizer import PaintMap
from .sensing.perception.route_camera import RouteCameraFollower
from .sensing.perception.route_hybrid import RouteHybridFollower
from .sensing.perception.route_map import RouteMapFollower


def build_route_follower(mode: str, graph_path: str, route, route_start, x_offset: float):
    with open(graph_path, encoding='utf-8') as handle:
        graph = yaml.safe_load(handle)
    start = tuple(route_start)
    if mode == 'route_a':
        return RouteCameraFollower(graph, route, start_pose=start, camera_x_offset_m=x_offset)
    paint_map = PaintMap.from_bundle(os.path.dirname(graph_path))
    follower = RouteHybridFollower if mode == 'route_ab' else RouteMapFollower
    return follower(graph, route, start_pose=start, camera_x_offset_m=x_offset, paint_map=paint_map)
