#!/usr/bin/env python3
"""D-864 §2: check register_probe readings against the vendor joint-map hypothesis; never opens a device.

The pinned ROBOTIS driver converts Present Position with identity transmission matrices and the XL330/XL430
model unit (2pi/4096 rad per tick, offset -pi), so ros_joint_rad equals dynamixel_rad_v1 by construction.
What the hardware can break is the register state the motors apply before Present Position: a non-zero
homing offset or the reverse bit. This tool checks only that, from read-only register_probe.py outputs taken
with no driver running (the vendor driver writes EEPROM and enables torque on start, so it is not used here).
It does not show that the physical zero matches the URDF zero.
Exit 0: every probe agrees and the hypothesis holds; 3: it does not; 2: invalid input.
"""
import argparse
import json
import math
from pathlib import Path
import sys

#: Motor ID -> ROS joint (open_manipulator omx_f.ros2_control.xacro at the pinned revision).
JOINTS = {11: 'joint1', 12: 'joint2', 13: 'joint3', 14: 'joint4', 15: 'joint5', 16: 'gripper_joint_1'}
#: Registers that must not change between probes; a change means something wrote the motor in between.
STATE = ('drive_mode', 'homing_offset_raw', 'operating_mode')
TICKS = 4096


def ros_rad(raw):
    """The vendor driver's Present Position conversion (model unit 2pi/4096, offset -pi, identity matrix)."""
    return raw * 2 * math.pi / TICKS - math.pi


def motors(probe):
    rows = {row.get('id'): row for row in probe.get('motors', [])}
    if set(rows) != set(JOINTS) or any(key not in row for row in rows.values() for key in STATE + ('position_raw',)):
        raise ValueError('each probe must list motors 11..16 with position and register state')
    return rows


def check(probes, *, still_ticks=4):
    """Pure comparison over one or more probes of a resting arm; returns the verdict document."""
    if not probes:
        raise ValueError('at least one probe required')
    readings = [motors(probe) for probe in probes]
    rows, holds = [], True
    for motor_id, joint in JOINTS.items():
        seen = [reading[motor_id] for reading in readings]
        first = seen[0]
        reasons = []
        if any(row[key] != first[key] for row in seen for key in STATE):
            reasons.append('register_changed_between_probes')
        if max(r['position_raw'] for r in seen) - min(r['position_raw'] for r in seen) > still_ticks:
            reasons.append('moved_between_probes')
        if first['homing_offset_raw'] != 0:
            reasons.append('homing_offset_nonzero')
        if first['drive_mode'] & 1:
            reasons.append('reverse_bit_set')
        raw = sum(r['position_raw'] for r in seen) / len(seen)
        rows.append(dict(motor_id=motor_id, joint=joint, homing_offset_raw=first['homing_offset_raw'],
                         drive_mode=first['drive_mode'], operating_mode=first['operating_mode'],
                         position_raw=raw, ros_rad=ros_rad(raw), reasons=reasons, holds=not reasons))
        holds &= not reasons
    return dict(schema='rosy.omx-joint-map-check/2', hypothesis='ros_joint_rad == dynamixel_rad_v1',
                proves='register state only; physical zero vs URDF zero is not checked',
                probes=len(probes), still_ticks=still_ticks, holds=holds, joints=rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('probes', type=Path, nargs='+', help='register_probe.py JSON outputs of a resting arm')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.out.exists():
            raise ValueError('verdict exists; choose a new path')
        verdict = check([json.loads(path.read_text(encoding='utf-8')) for path in args.probes])
        with args.out.open('x', encoding='utf-8') as stream:
            json.dump(verdict, stream, indent=2)
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        print(f'joint_map_check: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'holds': verdict['holds']}))
    return 0 if verdict['holds'] else 3


if __name__ == '__main__':
    sys.exit(main())
