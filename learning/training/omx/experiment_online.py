"""A persistent SAC learner fed immutable registered experience, without a robot actor."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

import numpy as np

from experiment_dataset import Episode, ExperimentDataset, load_dataset
from experiment_profile import action_bounds
from experiment_scope import select_dataset
from experiment_train import train_dataset, write_json
from experiment_jobs import check_learning_task

MAX_INPUTS = 128
MAX_REPLAY_BYTES = 512 * 1024 * 1024


class OnlineLearner:
    def __init__(self, request, output):
        if (not isinstance(request, dict)
                or set(request) - {'arm_id', 'learning_task'} != {'dataset_root', 'method', 'steps', 'batch_size', 'device', 'seed'}
                or request['method'] != 'hilserl' or request['device'] != 'cpu'):
            raise ValueError('explicit CPU hilserl online request required')
        for key, low, high in [('steps', 1, 100000), ('batch_size', 1, 256), ('seed', 0, 2**32 - 1)]:
            if type(request[key]) is not int or not low <= request[key] <= high:
                raise ValueError('invalid online training budget')
        self.output = Path(output).resolve()
        root = Path(request['dataset_root']).resolve(strict=True)
        if (self.output.exists() or self.output.is_relative_to(root) or root.is_relative_to(self.output)
                or any((parent / '.git').exists() for parent in (self.output, *self.output.parents))):
            raise ValueError('new output outside dataset and source checkout required')
        self.request = dict(request)
        initial = load_dataset(root, method='hilserl')
        if 'learning_task' in request:
            _, scope = select_dataset(initial, request.get('arm_id'), method='hilserl')
            check_learning_task(request['learning_task'], initial, scope)
        self.bounds = np.asarray(action_bounds(initial.profile), dtype=np.float32)
        if not np.isfinite(self.bounds).all() or np.any(self.bounds[:, 0] >= self.bounds[:, 1]):
            raise ValueError('declared action limits collapse or overflow in float32')
        self.profile = initial.profile
        self.state, self.roles, self.identities, self.revisions = {}, {}, set(), set()
        self.inputs, self.errors, self.episode_ids = [], [], set()
        self.next_sequence = 1
        self.episodes, self.sources, self.replay_bytes = [], [], 0
        self.latest_version = None
        self.output.mkdir(parents=True)
        (self.output / 'versions').mkdir()
        self.inbox = self.output.parent / 'inbox'
        self.inbox.mkdir(exist_ok=True)
        roles, size = self._validate(initial)
        self._consume('initial', initial, roles, size)

    def _validate(self, dataset):
        if len(self.inputs) >= MAX_INPUTS:
            raise ValueError('online input descriptor limit reached')
        if dataset.profile != self.profile:
            raise ValueError('experience profile differs from initial policy')
        select_dataset(dataset, self.request.get('arm_id'), method='hilserl')
        roles = dict(self.roles)
        for episode in dataset.episodes:
            row, split = episode.metadata, episode.metadata['split']
            if row['id'] in self.episode_ids:
                raise ValueError('experience episode identity was already registered')
            for kind, identity in [('session', row['session_id']), ('parent', row['parent_id']),
                                   ('content', row['sha256'])]:
                key = kind, identity
                if key in roles and roles[key] != split:
                    raise ValueError('experience session/parent/content crosses global split roles')
                roles[key] = split
            if split == 'train':
                actions = episode.arrays['action']
                if np.any(actions < self.bounds[:, 0]) or np.any(actions > self.bounds[:, 1]):
                    raise ValueError('experience action exceeds declared fixed action limits')
        size = sum(value.nbytes for episode in dataset.split('train') for value in episode.arrays.values())
        if self.replay_bytes + size > MAX_REPLAY_BYTES:
            raise ValueError('accumulated decoded train replay exceeds 512 MiB')
        return roles, size

    def _progress(self, phase, event=None):
        write_json(self.output / 'progress.json', dict(phase=phase,
            total_steps=self.state.get('total_steps', 0), consumed_inputs=list(self.inputs),
            latest_version=self.latest_version, input_errors=list(self.errors), latest_update=event))

    def _consume(self, identifier, dataset, roles, size):
        episodes = list(self.episodes)
        for episode in dataset.episodes:
            if identifier == 'initial' or episode.metadata['split'] == 'train':
                episodes.append(Episode(dict(episode.metadata, source=dataset.source), episode.arrays))
        sources = [*self.sources, dict(id=identifier, dataset_revision=dataset.revision,
                                      source=dataset.source)]
        revision = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
        replay = ExperimentDataset(self.profile, sources[0]['source'], episodes, revision)
        version = f'{len(self.inputs) + 1:06}'
        destination = self.output / 'versions' / version
        self._progress('training')
        options = {key: self.request[key] for key in ('method', 'steps', 'batch_size', 'device', 'seed')}
        if 'arm_id' in self.request:
            options['arm_id'] = self.request['arm_id']
        if 'learning_task' in self.request:
            options['learning_task'] = self.request['learning_task']
        result = train_dataset(replay, destination, state=self.state,
            action_bounds=self.bounds.tolist(), execution_mode='online_experience',
            progress=lambda event: self._progress('training', event), **options)
        result.update(execution_mode='online_experience', physical_learning_verified=False,
                      policy_activation=False, version=version, inputs=sources,
                      total_steps=self.state['total_steps'], normalization_frozen=True,
                      action_bounds_source='declared_profile')
        write_json(destination / 'result.json', result)
        self.episodes, self.sources = episodes, sources
        self.roles, self.replay_bytes = roles, self.replay_bytes + size
        self.identities.add(identifier)
        self.revisions.add(dataset.revision)
        self.episode_ids.update(episode.metadata['id'] for episode in dataset.episodes)
        self.inputs.append(identifier)
        self.latest_version = version
        write_json(self.output / 'result.json', result)
        self._progress('waiting_for_experience')

    def poll(self):
        processed = False
        for sequence in range(self.next_sequence, MAX_INPUTS + 1):
            path = self.inbox / f'{sequence:06}.json'
            if not path.exists() and not path.is_symlink():
                break
            self.next_sequence = sequence + 1
            processed = True
            try:
                if path.is_symlink() or path.stat().st_size > 65536:
                    raise ValueError('fixed ordered inbox descriptor required')
                record = json.loads(path.read_bytes())
                if not isinstance(record, dict) or set(record) != {'id', 'dataset_root', 'dataset_revision'}:
                    raise ValueError('experience descriptor fields differ from schema')
                identifier = record['id']
                if str(uuid.UUID(identifier)) != identifier:
                    raise ValueError('canonical experience UUID required')
                if (not isinstance(record['dataset_revision'], str)
                        or not re.fullmatch('[0-9a-f]{64}', record['dataset_revision'])
                        or not isinstance(record['dataset_root'], str)
                        or not Path(record['dataset_root']).is_absolute()):
                    raise ValueError('registered absolute dataset path and revision required')
                if identifier in self.identities or record['dataset_revision'] in self.revisions:
                    continue
                dataset = load_dataset(record['dataset_root'], method='hilserl')
                if dataset.revision != record['dataset_revision']:
                    raise ValueError('registered experience revision differs from loaded bytes')
                roles, size = self._validate(dataset)
            except (ValueError, TypeError, OSError, KeyError) as exc:
                self.errors.append(dict(sequence=path.name, error=type(exc).__name__,
                                        reason=str(exc) if isinstance(exc, ValueError) else 'invalid experience input'))
                self._progress('waiting_for_experience')
                continue
            # A failed gradient/checkpoint is fatal: never continue after partial optimizer updates.
            self._consume(identifier, dataset, roles, size)
        return processed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise ValueError('new run-owned output directory required')
    try:
        learner = OnlineLearner(json.loads(args.request.read_text(encoding='utf-8')), args.out)
        while True:
            learner.poll()
            time.sleep(0.5)
    except Exception as exc:
        args.out.mkdir(parents=True, exist_ok=True)
        write_json(args.out / 'error.json', {'error': type(exc).__name__, 'status': 'failed'})
        raise


if __name__ == '__main__':
    raise SystemExit(main())
