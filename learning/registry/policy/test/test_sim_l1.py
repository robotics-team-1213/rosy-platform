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


def report_v2(**change):
    doc = {
        'schema': 'rosy.sim-l1-eval/2', 'task': 'ship-h1', 'physics_candidate': 'v24-20261122',
        'checkpoint_sha256': 'cd' * 32, 'randomisation': {'pose_random': [0.0, 1.0]},
        'profiles': {
            'nominal': {'n_action_steps': 4, 'delay_frames': 0, 'policy_episodes': 18, 'policy_successes': 16,
                        'teacher_episodes': 18, 'teacher_successes': 16, 'neighbour_disturbed': 0, 'arm_link_contacts': 0},
            'delayed': {'n_action_steps': 8, 'delay_frames': 7, 'policy_episodes': 18, 'policy_successes': 16,
                        'teacher_episodes': 18, 'teacher_successes': 15, 'neighbour_disturbed': 0, 'arm_link_contacts': 0},
        },
        'per_layer': {
            'l0': {'episodes': 12, 'lifted': 12, 'sustained_lift': 12, 'successes': 12},
            'l1': {'episodes': 12, 'lifted': 12, 'sustained_lift': 12, 'successes': 11},
            'l2': {'episodes': 12, 'lifted': 12, 'sustained_lift': 11, 'successes': 9},
        },
        'verdict': 'pass',
    }
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


def test_v2_validates_nominal_delayed_collision_and_per_layer():
    passed = sim_l1_assessment(report_v2())
    assert passed['verdict'] == 'pass' and passed['validator'] == 'rosy-sim-l1-gate/2'
    assert passed['profiles']['delayed']['delay_frames'] == 7
    assert passed['per_layer']['l2']['success_rate'] == 9 / 12

    delayed_drop = report_v2(verdict='reject')
    delayed_drop['profiles']['delayed']['policy_successes'] = 10
    assert 'delayed_below_teacher' in sim_l1_assessment(delayed_drop)['reasons']

    hit = report_v2(verdict='reject')
    hit['profiles']['delayed']['neighbour_disturbed'] = 1
    assert 'collision_detected' in sim_l1_assessment(hit)['reasons']

    zero_l2 = report_v2(verdict='reject')
    zero_l2['per_layer']['l2']['successes'] = 0
    assert 'layer_zero_success' in sim_l1_assessment(zero_l2)['reasons']

    with pytest.raises(ValueError):
        sim_l1_assessment(report_v2(verdict='reject'))
    bad_delay = report_v2()
    bad_delay['profiles']['delayed']['delay_frames'] = 0
    with pytest.raises(ValueError):
        sim_l1_assessment(bad_delay)

    bad_layer_key = report_v2()
    bad_layer_key['per_layer'][1] = {'episodes': 12, 'lifted': 12, 'sustained_lift': 12, 'successes': 12}
    with pytest.raises(ValueError, match='layer name'):
        sim_l1_assessment(bad_layer_key)

    bad_layer_counts = report_v2()
    bad_layer_counts['per_layer']['l0']['lifted'] = 5
    bad_layer_counts['per_layer']['l0']['successes'] = 6
    with pytest.raises(ValueError, match='invalid layer counts'):
        sim_l1_assessment(bad_layer_counts)


def test_registry_records_it_without_changing_stage(tmp_path):
    root, doc = source(tmp_path)
    registry = Registry(tmp_path / 'registry')
    registry.register(root)
    own = registered_checkpoint_sha256(root, doc)
    result = registry.record_sim_l1(doc['revision'], report(checkpoint_sha256=own))
    assert registry.record_sim_l1(doc['revision'], report(checkpoint_sha256=own)) == result  # idempotent
    v2 = registry.record_sim_l1(doc['revision'], report_v2(checkpoint_sha256=own))
    assert registry.record_sim_l1(doc['revision'], report_v2(checkpoint_sha256=own)) == v2
    assert registry.show(doc['revision'])['stage'] == 'unregistered'
    assert registry.history()[-1]['data'] == v2 and len(registry.history()) == 3
    with pytest.raises(ValueError):
        registry.record_sim_l1('0' * 64, report(checkpoint_sha256=own))


def test_report_for_another_checkpoint_is_not_recorded_under_this_revision(tmp_path):
    root, doc = source(tmp_path)
    registry = Registry(tmp_path / 'registry')
    registry.register(root)
    with pytest.raises(ValueError, match='registered policy files'):
        registry.record_sim_l1(doc['revision'], report())  # 'ab' * 32 is not this policy's checkpoint
    assert len(registry.history()) == 1


def test_digest_matches_the_contract_checkpoint_digest(tmp_path):
    from rosy.contracts.learning.digest import checkpoint_sha256
    root, doc = source(tmp_path)
    ckpt = tmp_path / 'ckpt'
    ckpt.mkdir()
    (ckpt / 'weights.bin').write_bytes(b'weights')
    assert checkpoint_sha256(ckpt) == registered_checkpoint_sha256(root, doc)
