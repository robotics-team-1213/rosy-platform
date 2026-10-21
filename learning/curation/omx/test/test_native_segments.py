"""Native grasp selections preserve original lineage and corresponding observations/actions."""
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
    return [dict(**{k:e[k] for k in ('episode_index','content_sha256','frames','session_id','cycle_id') if k in e},
                 start_frame=2, end_frame=5, object='cube', intervention=False,
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


@pytest.mark.parametrize('scalar_clock', [False, True])
def test_frame_copy_preserves_action_state_images_and_source_clocks(module, scalar_clock):
    import numpy as np
    row = {'action': np.arange(6, dtype=np.float32), 'observation.state': np.arange(6)+10,
           'observation.images.front': np.ones((3, 2, 4), dtype=np.float32)*0.5,
           'source.capture_time_ns': np.array(123456789 if scalar_clock else [123456789], dtype=np.int64),
           'frame_index': 19, 'timestamp': 19/30, 'task': 'pick'}
    features = {k: {} for k in row if k.startswith(('action', 'observation.', 'source.'))}
    features['source.capture_time_ns']['shape'] = [1]
    frame = module.copy_frame(row, features)
    np.testing.assert_array_equal(frame['action'], row['action'])
    np.testing.assert_array_equal(frame['observation.state'], row['observation.state'])
    assert frame['observation.images.front'].shape == (2, 4, 3)
    assert frame['observation.images.front'].dtype == np.uint8
    assert frame['source.capture_time_ns'].item() == 123456789
    assert frame['source.capture_time_ns'].shape == (1,)
    assert frame['source.capture_time_ns'].dtype == np.int64
    assert 'timestamp' not in frame and 'frame_index' not in frame
    assert frame['task'] == 'pick'


@pytest.mark.parametrize('corrupt', [None, 'action', 'image', 'source'])
def test_export_checks_matching_child_frames_and_original_bytes(module, tmp_path, monkeypatch, corrupt):
    import json
    import sys
    from types import SimpleNamespace
    import numpy as np
    native = module.native
    features = {key: dict(dtype='float32', shape=[6], names=native.JOINTS)
                for key in ('action', 'observation.state')}
    features['observation.images.front'] = dict(dtype='video', shape=[2, 4, 3])
    info = dict(robot_type='omx_follower', codebase_version='v3.0', fps=30,
                total_frames=16, total_episodes=2, features=features)
    rows = [dict(episode_index=episode, frame_index=frame, timestamp=frame/30,
                 action=np.full(6, episode*10+frame, dtype=np.float32),
                 **{'observation.state': np.full(6, episode*20+frame, dtype=np.float32),
                    'observation.images.front': np.full((3,2,4), frame/8, dtype=np.float32)}, task='pick')
            for episode in range(2) for frame in range(8)]
    report = native.inspect_frames(info, rows)
    report.update(repo_id='local/native', source_mode='leader_native', body_units='normalized_-100_100',
                  rig_revision='rig', calibration_revision='cal', files={'meta/info.json': 'a'*64})
    source = tmp_path/'source'
    output = tmp_path/'output'
    class Dataset(list):
        def __init__(self, data, metadata):
            super().__init__(data)
            self.meta = SimpleNamespace(info=metadata)
    written = {}
    class Writer:
        def __init__(self, **kwargs):
            self.root, self.rows, self.buffer, self.episode = kwargs['root'], [], [], 0
            (self.root/'meta').mkdir(parents=True)
            (self.root/'data').mkdir()
            (self.root/'meta/info.json').write_text('{}')
            (self.root/'data/part.parquet').write_bytes(b'data')
        def add_frame(self, row):
            self.buffer.append(row)
        def save_episode(self, **kwargs):
            for i, row in enumerate(self.buffer):
                row = dict(row, episode_index=self.episode, frame_index=i, timestamp=i/30)
                row['observation.images.front'] = row['observation.images.front'].transpose(2,0,1)/255
                if corrupt == 'action': row['action'] = row['action']+1
                if corrupt == 'image': row['observation.images.front'] *= 0
                self.rows.append(row)
            self.episode += 1
            self.buffer = []
        def finalize(self):
            metadata = dict(info, total_frames=len(self.rows), total_episodes=self.episode)
            written[self.root] = Dataset(self.rows, metadata)
    monkeypatch.setitem(sys.modules, 'lerobot.datasets.lerobot_dataset',
                        SimpleNamespace(LeRobotDataset=SimpleNamespace(create=lambda **kw: Writer(**kw))))
    monkeypatch.setattr(module, 'verified_source', lambda *a: Dataset(rows, info))
    original_files = native.dataset_files
    monkeypatch.setattr(native, 'dataset_files', lambda p: (
        {'meta/info.json': ('b' if corrupt == 'source' else 'a')*64}
        if Path(p) == source else original_files(p)))
    monkeypatch.setattr(native, 'load_dataset', lambda p, *a: written[Path(p)])
    document = module.selection(report, selections(report))
    if corrupt:
        with pytest.raises((ValueError, AssertionError)):
            module.export_segments(source, report, document, output)
        assert not (output/'split-receipt.json').exists()
    else:
        receipt = module.export_segments(source, report, document, output)
        assert receipt['segment_lineage']['train'][0]['start_frame'] == 2
        assert [r['frame_index'] for r in written[output/'train']] == [0,1,2]
        assert [r['action'][0] for r in written[output/'train']] == [2,3,4]
        assert receipt['decisions'][0]['outcome'] == 'unknown'
        assert json.loads((output/'split-receipt.json').read_text())['source'] == report
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'training/omx'))
        import native_cycle
        monkeypatch.setattr(native_cycle, 'native', native)
        assert native_cycle.validate_split(output) == receipt
        receipt['segment_lineage']['train'][0]['start_frame'] = 0
        with pytest.raises(ValueError, match='lineage'):
            module.validate_receipt(receipt)


def test_real_lerobot_segment_readback(module, tmp_path):
    pytest.importorskip('lerobot')
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    features = {key: dict(dtype='float32', shape=(6,), names=module.native.JOINTS)
                for key in ('action','observation.state')}
    features['observation.images.front'] = dict(dtype='video',shape=(32,32,3),names=['height','width','channels'])
    root = tmp_path/'native'
    writer = LeRobotDataset.create(repo_id='local/segment-source',root=root,fps=30,
        robot_type='omx_follower',features=features,use_videos=True,video_backend='pyav',
        vcodec='h264',batch_encoding_size=1)
    try:
        for episode in range(2):
            for frame in range(8):
                writer.add_frame(dict(action=np.full(6,episode*10+frame,dtype=np.float32),
                    **{'observation.state':np.full(6,episode*10+frame-1,dtype=np.float32),
                       'observation.images.front':np.full((32,32,3),frame*20,dtype=np.uint8)},task='pick'))
            writer.save_episode(parallel_encoding=False)
    finally:
        writer.finalize()
    report = module.native.inspect_dataset(root,'local/segment-source',body_units='normalized_-100_100',
        rig_revision='rig',calibration_revision='cal',source_mode='leader_native')
    receipt = module.export_segments(root,report,module.selection(report,selections(report)),tmp_path/'segments')
    assert receipt['reader_verified'] is True
    assert receipt['splits'] == {'train':[0],'eval':[1]}
    reader = module.native.load_dataset(tmp_path/'segments/train','local/segment-source_train')
    assert len(reader) == 3
    assert [reader[i]['action'][0].item() for i in range(3)] == [2,3,4]
