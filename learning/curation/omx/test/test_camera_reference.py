"""D-792 S3 first slice: OMX intake refuses mismatched camera references and records only revisions."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
import camera_reference  # noqa: E402
from teacher_fixture import CAMERA_IDENTITY as IDENTITY, camera_reference as reference  # noqa: E402


def segments_test():
    spec = importlib.util.spec_from_file_location('segments_fixture', HERE/'test_native_segments.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INFO = dict(fps=10, features={'observation.images.top': dict(dtype='video', shape=[24, 32, 3],
                                                             names=['height', 'width', 'channels'])})


@pytest.fixture
def intake(tmp_path, monkeypatch):
    """A stubbed one-recording prepare_native whose aggregate writes a LeRobot-shaped info.json."""
    fixture = segments_test()
    module = fixture.intake_module()
    fixture.stub_intake(module, monkeypatch, [tmp_path/'source'], {'source': 2})
    def aggregate(*args, aggr_root, **kwargs):
        (aggr_root/'meta').mkdir(parents=True)
        (aggr_root/'meta/info.json').write_text(json.dumps(INFO))
    monkeypatch.setitem(sys.modules, 'lerobot.datasets.aggregate', SimpleNamespace(aggregate_datasets=aggregate))
    seen = {}
    class Inspected(Exception):
        pass
    def inspect(output, repo_id, **kwargs):
        seen.update(kwargs)
        raise Inspected
    monkeypatch.setattr(module, 'inspect_dataset', inspect)
    def run(references=None):
        with pytest.raises(Inspected):
            module.prepare_native([tmp_path/'source'], tmp_path/'prepared', 'local/native',
                                  **({} if references is None else dict(camera_references=references)))
        return seen
    module.run = run
    return module


def test_cli_values_refuse_a_role_given_twice_or_without_a_path():
    assert camera_reference.parse(['top=a.json', 'front=b.json']) == dict(top=Path('a.json'), front=Path('b.json'))
    assert camera_reference.parse(None) == {}
    with pytest.raises(ValueError, match='given twice'):
        camera_reference.parse(['top=a.json', 'top=b.json'])
    for value in ('top', '=a.json', 'top='):
        with pytest.raises(ValueError, match='ROLE=PATH'):
            camera_reference.parse([value])


def test_revision_is_recorded_in_capture_and_inspection_without_identity_or_path(intake, tmp_path):
    path = reference(tmp_path/'state/camera-setup')
    seen = intake.run(dict(top=path))
    assert seen['camera_setup'] == seen['capture_provenance']['camera_setup'] == dict(top=path.stem)
    blob = json.dumps(seen)
    assert IDENTITY not in blob and 'camera-setup' not in blob and str(tmp_path) not in blob


def test_without_references_capture_and_inspection_are_unchanged(intake):
    seen = intake.run()
    assert seen['camera_setup'] is None and 'camera_setup' not in seen['capture_provenance']


@pytest.mark.parametrize('fault, match', [
    ('stem', 'file name differs'), ('seal', 'canonical revision'), ('role', 'reference is for role front'),
    ('json', 'Expecting value')])
def test_tampered_or_misnamed_reference_is_refused_before_any_output(intake, tmp_path, fault, match):
    path = reference(tmp_path/'refs', role='front' if fault == 'role' else 'top',
                     **(dict(fps=12) if fault == 'seal' else {}))
    if fault == 'stem':
        path = path.rename(path.with_name('f'*64 + '.json'))
    if fault == 'json':
        path.write_text('{', encoding='utf-8')
    with pytest.raises(ValueError, match=match):
        intake.prepare_native([tmp_path/'source'], tmp_path/'prepared', 'local/native', camera_references=dict(top=path))
    assert not (tmp_path/'prepared').exists()


@pytest.mark.parametrize('refs, match', [
    (dict(top=dict(width=24, height=32)), 'width, height or fps'),  # HWC [24, 32, 3] is 32 wide
    (dict(top=dict(fps=30)), 'width, height or fps'),
    (dict(top={}, front=dict(role='front')), 'differ from dataset cameras'),
])
def test_role_set_size_or_fps_mismatch_against_merged_info_is_refused(intake, tmp_path, refs, match):
    references = {role: reference(tmp_path/'refs', **values) for role, values in refs.items()}
    with pytest.raises(ValueError, match=match):
        intake.prepare_native([tmp_path/'source'], tmp_path/'prepared', 'local/native', camera_references=references)
    assert not (tmp_path/'prepared'/'inspection.json').exists()


@pytest.fixture
def native(monkeypatch):
    spec = importlib.util.spec_from_file_location('native_review', HERE.parent/'native_review.py')
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    episodes = [dict(episode_index=0, frames=3, content_sha256='0'*64)]
    for name, value in (('dataset_files', lambda root: {}),
                        ('load_dataset', lambda *a: type('Dataset', (list,), dict(meta=SimpleNamespace(info={})))()),
                        ('inspect_frames', lambda *a: dict(camera_keys=['observation.images.top'],
                                                           episodes=copy.deepcopy(episodes))),
                        ('bind_capture', lambda *a, **k: {}), ('bind_environment', lambda *a, **k: {}),
                        ('static_episodes', lambda *a: [])):
        monkeypatch.setattr(native, name, value)
    return native


def test_inspection_records_camera_setup_only_when_given_and_refuses_other_roles(native, tmp_path):
    def inspect(**kwargs):
        return native.inspect_dataset(tmp_path, 'local/native', body_units='degrees', rig_revision='rig',
                                      calibration_revision='cal', **kwargs)
    assert 'camera_setup' not in inspect()
    assert inspect(camera_setup=dict(top='a'*64))['camera_setup'] == dict(top='a'*64)
    for bad in (dict(front='a'*64), dict(top='A'*64), dict(top='a'*64, front='b'*64), {}):
        with pytest.raises(ValueError, match='camera_setup must map'):
            inspect(camera_setup=bad)
    with pytest.raises(ValueError, match='other camera references'):
        inspect(camera_setup=dict(top='a'*64), capture_provenance=dict(camera_setup=dict(top='b'*64)))
    with pytest.raises(ValueError, match='camera_setup must map'):  # a recheck that drops the field is refused
        inspect(capture_provenance=dict(camera_setup=dict(top='b'*64)))


PINNED_DRIVER = r'''
import json, pathlib, sys
source, tmp = map(pathlib.Path, sys.argv[1:])
sys.path[:0] = [str(source/'learning/curation/omx'), str(source/'learning/curation/omx/test')]
import collection_intake, native_segments, teacher_fixture as fixture
plain = fixture.seal_teacher(tmp/'collections', 'arm-s-replay-1', fixture.teacher_dataset(tmp/'recordings/one'))
good = fixture.camera_reference(tmp/'state/camera-setup', width=32, height=32, fps=10)
wrong = fixture.camera_reference(tmp/'state/camera-setup', width=32, height=32, fps=30)
def prepare(name, path):
    return collection_intake.prepare_native([plain], tmp/name, 'local/'+name, camera_references=dict(top=path),
                                            **fixture.OPERATOR)
prepare('prepared', good)
out = tmp/'prepared'
report = json.loads((out/'inspection.json').read_text())
native_segments.verified_source(out, report)
try:
    prepare('prepared-wrong', wrong)
    refused = None
except ValueError as exc:
    refused = str(exc)
print(json.dumps(dict(
    feature=json.loads((out/'meta/info.json').read_text())['features']['observation.images.top'],
    report=report['camera_setup'], capture=json.loads((out/'capture.json').read_text())['camera_setup'],
    revision=good.stem, refused=refused,
    leaked=sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file()
                  and any(s in p.read_bytes() for s in (fixture.CAMERA_IDENTITY.encode(), b'camera-setup/'))))))
'''


def test_pinned_real_lerobot_intake_records_the_reference_and_refuses_other_fps(tmp_path):
    """Real LeRobot 0.4.4 info.json in the pinned learner venv (see the pinned intake test)."""
    import os
    import subprocess
    if os.environ.get('ROSY_RUN_PINNED_LEARNING') != '1':
        pytest.skip('explicit existing isolated learner environment required')
    python = Path.home()/'.local/share/rosy-learning-center/venv-cpu/bin/python'
    assert python.is_file(), 'existing pinned learner Python is unavailable'
    env = {key: os.environ[key] for key in ('HOME', 'PATH', 'USER', 'LOGNAME') if key in os.environ}
    env.update(HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='2')
    result = subprocess.run([str(python), '-I', '-B', '-c', PINNED_DRIVER, str(HERE.parents[3]), str(tmp_path)],
                            capture_output=True, text=True, env=env, timeout=300, check=False)
    assert result.returncode == 0, result.stderr[-4000:]
    proof = json.loads(result.stdout.splitlines()[-1])
    assert proof['feature']['names'] == ['height', 'width', 'channels'] and proof['feature']['shape'] == [32, 32, 3]
    assert proof['report'] == proof['capture'] == dict(top=proof['revision'])
    assert 'width, height or fps' in proof['refused'] and proof['leaked'] == []
