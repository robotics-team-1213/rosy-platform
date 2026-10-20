"""Native grasp selections preserve original lineage and corresponding observations/actions."""
import copy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1] / 'native_segments.py'
    assert path.exists(), 'native grasp segment workflow is missing'
    spec = importlib.util.spec_from_file_location('native_segments', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def report():
    return dict(source_mode='leader_native', body_units='normalized_-100_100',
                rig_revision='rig', calibration_revision='cal', files={'meta/info.json': 'a'*64},
                repo_id='local/native', episodes=[dict(episode_index=i, frames=8,
                    content_sha256=str(i)*64, session_id=f's{i}', cycle_id=f'c{i}') for i in range(2)])


def selections(report):
    return [dict(**e, start_frame=2, end_frame=5, object='cube', intervention=False,
                 outcome='success', reviewer='human', reason='observed grasp', split=split)
            for e, split in zip(report['episodes'], ('train', 'eval'))]


def test_selection_keeps_source_identity_and_short_ranges(module, report):
    rows = selections(report)
    document = module.selection(report, rows)
    assert module.validate_selection(report, document) == {'train': [0], 'eval': [1]}
    assert document['segments'] == rows
    assert document['source_sha256'] == module.digest(report)
    report['files']['meta/info.json'] = 'f'*64
    with pytest.raises(ValueError, match='source'):
        module.validate_selection(report, document)


@pytest.mark.parametrize('field,value', [('start_frame', True), ('start_frame', -1),
    ('end_frame', 9), ('end_frame', 2), ('episode_index', False), ('content_sha256', 'x'),
    ('session_id', 'another'), ('outcome', 'unknown'), ('outcome', 'failure'),
    ('intervention', True), ('intervention', 'no'), ('reviewer', ''), ('object', '')])
def test_invalid_or_unconfirmed_segments_cannot_train(module, report, field, value):
    rows = selections(report)
    rows[0][field] = value
    with pytest.raises(ValueError):
        module.validate_selection(report, module.selection(report, rows))


@pytest.mark.parametrize('identity', ['episode_index', 'content_sha256', 'session_id', 'cycle_id'])
def test_all_parent_descendants_stay_in_one_split(module, report, identity):
    if identity == 'episode_index':
        rows = selections(report)
        rows[1] = dict(rows[0], split='eval', start_frame=5, end_frame=8)
    else:
        report['episodes'][1][identity] = report['episodes'][0][identity]
        rows = selections(report)
    with pytest.raises(ValueError, match='split'):
        module.validate_selection(report, module.selection(report, rows))


def test_failure_and_intervention_are_retained_only_as_excluded(module, report):
    rows = selections(report)
    rows.append(dict(rows[0], start_frame=5, end_frame=8, split='exclude', outcome='failure',
                     intervention=True))
    doc = module.selection(report, rows)
    assert module.validate_selection(report, doc)['train'] == [0]
    assert doc['segments'][-1]['outcome'] == 'failure'


def test_frame_copy_preserves_action_state_images_and_source_clocks(module):
    import numpy as np
    row = {'action': np.arange(6, dtype=np.float32), 'observation.state': np.arange(6)+10,
           'observation.images.front': np.ones((3, 2, 4), dtype=np.float32)*0.5,
           'source.capture_time_ns': np.array([123456789], dtype=np.int64),
           'frame_index': 19, 'timestamp': 19/30, 'task': 'pick'}
    features = {k: {} for k in row if k.startswith(('action', 'observation.', 'source.'))}
    frame = module.copy_frame(row, features)
    np.testing.assert_array_equal(frame['action'], row['action'])
    np.testing.assert_array_equal(frame['observation.state'], row['observation.state'])
    assert frame['observation.images.front'].shape == (2, 4, 3)
    assert frame['observation.images.front'].dtype == np.uint8
    assert frame['source.capture_time_ns'].item() == 123456789
    assert 'timestamp' not in frame and 'frame_index' not in frame
    assert frame['task'] == 'pick'
