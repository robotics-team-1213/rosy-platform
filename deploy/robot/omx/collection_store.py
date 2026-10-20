"""New-directory raw collection journal, with hashes and no task-success inference."""
import hashlib
import json
import os
from pathlib import Path
import uuid


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name+'.pending')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, allow_nan=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)
    sync_directory(path.parent)


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
        sync_directory(self.root.parent)
        self._last_environment, self._last_camera_info = None, None
        self.manifest = dict(schema='rosy.omx-collection-session.v1', state='RUNNING', mode=mode,
            source_mode='scripted_teacher' if mode == 'hardware' else 'simulation',
            session_id=uuid.uuid4().hex, rig_revision=profile['rig_revision'],
            calibration_revision=profile['calibration_revision'], teacher_sha256=teacher_sha256,
            fps=profile['fps'], task=profile['task'], camera_shapes=profile['camera_shapes'],
            body_units='normalized_-100_100', gripper_units='normalized_0_100', episodes=[], files={})
        save(self.root/'manifest.json', self.manifest)
        for name in ('environment.jsonl', 'events.jsonl'):
            (self.root/name).touch(exist_ok=False)

    def environment(self, receipt):
        stamp = receipt.get('recorded_ns')
        if type(stamp) is not int or stamp <= 0:
            raise ValueError('invalid original environment time')
        fingerprint = hashlib.sha256(json.dumps(receipt, sort_keys=True, allow_nan=False).encode()).hexdigest()
        if self._last_environment is not None:
            previous, digest = self._last_environment
            if stamp == previous and fingerprint == digest:
                return
            if stamp <= previous:
                raise ValueError('environment time reversed or original receipt changed')
        append(self.root/'environment.jsonl', receipt)
        self._last_environment = (stamp, fingerprint)

    def camera_info(self, intrinsics, time_ns):
        """Append the published camera models when first seen or changed; absent when not configured."""
        if not intrinsics:
            return
        fingerprint = hashlib.sha256(json.dumps(intrinsics, sort_keys=True, allow_nan=False).encode()).hexdigest()
        if fingerprint == self._last_camera_info:
            return
        append(self.root/'camera_info.jsonl', dict(time_ns=time_ns, cameras=intrinsics))
        self._last_camera_info = fingerprint

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
                   reference_source_stamp=observation['reference_source_stamp'], images=images,
                   # D-792 S3: measured readback in profile joint order, for the wrist camera check pose.
                   joint_positions_rad=list(observation['joint_positions']))
        append(self.root/episode['samples_path'], row)
        episode['frames'] += 1

    def close(self, stop):
        for directory in sorted((p for p in self.root.rglob('*') if p.is_dir()), reverse=True):
            sync_directory(directory)
        self.manifest.update(state='CLOSED', stop=stop)
        self.manifest['files'] = {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(self.root.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
        save(self.root/'manifest.json', self.manifest)
        return self.manifest
