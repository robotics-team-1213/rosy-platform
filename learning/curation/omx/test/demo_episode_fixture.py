"""Synthetic OMX demonstration episodes for learning tests (D3, panel7 learning-contract).

Writes the rosy.omx-demonstration.v1 file layout the omx recorder writes. It does not validate rows: a test shows the
bytes are valid by calling rosy.contracts.learning.omx.validate_demonstration (see test_demo_episode_fixture.py).
Never evidence of a simulator or policy run.
"""
import hashlib
import io
import json
from pathlib import Path
import time
from uuid import uuid4

from PIL import Image

from rosy.contracts.learning.omx import ACTION_SEMANTICS, ROBOT_TYPE, SCHEMA


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class EpisodeWriter:
    """start / event / sample / stop, same call shape as the omx DemonstrationRecorder; every sample is kept."""

    def __init__(self, root, provenance):
        self.root, self.source, self._path = Path(root).resolve(), provenance, None

    def start(self, task):
        episode_id = str(uuid4())
        self._path = self.root / episode_id
        (self._path / 'images/front').mkdir(parents=True)
        self._manifest = {'schema': SCHEMA, 'episode_id': episode_id, 'robot_type': ROBOT_TYPE,
                          'action_semantics': ACTION_SEMANTICS, 'provenance': self.source, 'task': task.strip(),
                          'status': 'recording', 'frame_count': 0, 'started_wall_time_ns': time.time_ns(),
                          'task_outcome': 'unspecified'}
        self._samples, self._events = [], []
        return dict(self._manifest)

    def event(self, event):
        keep = {'kind', 'command_id', 'goal_id', 'sequence', 'status', 'result_code', 'accepted_sim_time_ns',
                'target', 'duration_s'}
        self._events.append({**{k: v for k, v in event.items() if k in keep}, 'received_wall_time_ns': time.time_ns()})

    def sample(self, *, capture_time_ns, state_time_ns, positions, target, state_sequence, command_id, ros_goal_id,
               duration_s, image_png, received_at_ns):
        names, index = self.source['joint_names'], len(self._samples)
        row = {'capture_time_ns': capture_time_ns, 'state_time_ns': state_time_ns, 'received_at_ns': received_at_ns,
               'state_sequence': state_sequence, 'observation.state': [positions[n] for n in names],
               'action': [target[n] for n in names], 'command_id': command_id, 'ros_goal_id': ros_goal_id,
               'duration_s': duration_s}
        if self.source.get('gripper_joint') is not None:
            row['action.gripper'] = target[self.source['gripper_joint']]
        row.update(frame_index=index, image_path=f'images/front/{index:06d}.png', image_sha256=_sha(image_png))
        (self._path / row['image_path']).write_bytes(image_png)
        self._samples.append(row)

    def stop(self, outcome='success'):
        payloads = {}
        for name, rows in (('samples', self._samples), ('events', self._events)):
            payloads[name] = b''.join(_json(row) + b'\n' for row in rows)
            (self._path / f'{name}.jsonl').write_bytes(payloads[name])
        self._manifest.update(status='complete', task_outcome=outcome, frame_count=len(self._samples), issues=[],
                              closed_wall_time_ns=time.time_ns(), samples_sha256=_sha(payloads['samples']),
                              events_sha256=_sha(payloads['events']))
        (self._path / 'manifest.json').write_bytes(_json(self._manifest))
        return dict(self._manifest)


def provenance():
    return {'simulation': True, 'instance_id': 'sim01', 'source_revision': 'a' * 40, 'vendor_revision': 'b' * 40,
            'world_sha256': 'c' * 64, 'source_tree_sha256': 'e' * 64, 'calibration_revision': 'sim-v1',
            'clock_domain': 'gazebo_sim', 'joint_names': ['joint1', 'gripper_joint_1'],
            'position_limits_rad': {'joint1': [-1, 1], 'gripper_joint_1': [-0.5, 0.5]},
            'camera': {'name': 'front', 'identity': 'gazebo:front', 'width': 8, 'height': 6,
                       'camera_info_sha256': 'd' * 64}, 'fps': 10}


def gripper_provenance():
    return {**provenance(), 'gripper_joint': 'gripper_joint_1'}


def image_bytes():
    output = io.BytesIO()
    Image.new('RGB', (8, 6), (12, 34, 56)).save(output, format='PNG')
    return output.getvalue()


def sample(writer, timestamp=1_000_000_000, **changes):
    values = {'capture_time_ns': timestamp, 'state_time_ns': timestamp - 10_000_000,
              'positions': {'joint1': 0.01, 'gripper_joint_1': -0.1},
              'target': {'joint1': 0.02, 'gripper_joint_1': -0.1}, 'state_sequence': timestamp // 1_000_000,
              'command_id': 'command', 'ros_goal_id': '11111111-1111-4111-8111-111111111111', 'duration_s': 0.4,
              'image_png': image_bytes(), 'received_at_ns': timestamp + 10}
    values.update(changes)
    writer.sample(**values)


def complete_episode_with(root, source):
    writer = EpisodeWriter(root, source)
    writer.start('move the joint')
    sample(writer)
    sample(writer, 1_100_000_000)
    return writer.stop('success')


def complete_episode(root):
    return complete_episode_with(root, provenance())
