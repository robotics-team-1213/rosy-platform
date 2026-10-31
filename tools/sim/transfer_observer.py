"""Simulation transfer observer (D-927 decision 3): facts for every observation phase; never approves or dispatches.

Joints, joint rates, gripper and object pose come from the simulation state file the sim owner writes. Link bounds
are URDF forward kinematics of those joints over each mesh's box, and link velocities follow from the joint rates.
These are simulation observations: Fleet validates them like any producer's, but they are not physical evidence.

  ROSY_TRANSFER_OBSERVER_TOKEN=... python tools/sim/transfer_observer.py --origin http://127.0.0.1:8000 \
      --assets learning/envs/isaac/assets/open_manipulator_description --bases bases.json --state state.json run
"""
import argparse
import json
import math
import os
from pathlib import Path
import struct
import sys
import time
from time import time_ns
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recovery_observer import LIMIT, NoRedirect, _json, _origin, _read  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'contracts/foundation'))
from core_common.protocol.arm_transfer_observations import (  # noqa: E402
    ArmTransferObservation, ArmTransferObservationContextResponse,
)

CONTEXT = '/api/fleet/arm-transfers/observation-context'
URDF = 'urdf/omx_f/omx_f.urdf'
STATE_SCHEMA = 'rosy.sim-transfer-state/1'
RATE_STEP_S = 1e-3


def _rpy(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return ((cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
            (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
            (-sp, cp * sr, cp * cr))


def _axis_angle(axis, angle):
    x, y, z = axis
    c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return ((t * x * x + c, t * x * y - s * z, t * x * z + s * y),
            (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
            (t * x * z - s * y, t * y * z + s * x, t * z * z + c))


def _quaternion(xyzw):
    x, y, z, w = xyzw
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def _mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _apply(rotation, vector):
    return tuple(sum(rotation[i][k] * vector[k] for k in range(3)) for i in range(3))


def _floats(text, count=3):
    values = tuple(float(v) for v in (text or ' '.join(['0'] * count)).split())
    if len(values) != count or not all(map(math.isfinite, values)):
        raise ValueError('URDF needs finite vectors')
    return values


def _stl_box(raw):
    """Binary STL vertex box; ASCII or truncated meshes are refused."""
    count = struct.unpack_from('<I', raw, 80)[0] if len(raw) >= 84 else -1
    if len(raw) != 84 + 50 * count or count < 1:
        raise ValueError('binary STL mesh required')
    points = [struct.unpack_from('<3f', raw, 84 + 50 * i + 12 + 12 * k) for i in range(count) for k in range(3)]
    return tuple(min(p[a] for p in points) for a in range(3)), tuple(max(p[a] for p in points) for a in range(3))


class ArmModel:
    """Serial URDF chain with one local box per link (the visual mesh or box, scaled and placed)."""

    def __init__(self, urdf, mesh):
        root = ET.fromstring(urdf)
        self.joints, self.boxes = [], {}
        for joint in root.findall('joint'):
            origin, axis, mimic = joint.find('origin'), joint.find('axis'), joint.find('mimic')
            self.joints.append(dict(name=joint.get('name'), type=joint.get('type'),
                parent=joint.find('parent').get('link'), child=joint.find('child').get('link'),
                xyz=_floats(origin.get('xyz') if origin is not None else None),
                rpy=_floats(origin.get('rpy') if origin is not None else None),
                axis=_floats(axis.get('xyz')) if axis is not None else None,
                mimic=(mimic.get('joint'), float(mimic.get('multiplier', 1)), float(mimic.get('offset', 0)))
                if mimic is not None else None))
            if self.joints[-1]['type'] not in ('fixed', 'revolute'):
                raise ValueError('only fixed and revolute joints are modelled')
        for link in root.findall('link'):
            visual = link.find('visual')
            if visual is None:
                continue
            origin, geometry = visual.find('origin'), visual.find('geometry')[0]
            if geometry.tag == 'mesh':
                low, high = mesh(geometry.get('filename'))
                scale = _floats(geometry.get('scale') or '1 1 1')
                low, high = (tuple(sorted((a * s, b * s))[i] for a, b, s in zip(low, high, scale)) for i in (0, 1))
            elif geometry.tag == 'box':
                half = tuple(v / 2 for v in _floats(geometry.get('size')))
                low, high = tuple(-h for h in half), half
            else:
                raise ValueError('only mesh and box visuals are modelled')
            self.boxes[link.get('name')] = (low, high, _floats(origin.get('xyz') if origin is not None else None),
                                            _rpy(*_floats(origin.get('rpy') if origin is not None else None)))
        children = {j['child'] for j in self.joints}
        roots = {j['parent'] for j in self.joints} - children
        if len(roots) != 1:
            raise ValueError('URDF must be one tree')
        self.root = roots.pop()

    @classmethod
    def load(cls, assets):
        assets = Path(assets)
        def mesh(filename):
            return _stl_box((assets / filename.removeprefix('package://open_manipulator_description/')).read_bytes())
        return cls((assets / URDF).read_bytes(), mesh)

    def frames(self, positions, base):
        """World (rotation, origin) of every link for the joint radians and the base pose."""
        frames, pending = {self.root: (_quaternion(base['orientation_xyzw']), tuple(base['position_m']))}, list(self.joints)
        while pending:
            joint = next((j for j in pending if j['parent'] in frames), None)
            if joint is None:
                raise ValueError('URDF joint has no reachable parent')
            pending.remove(joint)
            rotation, origin = frames[joint['parent']]
            origin = tuple(o + d for o, d in zip(origin, _apply(rotation, joint['xyz'])))
            rotation = _mul(rotation, _rpy(*joint['rpy']))
            if joint['type'] == 'revolute':
                if joint['mimic']:
                    name, multiplier, offset = joint['mimic']
                    angle = multiplier * positions[name] + offset
                else:
                    angle = positions[joint['name']]
                rotation = _mul(rotation, _axis_angle(joint['axis'], angle))
            frames[joint['child']] = (rotation, origin)
        return frames

    def bounds(self, frames):
        result = {}
        for link, (rotation, origin) in frames.items():
            if link not in self.boxes:
                continue
            low, high, offset, turn = self.boxes[link]
            place = _mul(rotation, turn)
            centre = tuple(o + d for o, d in zip(origin, _apply(rotation, offset)))
            corners = [tuple(c + d for c, d in zip(centre, _apply(place, (x, y, z))))
                       for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
            result[link] = ([min(p[a] for p in corners) for a in range(3)], [max(p[a] for p in corners) for a in range(3)])
        return result

    def links(self, positions, rates, base):
        """Link boxes plus velocities: frames at q and q + rate * step, differenced."""
        now = self.frames(positions, base)
        later = self.frames({k: v + rates.get(k, 0.0) * RATE_STEP_S for k, v in positions.items()}, base)
        result = {}
        for link, (low, high) in self.bounds(now).items():
            (r1, p1), (r2, p2) = now[link], later[link]
            turn = _mul(r2, tuple(zip(*r1)))
            spin = ((turn[2][1] - turn[1][2]) / 2, (turn[0][2] - turn[2][0]) / 2, (turn[1][0] - turn[0][1]) / 2)
            result[link] = {'bounds': {'min_m': low, 'max_m': high},
                            'linear_velocity_m_s': [(b - a) / RATE_STEP_S for a, b in zip(p1, p2)],
                            'angular_velocity_rad_s': [w / RATE_STEP_S for w in spin]}
        return result


def _state(raw):
    if not isinstance(raw, dict) or raw.get('schema') != STATE_SCHEMA:
        raise ValueError(f'{STATE_SCHEMA} state required')
    return raw


def sample(context, state, model, bases, *, evidence_id, sequence):
    """One observation of the context's owners and object from one simulation state."""
    state, owners = _state(state), []
    for owner in context['owners']:
        arm = state['owners'][owner['instance_id']]
        names, positions = list(arm['joint_names']), [float(v) for v in arm['positions_rad']]
        rates = dict(zip(names, (float(v) for v in arm['velocities_rad_s'])))
        observed = arm['observed_at_ns']
        owners.append({**owner, 'links_observed_at_ns': observed, 'gripper_observed_at_ns': observed,
            'links': model.links(dict(zip(names, positions)), rates, bases[owner['instance_id']]),
            'gripper_state': arm['gripper_state'], 'held_state': arm['held_state'],
            'held_object_ref': arm.get('held_object_ref'),
            'joints': {'sample_id': f"{owner['instance_id']}-joints-{arm['sequence']}", 'sequence': arm['sequence'],
                       'observed_at_ns': observed, 'joint_names': names, 'positions_rad': positions}})
    keys = ('producer_id', 'evaluator_revision', 'action_id', 'attempt_id', 'frame_id', 'policy_digest',
            'catalog_digest', 'bindings_digest', 'object_ref', 'object_origin_id')
    body = {**{k: context[k] for k in keys}, 'evidence_id': evidence_id, 'sequence': sequence,
            'object_observed_at_ns': state['object']['observed_at_ns'],
            'object_pose': {k: state['object'][k] for k in ('position_m', 'orientation_xyzw')}, 'owners': owners}
    return ArmTransferObservation.model_validate_json(json.dumps(body)).model_dump(mode='json')


def _stamps(state):
    return [state['object']['observed_at_ns'], *(arm['observed_at_ns'] for arm in state['owners'].values())]


def collect(context, read_state, model, bases, *, sleep=time.sleep, poll_s=.02):
    """Two samples from states that are new since not_before and separated by min_separation."""
    def fresh(after_ns, previous=None):
        deadline = time.monotonic() + context['max_age_ns'] / 1e9 * 4
        while True:
            state = _state(read_state())
            if min(_stamps(state)) > after_ns and (previous is None or all(
                    state['owners'][i]['sequence'] > previous['owners'][i]['sequence'] for i in previous['owners'])):
                return state
            if time.monotonic() > deadline:
                raise TimeoutError('simulation state did not advance')
            sleep(poll_s)

    first = fresh(context['not_before_ns'])
    second = fresh(max(_stamps(first)) + context['min_separation_ns'], first)
    sequence = time_ns()
    return {'phase': context['phase'], 'expected_request_digest': context['request_digest'], 'observations': [
        sample(context, state, model, bases, evidence_id='sim-' + uuid4().hex, sequence=sequence + offset)
        for offset, state in enumerate((first, second))]}


class Client:
    def __init__(self, origin, token):
        self.origin = _origin(origin)
        if (not isinstance(token, str) or not 32 <= len(token) <= 512 or token != token.strip()
                or any(ord(c) < 32 or ord(c) >= 127 for c in token)):
            raise ValueError('independent observer credential required')
        self._token = token
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _request(self, path, body=None):
        headers = {'X-Physical-Observation-Token': self._token}
        raw = None
        if body is not None:
            raw = json.dumps(body, allow_nan=False).encode()
            headers.update({'Origin': self.origin, 'Content-Type': 'application/json'})
        with self.opener.open(Request(self.origin + path, data=raw, headers=headers), timeout=10) as response:
            return _json(response.read(LIMIT + 1))

    def context(self):
        return ArmTransferObservationContextResponse.model_validate(self._request(CONTEXT)).model_dump(mode='json')['context']

    def submit(self, context, body):
        return self._request(f"/api/fleet/arm-transfers/jobs/{quote(context['mission_id'], safe='')}/observations", body)


def observe_once(client, read_state, model, bases, seen, *, sleep=time.sleep):
    """Answer the current context once; a refused or lost submission is retried with new samples next time."""
    context = client.context()
    if context is None:
        return None
    key = (context['mission_id'], context['attempt_id'], context['phase'], context['not_before_ns'])
    if key in seen:
        return None
    body = collect(context, read_state, model, bases, sleep=sleep)
    # The context, not this process, decides: after an accepted submission it moves on.
    if client.context() != context:
        return None
    reply = client.submit(context, body)
    seen.add(key)
    return reply


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--origin', required=True)
    parser.add_argument('--assets', required=True, type=Path)
    # shortcut: arm base poses come from this file until the S4 installation profile carries them.
    parser.add_argument('--bases', required=True, type=Path)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--poll-s', type=float, default=.1)
    parser.add_argument('command', choices=('run', 'once'))
    args = parser.parse_args(argv)
    try:
        client = Client(args.origin, os.environ.get('ROSY_TRANSFER_OBSERVER_TOKEN', ''))
        model, bases = ArmModel.load(args.assets), _read(args.bases)
    except (OSError, ValueError) as error:
        parser.exit(2, f'observer refused its configuration: {type(error).__name__}\n')
    seen = set()
    while True:
        try:
            reply = observe_once(client, lambda: _read(args.state), model, bases, seen)
            if reply is not None:
                print(json.dumps({'status': reply['job']['status']}), flush=True)
        except HTTPError as error:
            print(json.dumps({'refused': error.code}), flush=True)
        except (OSError, ValueError, TimeoutError) as error:
            print(json.dumps({'error': type(error).__name__}), flush=True)
        if args.command == 'once':
            return
        time.sleep(args.poll_s)


if __name__ == '__main__':
    main()
