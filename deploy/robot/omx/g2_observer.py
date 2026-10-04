"""Independent measurement process: subscribes only, never sends a ROS/Gazebo goal."""
import argparse
import json
import math
import threading
import time
import uuid

from g2_common import ClockProgress, canonical_digest


class Observations:
    def __init__(self, *, max_age_s=0.5, open_position=1.0):
        self.max_age_s, self.open_position = max_age_s, open_position
        self.lock = threading.Lock()
        self.models = {}
        self.gripper = None
        self.clock = None
        self.progress = ClockProgress(monotonic=lambda: time.monotonic())

    def pose(self, message):
        received = time.time()
        with self.lock:
            for item in message.pose:
                q = item.orientation
                # Gazebo quaternions are measurements; world=link0 is pinned by the cell.
                roll = math.atan2(2*(q.w*q.x + q.y*q.z), 1-2*(q.x*q.x+q.y*q.y))
                pitch = math.asin(max(-1., min(1., 2*(q.w*q.y-q.z*q.x))))
                yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
                self.models[item.name] = (received, {
                    "x_m": float(item.position.x), "y_m": float(item.position.y),
                    "z_m": float(item.position.z), "roll_rad": roll,
                    "pitch_rad": pitch, "yaw_rad": yaw})

    def joints(self, message):
        if "gripper_joint_1" in message.name:
            index = message.name.index("gripper_joint_1")
            if index < len(message.position):
                with self.lock:
                    self.gripper = (time.time(), float(message.position[index]))

    def clocks(self, message):
        stamp = message.clock.sec + message.clock.nanosec / 1e9
        with self.lock:
            self.progress.observe(stamp)
            self.clock = (time.time(), stamp)

    def read(self, model, *, require_open):
        with self.lock:
            now = time.time()
            if (self.clock is None or now-self.clock[0] > self.max_age_s
                    or not self.progress.fresh(self.max_age_s)):
                raise RuntimeError("independent simulation clock is stale or not advancing")
            if model not in self.models or now-self.models[model][0] > self.max_age_s:
                raise RuntimeError("measured model pose absent or stale")
            if self.gripper is None or now-self.gripper[0] > self.max_age_s:
                raise RuntimeError("independent gripper measurement stale")
            if require_open and abs(self.gripper[1]-self.open_position) > 0.05:
                raise RuntimeError("measured gripper is not OPEN")
            result = {"model_id": model, "observed_at": self.models[model][0],
                      "model_pose_base": dict(self.models[model][1]),
                      "gripper_observed_at": self.gripper[0], "gripper_position": self.gripper[1],
                      "clock": self.clock[1], "clock_advances": self.progress.advances,
                      "observation_id": uuid.uuid4().hex, "sim_gripper_sensor": True}
            result["observation_digest"] = canonical_digest(result)
            return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--open-position", required=True, type=float)
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import JointState
    from rosgraph_msgs.msg import Clock
    from gz.transport13 import Node as GzNode
    from gz.msgs10.pose_v_pb2 import Pose_V
    rclpy.init()
    node = rclpy.create_node("rosy_g2_independent_observer")
    observations = Observations(open_position=args.open_position)
    node.create_subscription(JointState, "/joint_states", observations.joints, qos_profile_sensor_data)
    node.create_subscription(Clock, "/clock", observations.clocks, qos_profile_sensor_data)
    gz = GzNode()
    if not gz.subscribe(Pose_V, "/world/omx_cell_workcell/pose/info", observations.pose):
        raise RuntimeError("Gazebo pose subscription refused")
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    import os
    import socketserver

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(2)
            line = self.rfile.readline(4097)
            if len(line) > 4096:
                return
            try:
                request = json.loads(line)
                result = {"ok": True, "observation": observations.read(
                    request["model"], require_open=request["require_open"])}
            except (ValueError, KeyError, RuntimeError) as exc:
                result = {"ok": False, "error": str(exc)}
            self.wfile.write(json.dumps(result, allow_nan=False).encode()+b"\n")
    server = socketserver.UnixStreamServer(args.socket, Handler)
    os.chmod(args.socket, 0o600)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        executor.shutdown(timeout_sec=2)
        node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
