"""Private, simulation-only G2 composition configuration; no production entrypoint."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
SOURCE_PATHS = (
    "contracts/foundation", "contracts/skill/src", "operations/execution/src",
    "operations/processes/palletizing/src", "middleware/skills/api/src",
    "middleware/skills/manipulation/src", "middleware/apps/device/omx/adapter",
    "middleware/apps/device/omx/agent/src", "integrations/robots/omx/src",
    "operations/fleet",
)


def configure_imports():
    candidate = [str(ROOT / part) for part in SOURCE_PATHS]
    sys.path[:] = candidate + [path for path in sys.path if path not in candidate]


def verify_module_origins(expected):
    """A hash of unused candidate source cannot prove which Python module executed."""
    import importlib
    origins = {}
    for name, relative_root in expected.items():
        module = importlib.import_module(name)
        actual = getattr(module, "__file__", None)
        root = (ROOT / relative_root).resolve()
        if actual is None or not Path(actual).resolve().is_relative_to(root):
            raise RuntimeError("candidate source import origin mismatch: "+name)
        origins[name] = str(Path(actual).resolve().relative_to(ROOT))
    return origins


class ClockProgress:
    """Fresh publications of an identical clock do not prove simulator progress."""
    def __init__(self, *, monotonic=time.monotonic):
        self.monotonic = monotonic
        self.stamp = None
        self.advances = 0
        self.last_advance = None

    def observe(self, stamp):
        if self.stamp is not None and stamp > self.stamp:
            self.advances += 1
            self.last_advance = self.monotonic()
        elif self.stamp is not None and stamp < self.stamp:
            self.advances, self.last_advance = 0, None
        self.stamp = stamp

    def fresh(self, max_age_s):
        return (self.advances >= 2 and self.last_advance is not None
                and 0 <= self.monotonic()-self.last_advance <= max_age_s)


def canonical_digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def box_only_document(original):
    """Explicit derived scenario: original sheets and human checkpoint remain untested."""
    value = json.loads(json.dumps(original))
    value.pop("slip_sheet", None)
    for layer in value["layers"]:
        layer.pop("slip_sheet_below", None)
    value["name"] = "g2-box-only-16"
    return value


def prepare_world(source, destination):
    """Remove only initial loose demo items before any grants, preserve cell geometry."""
    tree = ET.parse(source)
    world = tree.getroot().find("world")
    if world is None or world.attrib.get("name") != "omx_cell_workcell":
        raise ValueError("unexpected simulation world identity")
    removed = []
    for model in tuple(world.findall("model")):
        if model.attrib.get("name") in {"infeed_block", "slip_sheet_0"}:
            removed.append(model.attrib["name"])
            world.remove(model)
    if set(removed) != {"infeed_block", "slip_sheet_0"}:
        raise ValueError("canonical initial loose items changed; review required")
    destination = Path(destination)
    with destination.open("xb") as stream:
        tree.write(stream, encoding="utf-8", xml_declaration=True)
    return {"source_sha256": sha256(Path(source).read_bytes()).hexdigest(),
            "derived_sha256": sha256(destination.read_bytes()).hexdigest(),
            "removed_before_grants": removed, "sim_aid": True}


def controller_readiness(timeout_s=60):
    """Read-only ROS gate, before an owner/proposal/grant is started."""
    import time
    import rclpy
    from controller_manager_msgs.srv import ListControllers
    from sensor_msgs.msg import JointState
    from rosgraph_msgs.msg import Clock
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.action import ActionClient
    from control_msgs.action import FollowJointTrajectory
    rclpy.init()
    node = rclpy.create_node("rosy_g2_readiness")
    latest = {"joints": None, "clock": None}
    progress = ClockProgress()

    def joints(message):
        latest["joints"] = (time.monotonic(), message)

    def clocks(message):
        stamp = message.clock.sec+message.clock.nanosec/1e9
        progress.observe(stamp)
        latest["clock"] = (time.monotonic(), stamp)

    node.create_subscription(JointState, "/joint_states", joints, qos_profile_sensor_data)
    node.create_subscription(Clock, "/clock", clocks, qos_profile_sensor_data)
    client = node.create_client(ListControllers, "/controller_manager/list_controllers")
    action = ActionClient(node, FollowJointTrajectory, "/arm_controller/follow_joint_trajectory")
    deadline, active, future = time.monotonic()+timeout_s, set(), None
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if future is None and client.service_is_ready():
                future = client.call_async(ListControllers.Request())
            if future is not None and future.done():
                response = future.result()
                active = {item.name for item in response.controller if item.state == "active"}
                future = None
            now = time.monotonic()
            joint = latest["joints"]
            if (active >= {"arm_controller", "joint_state_broadcaster"} and action.server_is_ready()
                    and latest["clock"] and now-latest["clock"][0] <= 0.5 and progress.fresh(0.5)
                    and joint and now-joint[0] <= 0.5
                    and {"joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"}
                    <= set(joint[1].name)):
                return {"controllers": sorted(active), "clock_advances": progress.advances,
                        "joint_names": list(joint[1].name), "action_server_ready": True}
        raise RuntimeError("read-only controller/clock/joint-state readiness timed out")
    finally:
        action.destroy()
        node.destroy_node()
        rclpy.shutdown()
