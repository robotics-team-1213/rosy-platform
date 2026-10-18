"""Subject: build the route_a/route_b/route_ab camera follower from a lane graph file (ROS-free).

`build_route_follower` owns the graph read and the per-mode follower choice; it raises OSError,
yaml.YAMLError or ValueError when it cannot build one. `RouteFollowerInput`, a mixin of
line_observer_node (split out of it, D-766), reads the node's parameters and turns every failure
into the one fail-closed warning.
"""

import os

import yaml

from .sensing.perception.camera_ground import simulation_ground_allowed
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


class RouteFollowerInput:
    def _build_route_follower(self, mode: str):
        """route_a/route_b/route_ab only. Missing or invalid lane_graph_path, route or
        route_start (or a graph/route that fails to build, e.g. a
        disconnected pair or a one-way ring arc walked backwards) fails
        closed: a warning logged once here at startup, no follower built,
        and CAMERA_LINE keeps publishing None (visible:false) every frame
        rather than going silent (D-143: this node still owes CORE
        evidence)."""
        # A static route_start anchors the first odometry pose without an
        # independent map fix. Keep these junction prototypes in simulation
        # until an active map and fresh localized start can authorize them.
        if not simulation_ground_allowed(
                source=self.get_parameter('camera_ground_source').value,
                simulation_enabled=self.get_parameter('allow_simulation_ground').value,
                use_sim_time=self.get_parameter('use_sim_time').value):
            self.get_logger().warning(
                f'{mode} prototype route modes require Gazebo simulation ground and clock; '
                'no follower built, CAMERA_LINE will publish no observation')
            return None
        graph_path = str(self.get_parameter('lane_graph_path').value)
        route = [str(key) for key in self.get_parameter('route').value]
        route_start = [float(v) for v in self.get_parameter('route_start').value]
        if not graph_path or not route or len(route_start) != 3:
            self.get_logger().warning(
                f'{mode} route modes need lane_graph_path, route and route_start; '
                'no follower built, CAMERA_LINE will publish no observation')
            return None
        try:
            return build_route_follower(mode, graph_path, route, route_start,
                                        float(self.get_parameter('camera_x_offset_m').value))
        except (OSError, yaml.YAMLError, ValueError) as exc:
            self.get_logger().warning(
                f'{mode} route modes need lane_graph_path, route and route_start '
                f'to build a valid follower ({exc}); no follower built, '
                'CAMERA_LINE will publish no observation')
            return None
