#!/usr/bin/env python3
"""D-977 5 (2026-11-17): the device_trial PRE_DISPATCH producer, `operator-attested-producer`.

Not an independent observation. A named cell operator's SOURCE_CLEAR (single use, 45 s) is the only reason this posts:
Fleet shows its observation context only behind a valid SOURCE_CLEAR and refuses the post otherwise, and this tool also
refuses any context whose producer id is not `operator-attested-producer`. What it posts is
  - object pose: the policy source pose from the written installation (the operator vouched the object is there),
  - arm zone and link clearance: forward kinematics of the arm session's own measured joints (chunk-io/live.json),
    through the simulation observer's ArmModel, Client and sampling code (tools/sim/transfer_observer.py).
Read only: it never commands the arm. POST_ACTION is not its job.

  ROSY_TRANSFER_OBSERVER_TOKEN=... operator_attested_producer.py --origin https://<fleet> --assets <open_manipulator_description> \
      --installation <written installation.json> --live chunk-io/live.json [--calibration omx_follower_arm.json] [--pipeline cell-pipeline.json] run
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / 'tools/sim')]
from arm_status_bridge import JOINTS, STALE_S, to_radians  # noqa: E402
import transfer_observer as sim  # noqa: E402

PRODUCER_ID = 'operator-attested-producer'
OPEN_TOLERANCE = 1.0  # gripper units; the same slack cell_area_vision_align.py allows below `grip_open`


class LiveState:
    """The sim observer's state document, built from the runner's live row; joint rates by differencing reads."""

    def __init__(self, instance, live, source_pose, calibration=None, now=time.time, grip_open=None):
        self.instance, self.live, self.pose, self.calibration, self.now = instance, live, source_pose, calibration, now
        self.grip_open = grip_open  # the arm's own pipeline `coarse.grip_open`; None means the open value is unknown
        self.previous = None

    def __call__(self):
        row = self.live()
        t = row.get('t')
        if not isinstance(t, (int, float)) or not row.get('state') or self.now() - t > STALE_S:
            raise TimeoutError('arm session live state is missing or stale')
        positions = to_radians(row['state'], self.calibration)
        before, self.previous = self.previous, (t, positions)
        if before is None or t <= before[0]:
            raise TimeoutError('arm session live state has not advanced')
        rates = [(positions[j] - before[1][j]) / (t - before[0]) for j in JOINTS]
        observed = int(t * 1e9)
        gripper = 'OPEN' if self.grip_open is not None and row['state'][-1] >= self.grip_open - OPEN_TOLERANCE else 'UNKNOWN'
        return {'schema': sim.STATE_SCHEMA, 'object': {**self.pose, 'observed_at_ns': observed},
                'owners': {self.instance: {'joint_names': list(JOINTS), 'positions_rad': [positions[j] for j in JOINTS],
                    'velocities_rad_s': rates, 'observed_at_ns': observed, 'sequence': int(t * 1000),
                    'gripper_state': gripper, 'held_state': 'NONE', 'held_object_ref': None}}}


def observe_once(client, read_state, model, bases, seen, *, sleep=time.sleep):
    """Post PRE_DISPATCH facts for the context Fleet shows; None without a context or on a foreign producer id."""
    context = client.context()
    if context is None or context['phase'] != 'PRE_DISPATCH':
        return None  # no valid SOURCE_CLEAR (Fleet hides the context), or not our phase
    if context['producer_id'] != PRODUCER_ID:
        raise PermissionError('context is not for the operator-attested producer')
    return sim.observe_once(client, read_state, model, bases, seen, sleep=sleep)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--origin', required=True)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--installation', required=True, type=Path)
    parser.add_argument('--live', required=True, type=Path)
    parser.add_argument('--calibration', type=Path)
    parser.add_argument('--pipeline', type=Path, help='the cell pipeline config; its coarse.grip_open is the open jaw value')
    parser.add_argument('--poll-s', type=float, default=.25)
    parser.add_argument('command', choices=('run', 'once'))
    args = parser.parse_args(argv)
    try:
        written = json.loads(args.installation.read_text(encoding='utf-8'))
        (instance,) = written['bases']
        pose = {k: written['policy']['source_pose'][k] for k in ('position_m', 'orientation_xyzw')}
        client = sim.Client(args.origin, os.environ.get('ROSY_TRANSFER_OBSERVER_TOKEN', ''))
        model, bases = sim.ArmModel.load(args.assets), written['bases']
        calibration = json.loads(args.calibration.read_text()) if args.calibration else None
        grip_open = float(json.loads(args.pipeline.read_text(encoding='utf-8-sig'))['coarse']['grip_open']) if args.pipeline else None
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'operator-attested producer refused its configuration: {type(error).__name__}\n')
    state = LiveState(instance, lambda: json.loads(args.live.read_text()), pose, calibration, grip_open=grip_open)
    seen = set()
    while True:
        try:
            reply = observe_once(client, state, model, bases, seen)
            if reply is not None:
                print(json.dumps({'evidence_source': 'operator_attested', 'status': reply['job']['status']}), flush=True)
        except Exception as error:  # a refusal or a lost read only ends this poll; Fleet decides
            print(json.dumps({'refused_or_error': type(error).__name__}), flush=True)
        if args.command == 'once':
            return
        time.sleep(args.poll_s)


if __name__ == '__main__':
    main()
