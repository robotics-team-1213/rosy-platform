#!/usr/bin/env python3
"""One native LeRobot recorder for two guarded OMX leader/follower pairs."""
import importlib
import argparse
import json
from pathlib import Path
import sys

from guarded_native import NativeJointMotion, NAMES, close_device, connect_passive, finite_values, torque_off
from motor_health import MotorHealth

ARMS = ("arm_a", "arm_b")


def prefixed(name, values):
    return {name + "." + key: value for key, value in values.items()}


class BimanualMotion:
    def __init__(self, motions):
        if set(motions) != set(ARMS):
            raise ValueError("exactly arm_a and arm_b are required")
        self.motions = motions

    def send(self, action):
        try:
            finite_values(action, [arm + "." + n + ".pos" for arm in ARMS for n in NAMES])
            prepared = {}
            for arm in ARMS:
                values = {key.removeprefix(arm + "."): value for key, value in action.items()
                          if key.startswith(arm + ".")}
                try:
                    prepared[arm] = self.motions[arm].prepare(values)
                except ValueError as exc:
                    raise ValueError(f"{arm}: {exc}") from exc
            sent = {}
            for arm in ARMS:
                sent.update(prefixed(arm, self.motions[arm].commit(prepared[arm])))
            return sent
        except BaseException as cause:
            errors = []
            for motion in self.motions.values():
                motion.failed = True
                for bus in (motion.follower, motion.leader):
                    try:
                        torque_off(bus)
                    except Exception as exc:
                        errors.append(exc)
            for motion in self.motions.values():
                motion.report_fault(cause)
            if errors:
                raise RuntimeError(f"bimanual torque OFF failed: {errors}") from cause
            raise


def close_all(devices, cameras=()):
    errors = []
    for device in devices:
        try:
            close_device(device)
        except Exception as exc:
            errors.append(exc)
    for camera in cameras:
        try:
            if camera.is_connected:
                camera.disconnect()
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise RuntimeError(f"bimanual cleanup failed: {errors}")


def make_adapters(robot_base, teleop_base, robot_factory, leader_factory, camera_factory):
    class Follower(robot_base):
        name = "bi_omx_follower"
        config_class = None

        def __init__(self, config):
            super().__init__(config)
            for name in ARMS:
                child = getattr(config, name)
                if child.type != "omx_follower" or child.use_degrees or child.cameras:
                    raise ValueError("bimanual children must be normalized OMX followers without cameras")
            self.arms = {name: robot_factory(getattr(config, name)) for name in ARMS}
            self.cameras = camera_factory(config.cameras)
            self.motion = None
            self.leader = None
            self.monitor = None

        @property
        def action_features(self):
            return {key: value for name in ARMS for key, value in prefixed(name, self.arms[name].action_features).items()}

        @property
        def observation_features(self):
            features = {key: value for name in ARMS
                        for key, value in prefixed(name, self.arms[name].observation_features).items()}
            return {**features, **{name: (cam.height, cam.width, 3) for name, cam in self.cameras.items()}}

        @property
        def is_connected(self):
            return all(d.bus.is_connected for d in self.arms.values()) and all(c.is_connected for c in self.cameras.values())

        @property
        def is_calibrated(self):
            return all(d.bus.is_calibrated for d in self.arms.values())

        def connect(self, calibrate=True):
            try:
                for device in self.arms.values():
                    connect_passive(device, follower=True)
                for camera in self.cameras.values():
                    camera.connect()
            except BaseException:
                self.disconnect()
                raise

        def calibrate(self):
            raise RuntimeError("commission each OMX arm explicitly before bimanual use")

        def configure(self):
            raise RuntimeError("use passive connect; automatic motor configuration is disabled")

        def get_observation(self):
            values = {key: value for name in ARMS
                      for key, value in prefixed(name, self.arms[name].get_observation()).items()}
            return {**values, **{name: camera.read_latest() for name, camera in self.cameras.items()}}

        def send_action(self, action):
            if self.motion is None:
                if self.leader is None or not self.leader.is_connected:
                    raise ValueError("both passive leaders must be connected")
                self.motion = BimanualMotion({name: NativeJointMotion(self.arms[name].bus, self.leader.arms[name].bus,
                                                               label=name, monitor=self.monitor)
                                             for name in ARMS})
            return self.motion.send(action)

        def disconnect(self):
            close_all(self.arms.values(), self.cameras.values())

    class Leader(teleop_base):
        name = "bi_omx_leader"
        config_class = None

        def __init__(self, config):
            super().__init__(config)
            if any(getattr(config, name).type != "omx_leader" for name in ARMS):
                raise ValueError("bimanual leaders must both be OMX leaders")
            self.arms = {name: leader_factory(getattr(config, name)) for name in ARMS}

        @property
        def action_features(self):
            return {key: value for name in ARMS for key, value in prefixed(name, self.arms[name].action_features).items()}

        @property
        def feedback_features(self):
            return {}

        @property
        def is_connected(self):
            return all(d.bus.is_connected for d in self.arms.values())

        @property
        def is_calibrated(self):
            return all(d.bus.is_calibrated for d in self.arms.values())

        def connect(self, calibrate=True):
            try:
                for device in self.arms.values():
                    connect_passive(device, follower=False)
            except BaseException:
                self.disconnect()
                raise

        def calibrate(self):
            raise RuntimeError("commission each OMX leader explicitly before bimanual use")

        def configure(self):
            raise RuntimeError("use passive connect; automatic motor configuration is disabled")

        def get_action(self):
            return {key: value for name in ARMS for key, value in prefixed(name, self.arms[name].get_action()).items()}

        def send_feedback(self, feedback):
            raise NotImplementedError("OMX leaders remain passive")

        def disconnect(self):
            close_all(self.arms.values())

    return Follower, Leader


def register_types():
    from dataclasses import dataclass, field
    from lerobot.cameras import CameraConfig
    from lerobot.cameras.utils import make_cameras_from_configs
    from lerobot.robots import Robot, RobotConfig, make_robot_from_config
    from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig
    from lerobot.teleoperators import Teleoperator, TeleoperatorConfig, make_teleoperator_from_config
    from lerobot.teleoperators.omx_leader.config_omx_leader import OmxLeaderConfig

    @RobotConfig.register_subclass("bi_omx_follower")
    @dataclass(kw_only=True)
    class FollowerConfig(RobotConfig):
        arm_a: OmxFollowerConfig
        arm_b: OmxFollowerConfig
        cameras: dict[str, CameraConfig] = field(default_factory=dict)

    @TeleoperatorConfig.register_subclass("bi_omx_leader")
    @dataclass(kw_only=True)
    class LeaderConfig(TeleoperatorConfig):
        arm_a: OmxLeaderConfig
        arm_b: OmxLeaderConfig

    Follower, Leader = make_adapters(Robot, Teleoperator, make_robot_from_config,
                                      make_teleoperator_from_config, make_cameras_from_configs)
    Follower.config_class, Leader.config_class = FollowerConfig, LeaderConfig
    return Follower, Leader


def run_native(module, follower_type, leader_type, invoke=None):
    devices = {}
    original_robot, original_leader = module.make_robot_from_config, module.make_teleoperator_from_config
    original_frame = getattr(module, "build_dataset_frame", None)
    sent = {}

    def make_robot(config):
        device = follower_type(config)
        devices["robot"] = device
        if "leader" in devices:
            device.leader = devices["leader"]
        return device

    def make_leader(config):
        device = leader_type(config)
        devices["leader"] = device
        if "robot" in devices:
            devices["robot"].leader = device
        return device

    module.make_robot_from_config, module.make_teleoperator_from_config = make_robot, make_leader
    if original_frame is not None:
        def frame(features, values, prefix):
            if prefix == module.ACTION:
                values = sent["action"]
            return original_frame(features, values, prefix=prefix)
        module.build_dataset_frame = frame
    original_send = follower_type.send_action
    def send_action(self, action):
        if self.monitor is None:
            self.monitor = MotorHealth()
        actual = original_send(self, action)
        sent["action"] = actual
        return actual
    follower_type.send_action = send_action
    fault = None
    try:
        return (invoke or module.main)()
    except BaseException as exc:
        fault = exc
        raise
    finally:
        errors = []
        for device in devices.values():
            try:
                device.disconnect()
            except Exception as exc:
                errors.append(exc)
        module.make_robot_from_config, module.make_teleoperator_from_config = original_robot, original_leader
        follower_type.send_action = original_send
        if original_frame is not None:
            module.build_dataset_frame = original_frame
        motion = getattr(devices.get("robot"), "motion", None)
        if fault is not None and motion is not None:
            for arm in motion.motions.values():
                if not arm.failed:
                    arm.report_fault(fault)
        monitor = getattr(devices.get('robot'), 'monitor', None)
        if monitor is not None:
            try:
                monitor.end()
            except BaseException:
                pass  # The parent finalizes the bound snapshot after its independent OFF cleanup.
        if errors:
            raise RuntimeError(f"bimanual native cleanup failed: {errors}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("record", "teleoperate"))
    parser.add_argument("--config_path", required=True, type=Path)
    args = parser.parse_args()
    Follower, Leader = register_types()
    module = importlib.import_module("lerobot.scripts.lerobot_" + args.mode)
    import draccus
    config_type = module.RecordConfig if args.mode == "record" else module.TeleoperateConfig
    config = draccus.decode(config_type, json.loads(args.config_path.read_text(encoding="utf-8-sig")))
    entry = module.record if args.mode == "record" else module.teleoperate
    # Native ChoiceWrapper recursively enumerates the bimanual registry; the loop needs only typed config.
    run_native(module, Follower, Leader, invoke=lambda: entry.__wrapped__(config))


if __name__ == "__main__":
    main()
