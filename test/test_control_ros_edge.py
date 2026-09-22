"""D-171: in control, ROS types live at the node edge.

A control module may import ROS (rclpy, *_msgs, tf2_ros, ...) only if it is
(a) a node module — it defines a class deriving from Node — or (b) a named
edge adapter whose job is ROS itself. Every other module keeps its decisions
ROS-free so host pytest can import it (2026-09-06 criterion C1): it returns
values, and the node builds the messages.

KNOWN_ROS_LEAKS is the ratchet (D-168 P5): checked by set equality, so a new
leak fails and so does a fixed leak left on the list. Baseline 2026-09-22:
16 leaks holding 1,339 decisions in 3,345 lines; see
docs/plans/2026-09-22-control-structural-evaluation.md.

Honest holes, not oversights:
- Only direct imports are checked. A module that imports a leaking module is
  bound too; fixing the leak frees it, which is the point of the order.
- ``tools/`` (simulation rigs) and ``map/`` bundles are out of scope.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "apps" / "control"
LIB = PKG / "control"

ROS_TOPS = {
    "rclpy", "std_msgs", "geometry_msgs", "nav_msgs", "sensor_msgs", "tf2_ros", "visualization_msgs",
    "rcl_interfaces", "std_srvs", "slam_toolbox", "nav2_msgs", "ament_index_python", "builtin_interfaces",
    "cv_bridge", "message_filters", "tf2_geometry_msgs", "action_msgs",
}

#: (b) Modules whose job is ROS: they adapt a ROS facility for the nodes.
EDGE_ADAPTERS = {
    "control.tf_buffer": "wraps tf2_ros.Buffer for every node",
    "control.web_map_control": "slam_toolbox reset/pause service client for web_node",
    "control.sensor_provider": "D-126 entry point core loads; it constructs the sensor-only ROS worker",
}

#: Ratchet: library modules that build ROS messages themselves (D-171 track 1).
KNOWN_ROS_LEAKS = {
    "control.wander.navigator": "Twist/String/Path, TF lookups",
    "control.calibration_rotation": "one Twist",
    "control.wander.motion": "Twist, rclpy Parameter",
    "control.wander.judge": "Twist",
    "control.wander.senses": "Bool/Float32/Odometry/UInt16MultiArray",
    "control.calibration_relocation": "Twist, String",
    "control.calibration_atomic": "one String",
    "control.safety.bumper": "Float32/LaserScan/Range, TF",
    "control.wander.contact": "Twist",
    "control.safety.hazard": "Bool/Imu/String/Twist/UInt16MultiArray",
    "control.goal_escape": "String",
    "control.safety.gate": "Twist, rclpy Parameter",
    "control.safety.scale": "Float32",
    "control.safety.evidence": "String",
    "control.safety.obstacles": "String, TF",
    "control.wander.obstacles": "String",
}


def _modules():
    for path in sorted(LIB.rglob("*.py")):
        if any(p.startswith(".") or p == "__pycache__" for p in path.parts):
            continue
        rel = path.relative_to(PKG).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        yield ".".join(parts), path


def _classify(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ros = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            ros |= any(a.name.split(".")[0] in ROS_TOPS for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            ros |= node.module.split(".")[0] in ROS_TOPS
    is_node = any(
        isinstance(n, ast.ClassDef) and any(
            (isinstance(b, ast.Name) and b.id == "Node") or (isinstance(b, ast.Attribute) and b.attr == "Node")
            for b in n.bases)
        for n in ast.walk(tree))
    return ros, is_node


def _leaks():
    found = set()
    for name, path in _modules():
        ros, is_node = _classify(path)
        if ros and not is_node and name not in EDGE_ADAPTERS:
            found.add(name)
    return found


def test_the_scan_sees_nodes_and_libraries():
    kinds = [_classify(path) for _, path in _modules()]
    assert sum(is_node for _, is_node in kinds) >= 10
    assert sum(not ros for ros, _ in kinds) >= 100


def test_ros_types_stay_at_the_node_edge():
    leaks = _leaks()
    assert leaks == set(KNOWN_ROS_LEAKS), (
        f"new ROS import outside a node: {sorted(leaks - set(KNOWN_ROS_LEAKS))} — return values and let "
        f"the node build messages (D-171); fixed, remove from KNOWN_ROS_LEAKS: "
        f"{sorted(set(KNOWN_ROS_LEAKS) - leaks)}"
    )


def test_edge_adapters_still_need_ros():
    modules = dict(_modules())
    stale = [name for name in EDGE_ADAPTERS if name not in modules or not _classify(modules[name])[0]]
    assert stale == [], stale
