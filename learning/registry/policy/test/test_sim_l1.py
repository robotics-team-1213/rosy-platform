import copy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'learning/registry/policy'), str(ROOT / 'contracts/learning/src'), str(ROOT / 'test'),
                str(Path(__file__).parent)]
from registry import Registry
from sim_l1 import registered_checkpoint_sha256, sim_l1_assessment
from test_registry import source


def report(**change):
    doc = {'schema': 'rosy.sim-l1-eval/1', 'task': 'stack-t1', 'physics_candidate': 'servo-friction-20261109',
           'checkpoint_sha256': 'ab' * 32, 'randomisation': {'tcp_x_m': [0.074, 0.0885], 'fk_bias_m': [-0.008, 0.008]},
           'policy_episodes': 20, 'policy_successes': 18, 'teacher_episodes': 20, 'teacher_successes': 17,
           'verdict': 'pass'}
    doc.update(change)
    return doc


def test_policy_at_or_above_teacher_passes_and_is_marked_sim_only():
    result = sim_l1_assessment(report())
    assert result['verdict'] == 'pass' and result['real_evidence'] is False
    assert result['checkpoint_sha256'] == 'ab' * 32 and result['policy_rate'] == 0.9


def test_below_teacher_or_small_sample_is_rejected():
    low = sim_l1_assessment(report(policy_successes=10, verdict='reject'))
    assert low['reasons'] == ['below_teacher_success_rate']
    few = sim_l1_assessment(report(policy_episodes=5, policy_successes=5, verdict='reject'))
    assert few['reasons'] == ['too_few_episodes']


@pytest.mark.parametrize('change', [
    {'verdict': 'reject'}, {'policy_successes': 21}, {'task': 'pick-1'}, {'checkpoint_sha256': 'AB' * 32},
    {'randomisation': {}}, {'randomisation': {'x': [2, 1]}}, {'randomisation': {'x': [0, float('nan')]}},
    {'policy_episodes': True}, {'policy_episodes': 0, 'policy_successes': 0, 'verdict': 'reject'}, {'physics_candidate': ''}, {'schema': 'x'}])
def test_forged_or_invalid_report_is_refused(change):
    with pytest.raises(ValueError):
        sim_l1_assessment(copy.deepcopy(report(**change)))


def test_registry_records_it_without_changing_stage(tmp_path):
    root, doc = source(tmp_path)
    registry = Registry(tmp_path / 'registry')
    registry.register(root)
    own = registered_checkpoint_sha256(root, doc)
    result = registry.record_sim_l1(doc['revision'], report(checkpoint_sha256=own))
    assert registry.record_sim_l1(doc['revision'], report(checkpoint_sha256=own)) == result  # idempotent
    assert registry.show(doc['revision'])['stage'] == 'unregistered'
    assert registry.history()[-1]['data'] == result and len(registry.history()) == 2
    with pytest.raises(ValueError):
        registry.record_sim_l1('0' * 64, report(checkpoint_sha256=own))


def test_report_for_another_checkpoint_is_not_recorded_under_this_revision(tmp_path):
    root, doc = source(tmp_path)
    registry = Registry(tmp_path / 'registry')
    registry.register(root)
    with pytest.raises(ValueError, match='registered policy files'):
        registry.record_sim_l1(doc['revision'], report())  # 'ab' * 32 is not this policy's checkpoint
    assert len(registry.history()) == 1


def test_digest_matches_the_runner_checkpoint_digest(tmp_path):
    sys.path.insert(0, str(ROOT / 'integrations/robots/omx/src'))
    from rosy.integrations.robots.omx.policy_runner import checkpoint_digest
    root, doc = source(tmp_path)
    ckpt = tmp_path / 'ckpt'
    ckpt.mkdir()
    (ckpt / 'weights.bin').write_bytes(b'weights')
    assert checkpoint_digest(ckpt) == registered_checkpoint_sha256(root, doc)
