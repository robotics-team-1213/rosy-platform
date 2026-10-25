"""Native grasp selections preserve original lineage and corresponding observations/actions."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

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
@pytest.mark.parametrize('bimanual', [False, True])
def test_export_checks_matching_child_frames_and_original_bytes(module, tmp_path, monkeypatch, corrupt, bimanual):
    import json
    import sys
    from types import SimpleNamespace
    import numpy as np
    native = module.native
    names = ([f'{arm}.{joint}' for arm in ('arm_a', 'arm_b') for joint in native.JOINTS]
             if bimanual else native.JOINTS)
    size = len(names)
    robot_type = 'bi_omx_follower' if bimanual else 'omx_follower'
    features = {key: dict(dtype='float32', shape=[size], names=names)
                for key in ('action', 'observation.state')}
    features['observation.images.front'] = dict(dtype='video', shape=[2, 4, 3])
    info = dict(robot_type=robot_type, codebase_version='v3.0', fps=30,
                total_frames=16, total_episodes=2, features=features)
    rows = [dict(episode_index=episode, frame_index=frame, timestamp=frame/30,
                 action=np.full(size, episode*10+frame, dtype=np.float32),
                 **{'observation.state': np.full(size, episode*20+frame, dtype=np.float32),
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
            assert kwargs['robot_type'] == robot_type
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


def intake_module():
    spec = importlib.util.spec_from_file_location('collection_intake', Path(__file__).resolve().parents[1]/'collection_intake.py')
    intake = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(intake)
    return intake


TEACHER = dict(kind='replay_trajectory', segments=dict(A=[0, 3], reset=[3, 4], B=[4, 7]),
               source=dict(dataset='local/omx-pick', episode=3, split_s=2.0, end_s=4.5))


def stub_intake(intake, monkeypatch, collections, sizes, modes=None):
    """prepare_native without LeRobot: sealed manifests, source episodes and the aggregate are stubs."""
    import sys
    def aggregate(*args, aggr_root, **kwargs):
        (aggr_root/'meta').mkdir(parents=True)
        (aggr_root/'data').mkdir()
        (aggr_root/'meta/info.json').write_text('{}')
        (aggr_root/'data/part.parquet').write_bytes(b'data')
    monkeypatch.setitem(sys.modules, 'lerobot.datasets.aggregate', SimpleNamespace(aggregate_datasets=aggregate))
    modes = modes or ['leader_native'] * len(collections)
    manifests = {c: dict(session_id=c.name, rig_revision='rig', calibration_revision='cal', sealed_ns=i,
                         source_mode=mode, **(dict(teacher_sha256=f'{i}'*64, teacher=TEACHER)
                                              if mode == 'scripted_teacher' else {}))
                 for i, (c, mode) in enumerate(zip(collections, modes))}
    monkeypatch.setattr(intake, '_sealed_collection', lambda c: (manifests[Path(c)], 'f'*64))
    monkeypatch.setattr(intake, '_source_episodes', lambda root, repo: [
        dict(episode_index=i, content_sha256=f'{root.parent.name}{i}') for i in range(sizes[root.parent.name])])
    for c in collections:
        (c/'dataset').mkdir(parents=True, exist_ok=True)
        (c/'calibration').mkdir(exist_ok=True)
        for name in ('session.json', 'record-config.json', 'manifest.json'):
            (c/name).write_text('{}')
    class Inspected(Exception):
        pass
    def inspect(output, *args, **kwargs):
        raise Inspected(json.loads((Path(output)/'static_episodes.json').read_text()))
    monkeypatch.setattr(intake, 'inspect_dataset', inspect)
    return Inspected


def marker(root, **values):
    (root/'static_episodes.json').write_text(json.dumps(dict(dict(episodes=3, static=[1], threshold=1.0), **values)))


def test_do_not_train_refuses_the_whole_dataset_at_intake_split_and_segment_export(module, report, tmp_path, monkeypatch):
    source = tmp_path/'source'
    (source/'dataset').mkdir(parents=True)
    (source/'DO_NOT_TRAIN.txt').write_text('leader never moved\n')
    (source/'dataset'/'DO_NOT_TRAIN.txt').write_text('leader never moved\n')
    with pytest.raises(ValueError, match='DO_NOT_TRAIN'):
        module.export_segments(source, report, module.selection(report, selections(report)), tmp_path/'segments')
    with pytest.raises(ValueError, match='DO_NOT_TRAIN'):
        module.native.split_reviewed(source, report, report['episodes'], tmp_path/'split')
    intake = intake_module()
    stub_intake(intake, monkeypatch, [source], {'source': 2})
    with pytest.raises(ValueError, match='DO_NOT_TRAIN'):
        intake.prepare_native([source], tmp_path/'prepared', 'local/native')
    assert not any((tmp_path/name).exists() for name in ('segments', 'split', 'prepared'))


@pytest.mark.parametrize('values', [dict(static=[3]), dict(static=[-1]), dict(static=[True]), dict(static=['1']),
                                    dict(static=[1, 1]), dict(static=None), dict(episodes=4), dict(episodes='3'),
                                    dict(threshold='1'), dict(extra=1), 'not json', 'all static'])
def test_malformed_or_all_static_marker_refuses_the_whole_dataset(module, tmp_path, values):
    if values == 'not json':
        (tmp_path/'static_episodes.json').write_text('{')
    else:
        marker(tmp_path, **(dict(static=[0, 1, 2]) if values == 'all static' else values))
    with pytest.raises(ValueError, match='refused'):
        module.native.static_episodes(tmp_path, 3)


def test_static_episodes_are_excluded_and_recorded_through_inspection_splits_and_segments(module, tmp_path, monkeypatch):
    native = module.native
    marker(tmp_path)
    assert native.static_episodes(tmp_path, 3) == [1]
    episodes = [dict(episode_index=i, frames=8, content_sha256=str(i)*64, session_id=f's{i}', cycle_id=f'c{i}')
                for i in range(3)]
    for name, value in (('dataset_files', lambda root: {}),
                        ('load_dataset', lambda *a: type('Dataset', (list,), dict(meta=SimpleNamespace(info={})))()),
                        ('inspect_frames', lambda *a: dict(episodes=copy.deepcopy(episodes))),
                        ('bind_capture', lambda *a, **k: {}), ('bind_environment', lambda *a, **k: {})):
        monkeypatch.setattr(native, name, value)
    report = native.inspect_dataset(tmp_path, 'local/native', body_units='degrees', rig_revision='rig',
                                    calibration_revision='cal')
    assert report['excluded_episodes'] == [dict(episode_index=1, reason=native.STATIC_REASON)]
    report['source_mode'] = 'leader_native'
    del report['files']  # environment binding is stubbed out here
    decisions = [dict(e, split=split, outcome='success', reviewer='human', reason='ok')
                 for e, split in zip(episodes, ('train', 'train', 'eval'))]
    assert native.reviewed_splits(report, decisions) == {'train': [0], 'eval': [2]}
    rows = [dict(row, split=split) for row, split in zip(selections(dict(report, episodes=episodes)) +
            selections(dict(report, episodes=episodes[2:])), ('train', 'train', 'eval'))]
    document = module.selection(report, rows)
    assert module.validate_selection(report, document) == {'train': [0], 'eval': [2]}
    assert [row['split'] for row in module.parent_decisions(report, document)] == ['train', 'exclude', 'eval']


def test_intake_carries_static_episodes_over_with_aggregated_indexes(tmp_path, monkeypatch):
    first, second = tmp_path/'first', tmp_path/'second'
    intake = intake_module()
    inspected = stub_intake(intake, monkeypatch, [first, second], {'first': 2, 'second': 3})
    marker(first/'dataset', episodes=2, static=[0], threshold=0.5)
    marker(second/'dataset', static=[2], threshold=1.0)
    with pytest.raises(inspected) as carried:
        intake.prepare_native([first, second], tmp_path/'prepared', 'local/native')
    assert carried.value.args[0] == dict(episodes=5, static=[0, 4], threshold=1.0)


def test_intake_prepared_before_exclusion_is_refused_from_its_sealed_manifests(module, tmp_path):
    provenance = tmp_path/'rosy_provenance'/'session-000000'
    provenance.mkdir(parents=True)
    (provenance/'manifest.json').write_text(json.dumps(dict(files={'dataset/static_episodes.json': 'a'*64})))
    with pytest.raises(ValueError, match='prepare it again'):
        module.native.static_episodes(tmp_path, 3)


def test_intake_refuses_leader_and_teacher_recordings_together(tmp_path, monkeypatch):
    first, second = tmp_path/'first', tmp_path/'second'
    intake = intake_module()
    stub_intake(intake, monkeypatch, [first, second], {'first': 2, 'second': 2},
                modes=['leader_native', 'scripted_teacher'])
    with pytest.raises(ValueError, match='cannot share one intake'):
        intake.prepare_native([first, second], tmp_path/'prepared', 'local/native')
    assert not (tmp_path/'prepared').exists()


@pytest.mark.parametrize('fault', ['do_not_train', 'three_episodes'])
def test_teacher_intake_keeps_the_do_not_train_rule_and_episodes_a_and_b(tmp_path, monkeypatch, fault):
    source = tmp_path/'source'
    intake = intake_module()
    stub_intake(intake, monkeypatch, [source], {'source': 3 if fault == 'three_episodes' else 2},
                modes=['scripted_teacher'])
    if fault == 'do_not_train':
        (source/'dataset'/'DO_NOT_TRAIN.txt').write_text('leader never moved\n')
    with pytest.raises(ValueError, match='DO_NOT_TRAIN' if fault == 'do_not_train' else 'episodes A and B'):
        intake.prepare_native([source], tmp_path/'prepared', 'local/native')
    assert not (tmp_path/'prepared').exists()


def test_teacher_intake_binds_the_teacher_not_its_site_path_and_carries_static_episodes(tmp_path, monkeypatch):
    import hashlib
    first, second = tmp_path/'first', tmp_path/'second'
    intake = intake_module()
    stub_intake(intake, monkeypatch, [first, second], {'first': 2, 'second': 2}, modes=['scripted_teacher'] * 2)
    marker(second/'dataset', episodes=2, static=[1], threshold=1.0)
    site_path = '/home/operator/omx-replays/arm-s-cycle.json'
    for collection in (first, second):
        (collection/'session.json').write_text(json.dumps(dict(source_mode='scripted_teacher', replay=dict(
            path=site_path, sha256='0'*64, segments=TEACHER['segments'], source=TEACHER['source']))))
    seen = {}
    class Inspected(Exception):
        pass
    def inspect(output, repo_id, **kwargs):
        seen.update(kwargs, static=json.loads((Path(output)/'static_episodes.json').read_text()))
        raise Inspected
    monkeypatch.setattr(intake, 'inspect_dataset', inspect)
    with pytest.raises(Inspected):
        intake.prepare_native([first, second], tmp_path/'prepared', 'local/native')
    capture = seen['capture_provenance']
    assert seen['source_mode'] == capture['source_mode'] == 'scripted_teacher'
    assert 'collection_manifest_sha256' not in capture
    assert capture['teacher_sha256'] == hashlib.sha256(json.dumps(['0'*64, '1'*64]).encode()).hexdigest()
    assert capture['teachers'] == [dict(session_id=c.name, teacher_sha256=f'{i}'*64, **TEACHER)
                                   for i, c in enumerate((first, second))]
    assert seen['static'] == dict(episodes=4, static=[3], threshold=1.0)
    copied = json.loads((tmp_path/'prepared/rosy_provenance/session-000000/session.json').read_text())
    assert copied['replay'] == dict(sha256='0'*64, segments=TEACHER['segments'], source=TEACHER['source'])
    assert site_path not in json.dumps(capture)
    assert not any(site_path.encode() in p.read_bytes() for p in (tmp_path/'prepared').rglob('*') if p.is_file())
    from native_capture import bind_capture
    bound = bind_capture([dict(episode_index=i) for i in range(4)], capture['files'], source_mode='scripted_teacher',
                         body_units='normalized_-100_100', rig_revision='rig', calibration_revision='cal',
                         provenance=capture)
    assert [e['cycle_id'] for e in bound['episodes']] == ['first-ep0000', 'first-ep0001', 'second-ep0000', 'second-ep0001']
