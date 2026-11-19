#!/usr/bin/env python3
"""Native LeRobot Factory Wiring & CLI Session Runner (`guarded_native_cli.py`).

Single Responsibility:
  - Wraps native LeRobot `make_robot_from_config` / `make_teleoperator_from_config` / `build_dataset_frame`
    factories (`run_native`) so `OmxFollower` and `OmxLeader` use passive connection (`connect_passive`),
    real-time guarded streaming (`NativeJointMotion`), and fail-closed cleanup (`close_device`).
  - CLI entrypoint (`main`) for `record [--teacher]` and `teleoperate [--body-only]`.
"""
from __future__ import annotations

import importlib
import sys

from guarded_device import close_device, connect_passive


def _gn_attr(name: str, default):
    for mod_name in ("guarded_native", "omx_guard_test"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, name):
            return getattr(mod, name)
    return default


def run_native(module, follower_type, leader_type, *, body_only=False, teacher=False):
    """Keep native factories/recording; replace only hardware lifecycle and action guard."""
    from guarded_native import NativeJointMotion

    devices = []
    if body_only and hasattr(module, "record"):
        raise ValueError("body-only mode is manual teleoperation only")
    if teacher and not hasattr(module, "record"):
        raise ValueError("teacher mode is a recording")
    shared = {}
    original_robot = module.make_robot_from_config
    original_teleop = module.make_teleoperator_from_config

    class Follower(follower_type):
        def connect(self, calibrate=True):
            _gn_attr("connect_passive", connect_passive)(self, follower=True)

        def send_action(self, action):
            if "motion" not in shared:
                from motor_health import MotorHealth

                motion_cls = _gn_attr("NativeJointMotion", NativeJointMotion)
                shared["motion"] = motion_cls(
                    self.bus,
                    None if teacher else shared["leader"].bus,
                    body_only=body_only,
                    teacher=teacher,
                    monitor=MotorHealth(),
                )
            sent = shared["motion"].send(action)
            shared["sent"] = sent
            return sent

        def disconnect(self):
            _gn_attr("close_device", close_device)(self)

    class Leader(leader_type):
        def connect(self, calibrate=True):
            _gn_attr("connect_passive", connect_passive)(self, follower=False)

        def disconnect(self):
            _gn_attr("close_device", close_device)(self)

    def robot_factory(config):
        device = original_robot(config)
        if not isinstance(device, follower_type) or getattr(config, "use_degrees", False):
            raise ValueError("guard supports only normalized OMX follower manual control")
        device.__class__ = Follower
        devices.append(device)
        return device

    def teleop_factory(config):
        device = original_teleop(config)
        if teacher:
            if isinstance(device, leader_type):
                raise ValueError("teacher mode replays a trajectory, not a leader")
            return device
        if not isinstance(device, leader_type):
            raise ValueError("guard requires OMX leader")
        device.__class__ = Leader
        devices.append(device)
        shared["leader"] = device
        return device

    module.make_robot_from_config = robot_factory
    module.make_teleoperator_from_config = teleop_factory
    original_frame = getattr(module, "build_dataset_frame", None)
    if original_frame is not None:

        def frame(features, values, prefix):
            if prefix == module.ACTION:
                values = shared["sent"]
            return original_frame(features, values, prefix=prefix)

        module.build_dataset_frame = frame
    fault = None
    try:
        return module.main()
    except BaseException as exc:
        fault = exc
        raise
    finally:
        errors = []
        close_fn = _gn_attr("close_device", close_device)
        for device in reversed(devices):
            try:
                close_fn(device)
            except Exception as exc:
                errors.append(exc)
        module.make_robot_from_config, module.make_teleoperator_from_config = original_robot, original_teleop
        if original_frame is not None:
            module.build_dataset_frame = original_frame
        motion = shared.get("motion")
        if fault is not None and motion is not None and not motion.failed:
            motion.report_fault(fault)
        if motion is not None and motion.monitor is not None:
            try:
                motion.monitor.end()
            except BaseException:
                pass
        if errors:
            raise RuntimeError(f"native cleanup failed: {errors}")


def main():
    mode = sys.argv.pop(1)
    teacher = "--teacher" in sys.argv
    if teacher:
        sys.argv.remove("--teacher")
        if mode != "record":
            raise SystemExit("teacher mode is a recording")
    body_only = "--body-only" in sys.argv
    if body_only:
        sys.argv.remove("--body-only")
        if mode != "teleoperate":
            raise SystemExit("body-only mode is manual teleoperation only")
    if mode not in ("record", "teleoperate"):
        raise SystemExit("expected record or teleoperate")
    from lerobot.robots.omx_follower.omx_follower import OmxFollower
    from lerobot.teleoperators.omx_leader.omx_leader import OmxLeader

    module = importlib.import_module("lerobot.scripts.lerobot_" + mode)
    run_native(module, OmxFollower, OmxLeader, body_only=body_only, teacher=teacher)
