#!/usr/bin/env python3
"""Configuration, caps, gains and bus ownership for the two-arm OMX pipeline.

The pipeline itself (`two_arm_pipeline.py`) owns the stages and the receipts; this module owns
what a config or a servo state means: the arm pair, the schema check, the Follower caps and
gains that a run raises and restores, the Leader's gravity bias, and the pose and bus helpers.

Caps and gains are servo state, not pipeline state: a Follower cap lives in EEPROM (writable
only with torque OFF) and a gain is a RAM register that resets on power-up, so every run reads
what is there before it writes, and restores it on every exit.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guarded_native  # noqa: E402
from guarded_native import BODY, TURN, connect_passive  # noqa: E402
from joint_tune import FOLLOWER as FOLLOWER_MODELS  # noqa: E402
from leader_actuator import (  # noqa: E402
    CAP_MAX, CURRENT_MAX, DEFAULT_CURRENT, DEFAULT_PWM, GRAVITY_MAX_TICKS)

SCHEMA = "rosy.omx-two-arm-pipeline/1"
POSE_SCHEMA = "rosy.omx-two-arm-poses/1"
#: The Follower is aligned when every joint is within this many degrees of the Leader.
ALIGN_TOLERANCE_DEG = 2.5
#: The highest position gain a run may ask for; the servo accepts 0..16383.
GAIN_MAX = 2000


class Arm:
    """One Follower/Leader pair and the buses the pipeline owns for the run."""

    def __init__(self, arm_id: str, follower, leader):
        self.arm_id = arm_id
        self.follower = follower
        self.leader = leader

    @property
    def follower_bus(self):
        return self.follower.bus

    @property
    def leader_bus(self):
        return self.leader.bus


# --------------------------------------------------------------------- configuration


def load_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_config(config: dict) -> None:
    """The config names the two buses of every arm; nothing else is invented here."""
    if config.get("schema") != SCHEMA:
        raise ValueError(f"config schema must be {SCHEMA}")
    arms = config.get("arms")
    if not isinstance(arms, dict) or not arms:
        raise ValueError("config needs at least one arm")
    for arm_id, arm in arms.items():
        for role in ("follower", "leader"):
            port = arm.get(role)
            if not isinstance(port, str) or not port.startswith("/dev/serial/by-id/"):
                raise ValueError(f"{arm_id}.{role} must be a physically confirmed /dev/serial/by-id path")
    limits = config.get("limits", {})
    if not 0 < float(limits.get("tolerance_deg", ALIGN_TOLERANCE_DEG)) <= 10:
        raise ValueError("limits.tolerance_deg must be 0..10 degrees")
    for section in ("leader_drive", "follower_caps"):
        caps = config.get(section, {})
        pwm = int(caps.get("pwm", DEFAULT_PWM))
        current = int(caps.get("current", DEFAULT_CURRENT))
        if not 1 <= pwm <= CAP_MAX or not 1 <= current <= CURRENT_MAX:
            raise ValueError(f"{section} caps must be 1..{CAP_MAX} PWM and 1..{CURRENT_MAX} current")
    overrides = config.get("follower_caps", {}).get("per_joint", {})
    if not isinstance(overrides, dict):
        raise ValueError("follower_caps.per_joint must be an object keyed by body joint")
    for name, values in overrides.items():
        if name not in BODY:
            raise ValueError(f"follower_caps.per_joint names no body joint: {name}")
        if not isinstance(values, dict) or not values:
            raise ValueError(f"follower_caps.per_joint.{name} must set pwm and/or current")
        for register, value in values.items():
            if register not in ("pwm", "current"):
                raise ValueError(f"follower_caps.per_joint.{name} may only set pwm and current")
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"follower_caps.per_joint.{name}.{register} must be an integer")
        pwm = int(values.get("pwm", config.get("follower_caps", {}).get("pwm", DEFAULT_PWM)))
        current = int(values.get("current", config.get("follower_caps", {}).get("current", DEFAULT_CURRENT)))
        if not 1 <= pwm <= CAP_MAX or not 1 <= current <= CURRENT_MAX:
            raise ValueError(f"follower_caps.per_joint.{name} must stay 1..{CAP_MAX} PWM "
                             f"and 1..{CURRENT_MAX} current")
    for section in ("follower_gains", "leader_gains"):
        gains = config.get(section, {}).get("per_joint", {})
        if not isinstance(gains, dict):
            raise ValueError(f"{section}.per_joint must be an object keyed by body joint")
        for name, values in gains.items():
            if name not in BODY:
                raise ValueError(f"{section}.per_joint names no body joint: {name}")
            if not isinstance(values, dict) or not values:
                raise ValueError(f"{section}.per_joint.{name} must set p and/or i")
            for register, value in values.items():
                if register not in ("p", "i"):
                    raise ValueError(f"{section}.per_joint.{name} may only set p and i")
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ValueError(f"{section}.per_joint.{name}.{register} must be an integer")
                if not 0 <= value <= GAIN_MAX:
                    raise ValueError(f"{section}.per_joint.{name}.{register} must be 0..{GAIN_MAX}")
    gravity = config.get("leader_gravity_ticks", {}).get("per_joint", {})
    if not isinstance(gravity, dict):
        raise ValueError("leader_gravity_ticks.per_joint must be an object keyed by body joint")
    for name, ticks in gravity.items():
        if name not in BODY:
            raise ValueError(f"leader_gravity_ticks.per_joint names no body joint: {name}")
        if not isinstance(ticks, int) or isinstance(ticks, bool):
            raise ValueError(f"leader_gravity_ticks.per_joint.{name} must be an integer of ticks")
        if not 0 <= ticks <= GRAVITY_MAX_TICKS:
            raise ValueError(f"leader_gravity_ticks.per_joint.{name} must be 0..{GRAVITY_MAX_TICKS} ticks")


def follower_caps(arm: Arm) -> dict:
    """The Follower's resting caps, per body joint. XL430 has no Current Limit register."""
    caps = {}
    for name in BODY:
        motor = arm.follower_bus.motors[name].id
        values = {"PWM_Limit": arm.follower_bus.read("PWM_Limit", name)}
        if FOLLOWER_MODELS.get(motor, (1200, 4))[0] == 1200:
            values["Current_Limit"] = arm.follower_bus.read("Current_Limit", name)
        caps[name] = values
    return caps


def follower_limits(config: dict) -> dict:
    """The caps the run gives each Follower body joint: the shared base plus per-joint overrides.

    Gravity torque is joint-dependent, so one value for the whole arm is either too low for the
    shoulder or more authority than a wrist needs. The guard still reads the caps back from the
    motors, so the load stop and the following-error stop keep using each joint's own bound.
    """
    caps = config.get("follower_caps", {})
    pwm = int(caps.get("pwm", DEFAULT_PWM))
    current = int(caps.get("current", DEFAULT_CURRENT))
    limits = {name: {"pwm": pwm, "current": current} for name in BODY}
    for name, values in caps.get("per_joint", {}).items():
        limits[name].update({key: int(value) for key, value in values.items()})
    return limits


def set_follower_caps(arm: Arm, caps: dict, limits: dict) -> None:
    """Raise the Follower's caps with torque OFF and read every write back."""
    for name in BODY:
        if arm.follower_bus.read("Torque_Enable", name):
            raise ValueError(f"{arm.arm_id} follower {name}: the caps need torque OFF")
        pwm = limits[name]["pwm"]
        arm.follower_bus.write("PWM_Limit", name, pwm)
        if arm.follower_bus.read("PWM_Limit", name) != pwm:
            raise RuntimeError(f"{arm.arm_id} follower {name}: PWM_Limit readback failed")
        if "Current_Limit" in caps.get(name, {}):
            current = limits[name]["current"]
            arm.follower_bus.write("Current_Limit", name, current)
            if arm.follower_bus.read("Current_Limit", name) != current:
                raise RuntimeError(f"{arm.arm_id} follower {name}: Current_Limit readback failed")


def restore_follower_caps(arm: Arm, saved: dict) -> list[str]:
    """Write the Follower's caps back; a failure on one joint never skips the others."""
    failures = []
    for name, values in saved.items():
        for register, value in values.items():
            try:
                arm.follower_bus.write(register, name, value)
                if arm.follower_bus.read(register, name) != value:
                    raise RuntimeError("readback mismatch")
            except Exception as exc:
                failures.append(f"restore {name} {register}={value}: {exc}")
    return failures


def follower_gains(config: dict) -> dict:
    """The position gains the run gives each Follower body joint that names them.

    Without an I gain a servo stops short of its goal under load, and that steady-state
    error is what a drooping shoulder shows as a Follower that never reaches the Leader.
    The gains are RAM registers, so a run sets them with torque OFF and restores them.
    """
    return _per_joint_gains(config, "follower_gains")


def leader_gains(config: dict) -> dict:
    """The position gains the run gives a Leader body joint; the Leader droops the same way."""
    return _per_joint_gains(config, "leader_gains")


def leader_gravity_ticks(config: dict) -> dict:
    """The static gravity bias the run adds to each written Leader goal, in ticks.

    A position-only loop answers a heavy shoulder with a standing position error. Adding that
    error back to the written goal makes the servo hold the pose the run asked for; the ramp,
    the load stop and the arrival check stay unbiased.
    """
    return {name: int(ticks)
            for name, ticks in config.get("leader_gravity_ticks", {}).get("per_joint", {}).items()}


def _per_joint_gains(config: dict, section: str) -> dict:
    gains = config.get(section, {}).get("per_joint", {})
    return {name: {key: int(value) for key, value in values.items()} for name, values in gains.items()}


def follower_gain_state(arm: Arm) -> dict:
    """The P and I position gains every Follower body joint holds before the run."""
    return {name: {key: arm.follower_bus.read(register, name)
                   for key, register in (("p", "Position_P_Gain"), ("i", "Position_I_Gain"))}
            for name in BODY}


def effective_gains(saved: dict, applied: dict) -> dict:
    """The gains a run held: the found values with the run's own on top, per register."""
    return {name: {**values, **applied.get(name, {})} for name, values in saved.items()}


def set_follower_gains(arm: Arm, gains: dict) -> None:
    """Write the run's position gains with torque OFF and read every write back."""
    for name, values in gains.items():
        if arm.follower_bus.read("Torque_Enable", name):
            raise ValueError(f"{arm.arm_id} follower {name}: the gains need torque OFF")
        for key, register in (("p", "Position_P_Gain"), ("i", "Position_I_Gain")):
            if key not in values:
                continue
            arm.follower_bus.write(register, name, values[key])
            if arm.follower_bus.read(register, name) != values[key]:
                raise RuntimeError(f"{arm.arm_id} follower {name}: {register} readback failed")


def restore_follower_gains(arm: Arm, saved: dict, applied: dict) -> list[str]:
    """Write back only the gain registers the run changed; a failure never skips the rest."""
    failures = []
    for name, values in applied.items():
        for key, register in (("p", "Position_P_Gain"), ("i", "Position_I_Gain")):
            if key not in values:
                continue
            try:
                arm.follower_bus.write(register, name, saved[name][key])
                if arm.follower_bus.read(register, name) != saved[name][key]:
                    raise RuntimeError("readback mismatch")
            except Exception as exc:
                failures.append(f"restore {name} {register}={saved[name][key]}: {exc}")
    return failures


def validate_poses(poses: dict, arms) -> None:
    """Every pose names every body joint of every arm and stays inside the calibrated range."""
    if poses.get("schema") != POSE_SCHEMA:
        raise ValueError(f"pose file schema must be {POSE_SCHEMA}")
    table = poses.get("poses")
    if not isinstance(table, dict) or not table:
        raise ValueError("the pose file needs a poses table")
    for arm_id, named in table.items():
        if arm_id not in arms:
            raise ValueError(f"pose file names an unknown arm: {arm_id}")
        for name, values in named.items():
            if not isinstance(values, dict) or set(values) != set(BODY):
                raise ValueError(f"{arm_id}.{name} must name exactly {list(BODY)}")
            for joint, value in values.items():
                if not isinstance(value, int) or not 0 <= value < TURN:
                    raise ValueError(f"{arm_id}.{name}.{joint} must be a tick value in 0..{TURN - 1}")


# --------------------------------------------------------------------- devices


def assert_bus_free(device: str) -> None:
    """Refuse to run while another process holds the port.

    The LeRobot bus opens the port without an exclusive lock, so two owners would read
    each other's replies. `fuser` is the same check the read-only probes use.
    """
    path = Path(device)
    if path.parent != Path("/dev/serial/by-id") or not path.is_symlink():
        raise ValueError(f"{device} must be a physically confirmed /dev/serial/by-id symlink")
    resolved = str(path.resolve(strict=True))
    users = subprocess.run(["fuser", resolved], capture_output=True, text=True, timeout=5)
    if users.returncode != 1 or users.stdout.strip() or users.stderr.strip():
        raise RuntimeError(f"{device} is busy or its ownership could not be checked: "
                           f"{users.stdout.strip()} {users.stderr.strip()}".strip())


def open_arm(arm_id: str, follower_port: str, leader_port: str) -> Arm:
    """Open one arm's two buses passively: torque OFF, no EEPROM write, no calibration."""
    from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig
    from lerobot.robots.omx_follower.omx_follower import OmxFollower
    from lerobot.teleoperators.omx_leader.config_omx_leader import OmxLeaderConfig
    from lerobot.teleoperators.omx_leader.omx_leader import OmxLeader

    assert_bus_free(follower_port)
    assert_bus_free(leader_port)
    follower = OmxFollower(OmxFollowerConfig(port=follower_port, id=f"{arm_id}_follower",
                                            use_degrees=False, cameras={}))
    leader = OmxLeader(OmxLeaderConfig(port=leader_port, id=f"{arm_id}_leader"))
    connect_passive(follower, follower=True)
    connect_passive(leader, follower=False)
    return Arm(arm_id, follower, leader)


def close_arm(arm: Arm) -> None:
    """Torque OFF on both buses and close them; a failure on one arm never skips the other."""
    errors = []
    for device in (arm.follower, arm.leader):
        try:
            guarded_native.close_device(device)
        except Exception as exc:
            errors.append(f"{arm.arm_id}: {exc}")
    if errors:
        raise RuntimeError(f"close failed: {errors}")


# --------------------------------------------------------------------- stages


def read_positions(bus) -> dict:
    return bus.sync_read("Present_Position", normalize=False)


def gap_degrees(leader: dict, follower: dict) -> dict:
    return {name: round((leader[name] - follower[name]) * 360 / TURN, 3) for name in BODY}
