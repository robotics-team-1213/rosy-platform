"""Strict, pickle-free experiment recordings shared by ACT and offline HIL-SERL."""
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import zipfile

import numpy as np

sys.path.append(str(Path(__file__).resolve().parents[2] / 'curation/perception'))
from storage_files import consumer as dataset_lease

from experiment_profile import action_names, profile_revision, validate_profile

ARM_SIGNALS = ('reward', 'terminated', 'truncated', 'is_intervention')


@dataclass
class Episode:
    metadata: dict
    arrays: dict


@dataclass
class ExperimentDataset:
    profile: dict
    source: str
    episodes: list
    revision: str

    def split(self, name):
        if name not in ('train', 'eval', 'test'):
            raise ValueError('unknown dataset split')
        return [episode for episode in self.episodes if episode.metadata['split'] == name]


def _file(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('relative regular dataset file required')
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root):
        raise ValueError('dataset file escapes dataset root')
    if any(part.is_symlink() for part in (path, *path.parents) if part != root.parent):
        raise ValueError('dataset symlinks are not accepted')
    if not path.is_file():
        raise ValueError('regular dataset file required')
    return path


def load_dataset(root: Path, *, method='act'):
    if method not in ('act', 'hilserl'):
        raise ValueError('unknown learning method')
    root = Path(root).resolve(strict=True)
    raw = _file(root, 'dataset.json').read_bytes()
    document = json.loads(raw)
    if (not isinstance(document, dict)
            or set(document) != {'schema', 'profile', 'source', 'episodes'}
            or document['schema'] not in ('rosy.omx.experiment-dataset/1', 'rosy.omx.experiment-dataset/2')):
        raise ValueError('unsupported experiment dataset schema')
    profile = validate_profile(document['profile'])
    per_arm = document['schema'] == 'rosy.omx.experiment-dataset/2'
    if per_arm and profile['mode'] != 'independent':
        raise ValueError('per-arm dataset schema requires independent mode')
    if document['source'] not in ('synthetic_smoke', 'reviewed_demonstration', 'robot_rollout'):
        raise ValueError('explicit dataset source required')
    rows = document['episodes']
    if not isinstance(rows, list) or not 2 <= len(rows) <= 10000:
        raise ValueError('bounded nonempty train and eval episodes required')
    width = len(action_names(profile))
    cameras = {camera['input_key']: tuple(camera['shape']) for camera in profile['cameras']}
    base = {'observation.state', 'action', *cameras}
    prefixes = ['arms.' + arm['id'] + '.' for arm in profile['arms']] if per_arm else ['']
    transitions = {'next_state', *('next.' + key for key in cameras),
                   *(prefix + signal for prefix in prefixes for signal in ARM_SIGNALS)}
    groups, identities, files, hashes, episodes = {}, set(), set(), set(), []
    total_bytes = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'session_id', 'parent_id', 'split', 'file', 'sha256'}:
            raise ValueError('episode fields differ from schema')
        for field in ('id', 'session_id', 'parent_id'):
            if not isinstance(row[field], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', row[field]):
                raise ValueError('explicit episode/session/parent identity required')
        split = row['split']
        if split not in ('train', 'eval', 'test'):
            raise ValueError('explicit train/eval/test split required')
        for key in ('session_id', 'parent_id'):
            group = key, row[key]
            if group in groups and groups[group] != split:
                raise ValueError('session or parent straddles dataset splits')
            groups[group] = split
        if row['id'] in identities or row['file'] in files:
            raise ValueError('duplicate episode identity/file')
        identities.add(row['id'])
        files.add(row['file'])
        path = _file(root, row['file'])
        if path.suffix != '.npz' or path.stat().st_size > 2_000_000_000:
            raise ValueError('bounded NPZ episode file required')
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != row['sha256'] or digest in hashes:
            raise ValueError('episode hash differs or duplicate content')
        hashes.add(digest)
        with zipfile.ZipFile(BytesIO(content)) as archive:
            total_bytes += sum(entry.file_size for entry in archive.infolist())
            if total_bytes > 2_000_000_000:
                raise ValueError('in-memory dataset exceeds 2 GB decoded bound')
        with np.load(BytesIO(content), allow_pickle=False) as archive:
            if len(archive.files) != len(set(archive.files)):
                raise ValueError('duplicate NPZ keys')
            keys = set(archive.files)
            if keys != base | transitions and (method == 'hilserl' or keys != base):
                raise ValueError('episode array keys differ from method schema')
            if per_arm and document['source'] == 'robot_rollout' and keys == base:
                raise ValueError('independent rollout requires explicit per-arm signals')
            arrays = {key: archive[key] for key in archive.files}
        state = arrays['observation.state']
        if state.ndim != 2 or state.shape[1] != width or len(state) < 1:
            raise ValueError('state/action dimensions differ from ordered arms')
        count = len(state)
        rewards = tuple(prefix + 'reward' for prefix in prefixes) if 'next_state' in keys else ()
        for key in ('observation.state', 'action', *(('next_state', *rewards) if 'next_state' in keys else ())):
            value = arrays[key]
            shape = (count,) if key in rewards else (count, width)
            if value.shape != shape or not np.issubdtype(value.dtype, np.floating) or not np.isfinite(value).all():
                raise ValueError('finite floating state/action/reward arrays required')
        for key, shape in cameras.items():
            for field in (key, *(('next.' + key,) if 'next_state' in keys else ())):
                if arrays[field].shape != (count, *shape) or arrays[field].dtype != np.uint8:
                    raise ValueError('uint8 CHW camera shape differs from profile')
        if 'next_state' in keys:
            for prefix in prefixes:
                for signal in ARM_SIGNALS[1:]:
                    value = arrays[prefix + signal]
                    if value.shape != (count,) or value.dtype != np.bool_:
                        raise ValueError('boolean transition flags required')
                if np.any(arrays[prefix + 'terminated'] & arrays[prefix + 'truncated']):
                    raise ValueError('transition cannot be both terminated and truncated')
        episodes.append(Episode(dict(row), arrays))
    loaded = ExperimentDataset(profile, document['source'], episodes,
        hashlib.sha256(raw + profile_revision(profile).encode()).hexdigest())
    if not loaded.split('train') or not loaded.split('eval'):
        raise ValueError('disjoint nonempty train and eval splits required')
    return loaded


def chunk_indices(episode, start, size):
    arrays = episode.arrays
    count = len(arrays['action'])
    if type(start) is not int or not 0 <= start < count or type(size) is not int or size < 1:
        raise ValueError('valid episode index and chunk size required')
    result, ended = [], False
    for index in range(start, start + size):
        if index >= count:
            ended = True
        if not ended and index > start and 'is_intervention' in arrays:
            ended = (arrays['is_intervention'][index] != arrays['is_intervention'][start]
                     or arrays['terminated'][index - 1] or arrays['truncated'][index - 1])
        result.append(None if ended else index)
    return result
