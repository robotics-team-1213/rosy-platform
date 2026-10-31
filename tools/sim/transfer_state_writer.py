"""Simulation transfer state writer (D-927 stream C2): the sim facts transfer_observer.py reads, from the sim topics.

It subscribes to the simulator's joint states and object poses (the MuJoCo backend's /sim/joint_states and
/sim/object_tf) and writes one `rosy.sim-transfer-state/1` file. Gripper and held state are judged here from the
simulation, never taken from the owner: OPEN at the profile's open position, MOVING while the finger turns, otherwise
CLOSED; HELD when the object centre lies within HELD_RADIUS_M of the jaw midpoint and the gripper is not open.
Stamps are wall-clock receipt times, the clock Fleet's observation context uses.

  python3 tools/sim/transfer_state_writer.py --assets learning/envs/isaac/assets/open_manipulator_description \
      --bases bases.json --instance omx_cell_sim_01 --object green_block=object-1 --state state.json
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from omx_cell_world import jaw_contact_point  # noqa: E402
from transfer_observer import STATE_SCHEMA, ArmModel, _apply  # noqa: E402
from recovery_observer import _read  # noqa: E402

GRIPPER_JOINT, GRIPPER_OPEN_RAD, OPEN_TOLERANCE_RAD = 'gripper_joint_1', 1.0, .02  # sim cell_profile.yaml gripper
MOVING_RAD_S = .05
HELD_RADIUS_M = .025  # Half the widest admitted item (cell_profile.yaml jaw: up to 50 mm).


class Writer:
    def __init__(self, model, base, instance, object_name, object_ref, path, *, clock=time.time_ns):
        self.model, self.base, self.instance, self.path, self.clock = model, base, instance, Path(path), clock
        self.object_name, self.object_ref = object_name, object_ref
        self.jaw = jaw_contact_point()
        self.arm = self.object = None
        self.sequence = 0

    def joints(self, names, positions, velocities):
        self.sequence += 1
        self.arm = dict(names=list(names), positions=[float(v) for v in positions],
                        velocities=[float(v) for v in velocities], at=self.clock(), sequence=self.sequence)
        self.write()

    def objects(self, poses):
        """poses: (child_frame_id, (x, y, z), (x, y, z, w)) of every movable body."""
        for name, position, orientation in poses:
            if name == self.object_name:
                self.object = dict(position_m=[float(v) for v in position],
                                   orientation_xyzw=[float(v) for v in orientation], observed_at_ns=self.clock())

    def jaw_midpoint(self, positions):
        frames = self.model.frames(positions, self.base)
        x, y = self.jaw
        points = []
        for link, side in (('link6', 1), ('link7', -1)):  # link7 mirrors link6, as in the MuJoCo pads
            rotation, origin = frames[link]
            points.append([o + d for o, d in zip(origin, _apply(rotation, (x, side * y, 0.0)))])
        return [(a + b) / 2 for a, b in zip(*points)]

    def state(self):
        if self.arm is None or self.object is None:
            return None
        arm = self.arm
        positions = dict(zip(arm['names'], arm['positions']))
        rate = dict(zip(arm['names'], arm['velocities'])).get(GRIPPER_JOINT, 0.0)
        q = positions[GRIPPER_JOINT]
        gripper = ('OPEN' if abs(q - GRIPPER_OPEN_RAD) <= OPEN_TOLERANCE_RAD
                   else 'MOVING' if abs(rate) > MOVING_RAD_S else 'CLOSED')
        gap = sum((a - b) ** 2 for a, b in zip(self.jaw_midpoint(positions), self.object['position_m'])) ** .5
        held = gripper != 'OPEN' and gap <= HELD_RADIUS_M
        return {'schema': STATE_SCHEMA, 'object': dict(self.object), 'owners': {self.instance: {
            'sequence': arm['sequence'], 'observed_at_ns': arm['at'], 'joint_names': arm['names'],
            'positions_rad': arm['positions'], 'velocities_rad_s': arm['velocities'], 'gripper_state': gripper,
            'held_state': 'HELD' if held else 'NONE', 'held_object_ref': self.object_ref if held else None}}}

    def write(self):
        state = self.state()
        if state is None:
            return
        temporary = self.path.with_name(self.path.name + '.tmp')
        temporary.write_text(json.dumps(state), encoding='utf-8')
        os.replace(temporary, self.path)  # the observer never reads a half-written state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--bases', required=True, type=Path)
    parser.add_argument('--instance', required=True)
    parser.add_argument('--object', required=True, help='sim body name = Fleet object_ref')
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--joints-topic', default='/sim/joint_states')
    parser.add_argument('--objects-topic', default='/sim/object_tf')
    args = parser.parse_args(argv)
    name, _, ref = args.object.partition('=')
    if not name or not ref:
        parser.exit(2, '--object must be BODY=OBJECT_REF\n')
    writer = Writer(ArmModel.load(args.assets), _read(args.bases)[args.instance], args.instance, name, ref, args.state)

    import rclpy
    from sensor_msgs.msg import JointState
    from tf2_msgs.msg import TFMessage
    rclpy.init()
    node = rclpy.create_node('rosy_sim_transfer_state_writer')
    node.create_subscription(JointState, args.joints_topic,
                             lambda m: writer.joints(m.name, m.position, m.velocity), 10)
    node.create_subscription(TFMessage, args.objects_topic, lambda m: writer.objects(
        (t.child_frame_id, (t.transform.translation.x, t.transform.translation.y, t.transform.translation.z),
         (t.transform.rotation.x, t.transform.rotation.y, t.transform.rotation.z, t.transform.rotation.w))
        for t in m.transforms), 10)
    print('SIM_TRANSFER_STATE_WRITER_READY', flush=True)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
