"""D-782 W1: world-model windows keep failed attempts, honour session splits and never bridge gaps."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import world_model_fixture as fixture


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location('world_model_dataset', HERE.parent/'world_model_dataset.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def build(module, tmp_path, roots, **kwargs):
    splits = {name: split for name, (_, split) in roots.items()}
    return module.build([root for root, _ in roots.values()], tmp_path/'out', horizon=kwargs.pop('horizon', 2),
                        splits=splits, **kwargs)


def test_failed_and_aborted_attempts_become_windows(module, tmp_path):
    roots = fixture.sessions(tmp_path)
    receipt = build(module, tmp_path, roots)
    dataset, digest = module.load(tmp_path/'out')
    assert receipt['dataset_sha256'] == digest and receipt['incomplete_attempts'] == 1
    assert receipt['windows'] == dict(train=12, eval=6, test=6)  # 8 frames, horizon 2 -> 6 windows per attempt
    aborted = [a for a in dataset['attempts'] if not a['complete']]
    assert aborted[0]['reason'].startswith('ABORT') and aborted[0]['windows'] == 6
    window = dataset['windows']['eval'][0]
    assert len(window['action']) == 2 and len(window['next_states']) == 2
    assert receipt['task_success_inferred'] is False and receipt['physical_acceptance'] is False


def test_labels_are_bounded_and_need_a_reviewer(module, tmp_path):
    roots = fixture.sessions(tmp_path)
    labels = {'labels': [dict(session_id='s-train', cycle_id='s-train-cycle-1', outcome='failure',
                              object_result='dropped', reviewer='op', reason='block fell at lift')]}
    build(module, tmp_path, roots, labels=labels)
    dataset, _ = module.load(tmp_path/'out')
    assert [(a['outcome'], a['object_result']) for a in dataset['attempts'] if a['cycle_id'].endswith('-1')] == [
        ('failure', 'dropped')]
    good = labels['labels'][0]
    for index, bad in enumerate((dict(good, object_result='slipped'), dict(good, reviewer=''),
                                 dict(good, cycle_id='no-such-cycle'))):
        splits = {name: split for name, (_, split) in roots.items()}
        with pytest.raises(ValueError, match='object_result|reviewer|attempt'):
            module.build([r for r, _ in roots.values()], tmp_path/f'bad-{index}', horizon=2, splits=splits,
                         labels={'labels': [bad]})
        assert not (tmp_path/f'bad-{index}').exists()


@pytest.mark.parametrize('fault', ['missing', 'unknown', 'no_eval'])
def test_every_session_needs_one_split_and_train_eval_exist(module, tmp_path, fault):
    roots = fixture.sessions(tmp_path)
    splits = {name: split for name, (_, split) in roots.items()}
    if fault == 'missing': del splits['s-test']
    if fault == 'unknown': splits['s-test'] = 'holdout'
    if fault == 'no_eval': splits['s-eval'] = 'train'
    with pytest.raises(ValueError, match='split|eval'):
        module.build([r for r, _ in roots.values()], tmp_path/'out', horizon=2, splits=splits)
    assert not (tmp_path/'out').exists()


def test_capture_gaps_are_never_bridged(module):
    rows = [dict(time_ns=t) for t in (0, 100_000_000, 200_000_000, 500_000_000, 600_000_000)]
    assert [len(s) for s in module._segments(rows, 10)] == [3, 2]


def test_tampered_raw_session_is_refused(module, tmp_path):
    roots = fixture.sessions(tmp_path)
    sample = roots['s-eval'][0]/'episodes/000000/samples.jsonl'
    sample.write_text(sample.read_text().replace('"frame_index": 0', '"frame_index": 0 '), encoding='utf-8')
    with pytest.raises(ValueError, match='hash'):
        build(module, tmp_path, roots)


def test_tampered_dataset_is_refused_on_load(module, tmp_path):
    build(module, tmp_path, fixture.sessions(tmp_path))
    data = tmp_path/'out/dataset.json'
    data.write_bytes(data.read_bytes().replace(b'"horizon": 2', b'"horizon": 3'))
    with pytest.raises(ValueError, match='receipt'):
        module.load(tmp_path/'out')


def test_mixed_rig_or_calibration_is_refused(module, tmp_path):
    roots = fixture.sessions(tmp_path)
    manifest_path = roots['s-test'][0]/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['calibration_revision'] = 'cal-2'
    manifest_path.write_text(json.dumps(manifest)+'\n')
    with pytest.raises(ValueError, match='calibration'):
        build(module, tmp_path, roots)
