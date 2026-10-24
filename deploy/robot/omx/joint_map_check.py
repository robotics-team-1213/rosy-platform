#!/usr/bin/env python3
"""D-864 §2: compare a read-only register probe with one /joint_states sample; never opens a device.

Hypothesis from the pinned ROBOTIS stack: with homing offset 0 and drive-mode reverse bit 0, each ROS joint
radian equals the same-order motor's dynamixel_rad_v1 (raw * 2pi/4096 - pi). Run on a resting arm:
  1. driver stopped: register_probe.py --device <by-id> > probe.json
  2. vendor driver up with torque disabled at init: ros2 topic echo --once /joint_states > joint_states.yaml
  3. register_probe.py again > probe-after.json (the arm must not have moved between)
  4. joint_map_check.py probe.json joint_states.yaml probe-after.json --out <new-verdict.json>
Exit 0: hypothesis holds; 3: it does not; 2: invalid input.
"""
import argparse
import json
import math
from pathlib import Path
import sys

#: Motor ID -> ROS joint (open_manipulator omx_f.ros2_control.xacro at the pinned revision).
JOINTS = {11: 'joint1', 12: 'joint2', 13: 'joint3', 14: 'joint4', 15: 'joint5', 16: 'gripper_joint_1'}
TICKS = 4096


def motor_rad(raw):
    return raw * 2 * math.pi / TICKS - math.pi


def motors(probe):
    rows = {row['id']: row for row in probe.get('motors', [])}
    if set(rows) != set(JOINTS):
        raise ValueError('probe must list motors 11..16')
    return rows


def check(before, joint_states, after, *, tolerance_rad=0.01, still_ticks=4):
    """Pure comparison; returns the verdict document."""
    first, last = motors(before), motors(after)
    names, positions = list(joint_states.get('name', [])), list(joint_states.get('position', []))
    if len(names) != len(positions) or not set(JOINTS.values()) <= set(names):
        raise ValueError('joint_states must carry every OMX joint with a position')
    ros = dict(zip(names, positions))
    rows, holds = [], True
    for motor_id, joint in JOINTS.items():
        a, b = first[motor_id], last[motor_id]
        moved = abs(a['position_raw'] - b['position_raw']) > still_ticks
        predicted = motor_rad((a['position_raw'] + b['position_raw']) / 2)
        error = float(ros[joint]) - predicted
        row = dict(motor_id=motor_id, joint=joint, homing_offset_raw=a['homing_offset_raw'],
                   drive_mode=a['drive_mode'], reverse=bool(a['drive_mode'] & 1), moved=moved,
                   ros_rad=float(ros[joint]), predicted_rad=predicted, error_rad=error,
                   holds=(not moved and a['homing_offset_raw'] == 0 and not a['drive_mode'] & 1
                          and abs(error) <= tolerance_rad))
        holds &= row['holds']
        rows.append(row)
    return dict(schema='rosy.omx-joint-map-check/1', hypothesis='ros_joint_rad == dynamixel_rad_v1',
                tolerance_rad=tolerance_rad, still_ticks=still_ticks, holds=holds, joints=rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('probe', type=Path)
    parser.add_argument('joint_states', type=Path, help='`ros2 topic echo --once /joint_states` output (YAML)')
    parser.add_argument('probe_after', type=Path)
    parser.add_argument('--tolerance-rad', type=float, default=0.01)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        import yaml
        if args.out.exists():
            raise ValueError('verdict exists; choose a new path')
        load = lambda path: json.loads(path.read_text(encoding='utf-8'))
        sample = yaml.safe_load(args.joint_states.read_text(encoding='utf-8'))
        verdict = check(load(args.probe), sample, load(args.probe_after), tolerance_rad=args.tolerance_rad)
        with args.out.open('x', encoding='utf-8') as stream:
            json.dump(verdict, stream, indent=2)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'joint_map_check: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'holds': verdict['holds']}))
    return 0 if verdict['holds'] else 3


if __name__ == '__main__':
    sys.exit(main())
