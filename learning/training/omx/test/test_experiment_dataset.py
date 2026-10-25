"""Dataset boundaries and real model inputs, independent of heavy model dependencies."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_experiment_profile import profile


def dataset(tmp_path, *, hil=False):
    setup = profile()
    setup['arms'] = setup['arms'][:1]
    setup['cameras'] = [setup['cameras'][0]]
    document = {'schema': 'rosy.omx.experiment-dataset/1', 'profile': setup,
                'source': 'synthetic_smoke', 'episodes': []}
    for index, split in enumerate(('train', 'eval', 'test')):
        arrays = {'observation.state': np.arange(18, dtype=np.float32).reshape(6, 3),
                  'action': np.ones((6, 3), dtype=np.float32) * index,
                  'observation.images.top': np.zeros((6, 3, 64, 80), dtype=np.uint8)}
        if hil:
            arrays.update(next_state=arrays['observation.state'] + 1,
                          reward=np.ones(6, dtype=np.float32),
                          terminated=np.array([False] * 5 + [True]),
                          truncated=np.zeros(6, dtype=bool),
                          is_intervention=np.array([True, True, False, False, True, True]))
            arrays['next.observation.images.top'] = arrays['observation.images.top'].copy()
        path = tmp_path / f'{split}.npz'
        np.savez(path, **arrays)
        document['episodes'].append({'id': split, 'session_id': f's{index}',
            'parent_id': f'p{index}', 'split': split, 'file': path.name,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    save(tmp_path, document)
    return document


def save(root, document):
    (root / 'dataset.json').write_text(json.dumps(document), encoding='utf-8')


def test_load_preserves_order_and_excludes_test_from_train(tmp_path):
    from experiment_dataset import load_dataset
    dataset(tmp_path)
    loaded = load_dataset(tmp_path)
    assert [e.metadata['id'] for e in loaded.split('train')] == ['train']
    assert loaded.split('train')[0].arrays['action'].shape == (6, 3)
    assert loaded.source == 'synthetic_smoke'


@pytest.mark.parametrize('change', ['session', 'parent', 'hash', 'escape', 'keys', 'nan'])
def test_refuses_leakage_tampering_and_bad_arrays(tmp_path, change):
    from experiment_dataset import load_dataset
    document = dataset(tmp_path)
    row = document['episodes'][1]
    if change in ('session', 'parent'):
        row[change + '_id'] = document['episodes'][0][change + '_id']
    elif change == 'hash':
        row['sha256'] = '0' * 64
    elif change == 'escape':
        row['file'] = '../outside.npz'
    else:
        path = tmp_path / row['file']
        with np.load(path, allow_pickle=False) as archive:
            arrays = dict(archive)
        if change == 'keys':
            arrays['unexpected'] = np.zeros(1)
        else:
            arrays['action'][0, 0] = np.nan
        np.savez(path, **arrays)
        row['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    save(tmp_path, document)
    with pytest.raises(ValueError):
        load_dataset(tmp_path)


def test_hil_requires_transition_arrays(tmp_path):
    from experiment_dataset import load_dataset
    dataset(tmp_path)
    with pytest.raises(ValueError):
        load_dataset(tmp_path, method='hilserl')


def test_intervention_chunk_stops_at_change_and_episode_end(tmp_path):
    from experiment_dataset import load_dataset, chunk_indices
    dataset(tmp_path, hil=True)
    episode = load_dataset(tmp_path, method='hilserl').split('train')[0]
    assert chunk_indices(episode, 0, 4) == [0, 1, None, None]
    assert chunk_indices(episode, 5, 4) == [5, None, None, None]
