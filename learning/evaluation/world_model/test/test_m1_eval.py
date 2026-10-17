"""D-782 §6: an M1 artifact passes only by beating hold and reach at every horizon step on held-out sessions."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/'learning/curation/omx/test'))
import world_model_fixture as fixture


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


builder = _load('world_model_dataset', ROOT/'learning/curation/omx/world_model_dataset.py')
job = _load('m1_job', ROOT/'learning/training/world_model/m1_job.py')
evaluation = _load('m1_eval', ROOT/'learning/evaluation/world_model/m1_eval.py')


def trained(tmp_path, **session_kwargs):
    roots = fixture.sessions(tmp_path, frames=40, **session_kwargs)
    builder.build([r for r, _ in roots.values()], tmp_path/'dataset', horizon=2,
                  splits={n: s for n, (_, s) in roots.items()})
    job.train(tmp_path/'dataset', tmp_path/'run')
    return tmp_path/'dataset', tmp_path/'run/artifact.json'


def test_learnable_dynamics_beat_both_baselines(tmp_path):
    dataset, artifact = trained(tmp_path)
    report = evaluation.evaluate(dataset, artifact, tmp_path/'eval')
    assert report['verdict'] == 'pass' and report['beats_both_baselines_by_step'] == [True, True]
    assert report['mae_by_step']['model'][0] < 0.1 * report['mae_by_step']['hold'][0]
    assert 0 <= report['two_sigma_coverage'] <= 1 and report['offline_only'] is True
    assert json.loads((tmp_path/'eval/eval-report.json').read_text()) == report


def test_a_still_arm_cannot_beat_the_hold_baseline(tmp_path):
    dataset, artifact = trained(tmp_path, still=True)
    report = evaluation.evaluate(dataset, artifact, tmp_path/'eval')
    assert report['verdict'] == 'reject' and report['mae_by_step']['hold'] == [0.0, 0.0]


def test_artifact_from_another_dataset_is_refused(tmp_path):
    (tmp_path/'a').mkdir()
    (tmp_path/'b').mkdir()
    _, artifact = trained(tmp_path/'a')
    other, _ = trained(tmp_path/'b', still=True)
    with pytest.raises(ValueError, match='another dataset'):
        evaluation.evaluate(other, artifact, tmp_path/'eval')


def test_train_split_is_not_an_evaluation_split(tmp_path):
    dataset, artifact = trained(tmp_path)
    with pytest.raises(ValueError, match='eval'):
        evaluation.evaluate(dataset, artifact, tmp_path/'eval', split='train')
