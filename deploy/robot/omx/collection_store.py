"""New-directory raw collection journal, with hashes and no task-success inference."""
import hashlib
import json
import os
from pathlib import Path
import uuid


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name+'.pending')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, allow_nan=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def append(path, value):
    with Path(path).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, allow_nan=False)+'\n')
        stream.flush(); os.fsync(stream.fileno())


class RawCollection:
    def __init__(self, root, profile, teacher_sha256, mode):
        self.root = Path(root)
        if self.root.exists():
            raise ValueError('collection output exists; select a new directory')
        self.root.mkdir(parents=True)
        self.manifest = dict(schema='rosy.omx-collection-session.v1', state='RUNNING', mode=mode,
            source_mode='scripted_teacher' if mode == 'hardware' else 'simulation',
            session_id=uuid.uuid4().hex, rig_revision=profile['rig_revision'],
            calibration_revision=profile['calibration_revision'], teacher_sha256=teacher_sha256,
            fps=profile['fps'], task=profile['task'], camera_shapes=profile['camera_shapes'],
            body_units='normalized_-100_100', gripper_units='normalized_0_100', episodes=[], files={})
        save(self.root/'manifest.json', self.manifest)
        for name in ('environment.jsonl', 'events.jsonl'):
            (self.root/name).touch(exist_ok=False)

    def begin(self, now_ns, environment):
        index = len(self.manifest['episodes'])
        folder = self.root/f'episodes/{index:06d}'
        folder.mkdir(parents=True)
        episode = dict(episode_index=index, cycle_id=uuid.uuid4().hex, start_ns=now_ns, end_ns=None,
                       run_id=environment['run_id'], profile_sha256=environment['profile_sha256'],
                       complete=False, frames=0, samples_path=f'episodes/{index:06d}/samples.jsonl',
                       reason='interrupted', outcome='unknown')
        (self.root/episode['samples_path']).touch(exist_ok=False)
        self.manifest['episodes'].append(episode)
        save(self.root/'manifest.json', self.manifest)
        return episode

    def sample(self, episode, observation, requested):
        frame = episode['frames']
        images = {}
        for role, image in observation['images'].items():
            relative = f'episodes/{episode["episode_index"]:06d}/{role}-{frame:06d}.rgb'
            raw = bytes(image['data'])
            with (self.root/relative).open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            images[role] = dict(path=relative, width=image['width'], height=image['height'],
                                source_stamp=image['source_stamp'], sha256=hashlib.sha256(raw).hexdigest())
        row = dict(frame_index=frame, time_ns=observation['time_ns'],
                   **{'observation.state': observation['observation_state'], 'action': observation['action']},
                   requested_target_rad=list(requested), joint_source_stamp=observation['joint_source_stamp'],
                   reference_source_stamp=observation['reference_source_stamp'], images=images)
        append(self.root/episode['samples_path'], row)
        episode['frames'] += 1

    def close(self, stop):
        self.manifest.update(state='CLOSED', stop=stop)
        self.manifest['files'] = {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(self.root.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
        save(self.root/'manifest.json', self.manifest)
        return self.manifest
