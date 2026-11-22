"""Shared input and first joint readbacks for a simulation-only CAD194 reset check."""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re

SCHEMA = "rosy.omx.paired-reset/1"
ARMS = ("arm_a", "arm_b")
JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")
SOURCE_HASHES = ("layout_sha256", "capture_sha256", "camera_snapshot_sha256", "joint_calibration_sha256")
# Diagnostic threshold uses the same angular scale as the tool-down tolerance.
TOLERANCE_RAD = .02


def validate_pose(values, bounds=None):
    if not isinstance(values, dict) or set(values) != set(ARMS):
        raise ValueError("paired reset requires both A and B joints")
    for arm in ARMS:
        q = values[arm]
        if (not isinstance(q, list) or len(q) != len(JOINTS)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in q)):
            raise ValueError(f"invalid canonical joint vector for {arm}")
        if bounds is not None:
            for joint, v, (low, high) in zip(JOINTS, q, bounds, strict=True):
                if not low <= v <= high:
                    raise ValueError(f"{arm} {joint} outside the simulation profile: {v:.4f} rad")
    return values


def read_start(path, layout_sha256, profile):
    raw = path.read_bytes()
    state = validate_start(json.loads(raw), layout_sha256, profile)
    return dict(state, input_sha256=sha256(raw).hexdigest())


def validate_start(state, layout_sha256, profile):
    if (not isinstance(state, dict) or state.get("schema") != SCHEMA or state.get("joint_names") != list(JOINTS)
            or state.get("layout_sha256") != layout_sha256
            or any(not re.fullmatch("[0-9a-f]{64}", str(state.get(k))) for k in SOURCE_HASHES)):
        raise ValueError("paired reset requires a matching layout and calibrated source fingerprints")
    limits = [profile["joints"][joint]["position"] for joint in JOINTS[:-1]]
    validate_pose(state.get("joints_rad"), [*limits, profile["gripper"]["position"]])
    return state


def prepare_start(capture, calibration, timing, geometry, layout_sha256, profile):
    if "joint_observation" not in timing or not geometry["camera_snapshot_sha256"]:
        raise ValueError("paired reset requires both synchronized joints and an accepted camera snapshot")
    raw = calibration.read_bytes()
    joints = json.loads(raw)
    capture_sha = sha256(capture.read_bytes()).hexdigest()
    if (not isinstance(joints, dict) or joints.get("schema") != "rosy.omx.calibrated-joints/1"
            or joints.get("capture_sha256") != capture_sha):
        raise ValueError("joint calibration receipt is for a different capture")
    state = dict(schema=SCHEMA, layout_sha256=geometry["layout_sha256"], capture_sha256=capture_sha,
                 camera_snapshot_sha256=geometry["camera_snapshot_sha256"],
                 joint_calibration_sha256=sha256(raw).hexdigest(),
                 joint_names=joints.get("joint_names"), joints_rad=joints.get("joints_rad"))
    return validate_start(state, layout_sha256, profile)


def readback(state, engine, initial, first=None):
    return dict(engine=engine, layout_sha256=state["layout_sha256"], input_sha256=state["input_sha256"],
                initial_rad=initial, first_observation_rad=initial if first is None else first)


def check_readbacks(state, mujoco, isaac):
    expected = validate_pose(state["joints_rad"])
    errors = {}
    for engine, result in (("mujoco", mujoco), ("isaac", isaac)):
        if (not isinstance(result, dict) or result.get("engine") != engine
                or any(result.get(k) != state[k] for k in ("layout_sha256", "input_sha256"))):
            raise ValueError(f"{engine} readback belongs to a different reset")
        for stage in ("initial_rad", "first_observation_rad"):
            observed = validate_pose(result.get(stage))
            errors[f"{engine}.{stage}"] = max(abs(v - target) for arm in ARMS
                                             for v, target in zip(observed[arm], expected[arm], strict=True))
    return {"matched": max(errors.values()) <= TOLERANCE_RAD, "max_errors_rad": errors,
            "tolerance_rad": TOLERANCE_RAD}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="bind verified render inputs and a calibrated joint receipt")
    for name in ("render", "capture", "handoff", "joint-calibration", "out"):
        prepare.add_argument("--" + name, required=True, type=Path)
    mujoco = commands.add_parser("mujoco", help="exercise a paired start in MuJoCo")
    mujoco.add_argument("start", type=Path)
    mujoco.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    import yaml
    from omx_two_arm_sites import Layout, layout_digest

    layout = Layout(preset="v24-20261114-cad194")
    profile_path = Path(__file__).resolve().parents[2] / "deploy/robot/omx/sim/cell_profile.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    identity = layout_digest(layout)
    if args.command == "prepare":
        from omx_transfer_audit import check_render, load

        _, geometry, timing = check_render(args.render, args.capture, load(args.handoff))
        result = prepare_start(args.capture, args.joint_calibration, timing, geometry, identity, profile)
    else:
        from omx_two_arm_world import World

        state = read_start(args.start, identity, profile)
        world = World(layout)
        data = world.reset(initial_joints=state["joints_rad"])
        actual = {arm: data.qpos[world.q[arm]].tolist() for arm in ARMS}
        result = readback(state, "mujoco", actual)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
