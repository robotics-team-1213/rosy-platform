"""ROS-free acceptance math shared by Pinky Gazebo runtime tools."""

from __future__ import annotations

import math
from collections import deque


def goal_position_error(
    actual_xy: tuple[float, float],
    goal_xy: tuple[float, float],
) -> float:
    values = (*actual_xy, *goal_xy)
    if not all(math.isfinite(float(value)) for value in values):
        return math.nan
    return math.dist(actual_xy, goal_xy)


def nav_result_passes(status: str, error_m: float, max_error_m: float) -> bool:
    if not math.isfinite(max_error_m) or max_error_m <= 0.0:
        raise ValueError("maximum navigation error must be positive and finite")
    return (
        str(status).upper() == "SUCCEEDED"
        and math.isfinite(error_m)
        and 0.0 <= error_m <= max_error_m
    )


def point_wall_clearance(point_xy, wall: dict) -> float:
    """Distance from a point to one measured, yaw-rotated wall box."""
    x, y = (float(value) for value in point_xy)
    pose = wall["pose"]
    size = wall["size"]
    dx, dy = x - float(pose[0]), y - float(pose[1])
    cosine, sine = math.cos(float(pose[5])), math.sin(float(pose[5]))
    local_x = cosine * dx + sine * dy
    local_y = -sine * dx + cosine * dy
    outside_x = max(abs(local_x) - float(size[0]) / 2.0, 0.0)
    outside_y = max(abs(local_y) - float(size[1]) / 2.0, 0.0)
    return math.hypot(outside_x, outside_y)


def center_clearance(point_xy, walls) -> float:
    if not walls:
        raise ValueError("at least one wall is required")
    return min(point_wall_clearance(point_xy, wall) for wall in walls)


def trajectory_clearance(poses_xy, walls, robot_radius_m: float) -> dict:
    if not math.isfinite(robot_radius_m) or robot_radius_m <= 0.0:
        raise ValueError("robot radius must be positive and finite")
    poses = list(poses_xy)
    if not poses:
        return {
            "sample_count": 0,
            "minimum_center_to_wall_m": None,
            "minimum_body_clearance_m": None,
            "collision": True,
        }
    minimum = min(center_clearance(point, walls) for point in poses)
    body_clearance = minimum - robot_radius_m
    return {
        "sample_count": len(poses),
        "minimum_center_to_wall_m": minimum,
        "minimum_body_clearance_m": body_clearance,
        "collision": body_clearance < 0.0,
    }


def _wall_bounds(walls) -> tuple[float, float, float, float]:
    corners = []
    for wall in walls:
        pose, size = wall["pose"], wall["size"]
        cosine, sine = math.cos(float(pose[5])), math.sin(float(pose[5]))
        half_x, half_y = float(size[0]) / 2.0, float(size[1]) / 2.0
        for local_x in (-half_x, half_x):
            for local_y in (-half_y, half_y):
                corners.append((
                    float(pose[0]) + cosine * local_x - sine * local_y,
                    float(pose[1]) + sine * local_x + cosine * local_y,
                ))
    if not corners:
        raise ValueError("at least one wall is required")
    return (
        min(point[0] for point in corners),
        max(point[0] for point in corners),
        min(point[1] for point in corners),
        max(point[1] for point in corners),
    )


def reachable_map_metrics(
    data,
    width: int,
    height: int,
    resolution: float,
    origin_xy,
    walls,
    spawn_xy,
    required_clearance_m: float,
    *,
    sampling_m: float = 0.01,
) -> dict:
    """Audit the mapped robot-center component without requiring sealed space."""
    if (
        width <= 0
        or height <= 0
        or len(data) != width * height
        or not math.isfinite(resolution)
        or resolution <= 0.0
        or not math.isfinite(sampling_m)
        or sampling_m <= 0.0
        or not math.isfinite(required_clearance_m)
        or required_clearance_m < 0.0
    ):
        raise ValueError("valid map and sampling geometry are required")
    min_x, max_x, min_y, max_y = _wall_bounds(walls)
    columns = max(1, int(math.ceil((max_x - min_x) / sampling_m)))
    rows = max(1, int(math.ceil((max_y - min_y) / sampling_m)))

    def world(row: int, column: int) -> tuple[float, float]:
        return (
            min_x + (column + 0.5) * sampling_m,
            min_y + (row + 0.5) * sampling_m,
        )

    free = [False] * (rows * columns)
    for row in range(rows):
        for column in range(columns):
            free[row * columns + column] = (
                center_clearance(world(row, column), walls)
                > required_clearance_m
            )
    spawn_column = int((float(spawn_xy[0]) - min_x) // sampling_m)
    spawn_row = int((float(spawn_xy[1]) - min_y) // sampling_m)
    if not (0 <= spawn_row < rows and 0 <= spawn_column < columns):
        raise ValueError("spawn is outside the measured wall bounds")
    spawn_index = spawn_row * columns + spawn_column
    if not free[spawn_index]:
        raise ValueError("spawn is not inside the robot-reachable space")

    queue = deque([(spawn_row, spawn_column)])
    reached = {spawn_index}
    while queue:
        row, column = queue.popleft()
        for next_row, next_column in (
            (row - 1, column), (row + 1, column),
            (row, column - 1), (row, column + 1),
        ):
            if not (0 <= next_row < rows and 0 <= next_column < columns):
                continue
            index = next_row * columns + next_column
            if free[index] and index not in reached:
                reached.add(index)
                queue.append((next_row, next_column))

    origin_x, origin_y = (float(value) for value in origin_xy)
    unknown = occupied = outside = 0
    for index in reached:
        row, column = divmod(index, columns)
        x, y = world(row, column)
        map_column = math.floor((x - origin_x) / resolution)
        map_row = math.floor((y - origin_y) / resolution)
        if not (0 <= map_row < height and 0 <= map_column < width):
            outside += 1
            unknown += 1
            continue
        value = int(data[map_row * width + map_column])
        if value < 0:
            unknown += 1
        elif value >= 65:
            occupied += 1
    count = len(reached)
    unknown_fraction = unknown / count
    occupied_fraction = occupied / count
    outside_fraction = outside / count
    return {
        "definition": "spawn_connected_robot_center_configuration_space",
        "required_center_clearance_m": required_clearance_m,
        "sampling_m": sampling_m,
        "sample_count": count,
        "unknown_fraction": unknown_fraction,
        "occupied_fraction": occupied_fraction,
        "outside_raster_fraction": outside_fraction,
        "mapping_complete": (
            unknown_fraction <= 0.01
            and occupied_fraction <= 0.01
            and outside_fraction <= 0.01
        ),
    }


def _wall_edge_points(wall: dict, step_m: float):
    pose, size = wall["pose"], wall["size"]
    half_x, half_y = float(size[0]) / 2.0, float(size[1]) / 2.0
    cosine, sine = math.cos(float(pose[5])), math.sin(float(pose[5]))

    def world(local_x, local_y):
        return (
            float(pose[0]) + cosine * local_x - sine * local_y,
            float(pose[1]) + sine * local_x + cosine * local_y,
        )

    points = []
    for length, fixed, horizontal in (
        (2.0 * half_x, half_y, True),
        (2.0 * half_x, -half_y, True),
        (2.0 * half_y, half_x, False),
        (2.0 * half_y, -half_x, False),
    ):
        count = max(2, int(math.ceil(length / step_m)) + 1)
        for index in range(count):
            value = -length / 2.0 + length * index / (count - 1)
            points.append(world(value, fixed) if horizontal else world(fixed, value))
    return points


def map_fidelity_metrics(
    data,
    width: int,
    height: int,
    resolution: float,
    origin_xy,
    walls,
    *,
    wall_sampling_m: float = 0.01,
    wall_tolerance_m: float = 0.05,
) -> dict:
    """Report full measured-wall fidelity without redefining reachable space."""
    if (
        width <= 0
        or height <= 0
        or len(data) != width * height
        or resolution <= 0.0
        or wall_sampling_m <= 0.0
        or wall_tolerance_m <= 0.0
    ):
        raise ValueError("valid map and fidelity sampling are required")
    origin_x, origin_y = (float(value) for value in origin_xy)
    occupied = []
    for row in range(height):
        for column in range(width):
            if int(data[row * width + column]) >= 65:
                occupied.append((
                    origin_x + (column + 0.5) * resolution,
                    origin_y + (row + 0.5) * resolution,
                ))
    recalls = []
    for wall in walls:
        edge = _wall_edge_points(wall, wall_sampling_m)
        hits = 0
        for point in edge:
            if occupied and min(math.dist(point, item) for item in occupied) <= wall_tolerance_m:
                hits += 1
        recalls.append(hits / len(edge))
    min_x, max_x, min_y, max_y = _wall_bounds(walls)
    inside = [
        point for point in occupied
        if min_x <= point[0] <= max_x and min_y <= point[1] <= max_y
    ]
    phantom = (
        sum(center_clearance(point, walls) > wall_tolerance_m for point in inside)
        / len(inside)
        if inside else 0.0
    )
    minimum_recall = min(recalls) if recalls else 0.0
    return {
        "wall_surface_recall": recalls,
        "minimum_wall_surface_recall": minimum_recall,
        "phantom_fraction": phantom,
        "wall_sampling_m": wall_sampling_m,
        "wall_tolerance_m": wall_tolerance_m,
        "full_raster_fidelity_passed": (
            minimum_recall >= 0.98 and phantom < 0.02
        ),
    }


def road_observation_score(observation: dict) -> int:
    """Count semantic road features visible in one camera observation."""
    if not isinstance(observation, dict):
        return 0
    return sum(
        observation.get(name, {}).get("visible") is True
        for name in ("lane", "stop_line", "crosswalk")
    )


def evaluate_acceptance(evidence: dict, *, clearance_margin_m: float) -> dict:
    if not math.isfinite(clearance_margin_m) or clearance_margin_m < 0.0:
        raise ValueError("clearance margin must be finite and nonnegative")
    body_clearance = evidence.get("minimum_body_clearance_m")
    publishers = evidence.get("cmd_vel_publishers") or []
    gates = {
        "mapping_route_complete": evidence.get("mapping_complete") is True,
        "map_received": evidence.get("map_received") is True,
        "robot_reachable_mapping": (
            evidence.get("reachable_mapping_complete") is True
        ),
        "trajectory_clearance": (
            isinstance(body_clearance, (int, float))
            and math.isfinite(float(body_clearance))
            and float(body_clearance) >= clearance_margin_m
            and evidence.get("collision") is False
        ),
        "gazebo_camera_frames": int(evidence.get("camera_frames") or 0) > 0,
        "white_line_detected": (
            evidence.get("line_visible") is True
            and float(evidence.get("line_confidence") or 0.0) >= 0.8
        ),
        "white_line_seen_while_moving": (
            evidence.get("line_visible_while_moving") is True
        ),
        "road_lane_detected": evidence.get("road_lane_visible") is True,
        "stop_line_detected": evidence.get("stop_line_visible") is True,
        "crosswalk_detected": evidence.get("crosswalk_visible") is True,
        "nav2_probe": evidence.get("nav2_passed") is True,
        "sole_final_cmd_vel_publisher": (
            len(publishers) == 1
            and str(publishers[0]).rstrip("/").split("/")[-1] == "core"
        ),
        "final_zero_stable": evidence.get("final_zero_stable") is True,
    }
    return {"passed": all(gates.values()), "gates": gates}
