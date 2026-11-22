"""D-1024 1: simulated L1 evaluation record. Sim evidence replaces only the held-out part of L1, never L2/L3 (D-911 4)."""
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'contracts/learning/src'))
from rosy.contracts.learning.digest import checkpoint_sha256  # noqa: E402

TASKS = ('stack-t1', 'stack-t2', 'stack-t3', 'ship-h1')
MIN_EPISODES = 10  # shortcut: G4-sized sample per arm; raise when the first real shadow data shows the spread


def _count(report, key):
    value = report.get(key)
    if type(value) is not int or value < 0:
        raise ValueError(f'invalid count {key}')
    return value


def _sha256(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('lowercase checkpoint sha256 required')


def registered_checkpoint_sha256(root, policy):
    """The runner's checkpoint digest (relative path + bytes, sorted) over the registered policy files."""
    return checkpoint_sha256(root, [ref['path'] for ref in policy['files']])


def _name(value, key):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f'{key} required')


def _ranges(ranges):
    if not isinstance(ranges, dict) or not ranges:
        raise ValueError('domain randomisation ranges required')
    for name, pair in ranges.items():
        _name(name, 'randomisation name')
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in pair) or pair[0] > pair[1]):
            raise ValueError(f'invalid randomisation range {name}')


def _check_profile(name, prof):
    if not isinstance(prof, dict):
        raise ValueError(f'invalid sim L1 profile {name}')
    n_action = _count(prof, 'n_action_steps')
    if n_action < 1:
        raise ValueError(f'{name}: positive n_action_steps required')
    delay = _count(prof, 'delay_frames')
    if (name == 'nominal' and delay != 0) or (name == 'delayed' and delay < 1):
        raise ValueError(f'{name}: invalid delay_frames {delay}')
    counts = {key: _count(prof, key) for key in (
        'policy_episodes', 'policy_successes', 'teacher_episodes', 'teacher_successes',
        'neighbour_disturbed', 'arm_link_contacts')}
    for arm in ('policy', 'teacher'):
        if counts[f'{arm}_episodes'] < 1:
            raise ValueError(f'{name}: at least one {arm} episode required')
        if counts[f'{arm}_successes'] > counts[f'{arm}_episodes']:
            raise ValueError(f'{name}: {arm} successes exceed episodes')
    return {
        'n_action_steps': n_action,
        'delay_frames': delay,
        **counts,
        'policy_rate': counts['policy_successes'] / counts['policy_episodes'],
        'teacher_rate': counts['teacher_successes'] / counts['teacher_episodes'],
    }


def _check_layer(name, row):
    _name(name, 'layer name')
    if not isinstance(row, dict):
        raise ValueError(f'invalid per_layer entry {name}')
    counts = {key: _count(row, key) for key in ('episodes', 'lifted', 'sustained_lift', 'successes')}
    ep = counts['episodes']
    if ep < 1 or counts['lifted'] > ep or counts['sustained_lift'] > counts['lifted'] or counts['successes'] > counts['lifted']:
        raise ValueError(f'{name}: invalid layer counts')
    return {
        **counts,
        'lift_rate': counts['lifted'] / ep,
        'sustained_lift_rate': counts['sustained_lift'] / ep,
        'success_rate': counts['successes'] / ep,
    }


def _assess_v2(report):
    raw_profiles = report.get('profiles')
    if not isinstance(raw_profiles, dict) or set(raw_profiles) != {'nominal', 'delayed'}:
        raise ValueError('v2 sim L1 report requires nominal and delayed profiles')
    raw_layers = report.get('per_layer')
    if not isinstance(raw_layers, dict) or not raw_layers:
        raise ValueError('v2 sim L1 report requires per_layer summary')
    for layer_key in raw_layers:
        _name(layer_key, 'layer name')
    profiles = {name: _check_profile(name, raw_profiles[name]) for name in ('nominal', 'delayed')}
    per_layer = {name: _check_layer(name, raw_layers[name]) for name in sorted(raw_layers)}

    reasons = []
    if any(min(p['policy_episodes'], p['teacher_episodes']) < MIN_EPISODES for p in profiles.values()):
        reasons.append('too_few_episodes')
    if profiles['nominal']['policy_rate'] < profiles['nominal']['teacher_rate']:
        reasons.append('nominal_below_teacher')
    if profiles['delayed']['policy_rate'] < profiles['delayed']['teacher_rate']:
        reasons.append('delayed_below_teacher')
    if any(p['neighbour_disturbed'] > 0 or p['arm_link_contacts'] > 0 for p in profiles.values()):
        reasons.append('collision_detected')
    if any(layer['successes'] == 0 for layer in per_layer.values()):
        reasons.append('layer_zero_success')

    expected = 'reject' if reasons else 'pass'
    if report.get('verdict') != expected:
        raise ValueError('claimed verdict differs from recomputed sim L1 rates')
    return {
        'kind': 'sim_l1', 'schema': 'rosy.sim-l1-eval/2', 'verdict': expected, 'reasons': reasons,
        'task': report['task'], 'physics_candidate': report['physics_candidate'],
        'randomisation': report['randomisation'], 'checkpoint_sha256': report['checkpoint_sha256'],
        'profiles': profiles, 'per_layer': per_layer,
        'real_evidence': False, 'validator': 'rosy-sim-l1-gate/2',
    }


def sim_l1_assessment(report):
    """Recompute the verdict: same task, physics candidate and randomisation, policy rate >= teacher rate."""
    schema = report.get('schema')
    if schema not in ('rosy.sim-l1-eval/1', 'rosy.sim-l1-eval/2'):
        raise ValueError('unsupported sim L1 report schema')
    if report.get('task') not in TASKS:
        raise ValueError('task must be one of ' + ', '.join(TASKS))
    _name(report.get('physics_candidate'), 'physics candidate')
    _sha256(report.get('checkpoint_sha256'))
    _ranges(report.get('randomisation'))
    if schema == 'rosy.sim-l1-eval/2':
        return _assess_v2(report)
    counts = {key: _count(report, key) for key in
              ('policy_episodes', 'policy_successes', 'teacher_episodes', 'teacher_successes')}
    for arm in ('policy', 'teacher'):
        if counts[f'{arm}_successes'] > counts[f'{arm}_episodes']:
            raise ValueError(f'{arm} successes exceed episodes')
    if counts['policy_episodes'] < 1:
        raise ValueError('at least one policy episode required')
    reasons = []
    if min(counts['policy_episodes'], counts['teacher_episodes']) < MIN_EPISODES:
        reasons.append('too_few_episodes')
    policy_rate = counts['policy_successes'] / max(1, counts['policy_episodes'])
    teacher_rate = counts['teacher_successes'] / max(1, counts['teacher_episodes'])
    if policy_rate < teacher_rate:
        reasons.append('below_teacher_success_rate')
    expected = 'reject' if reasons else 'pass'
    if report.get('verdict') != expected:
        raise ValueError('claimed verdict differs from recomputed sim L1 rates')
    return {'kind': 'sim_l1', 'verdict': expected, 'reasons': reasons, 'task': report['task'],
            'physics_candidate': report['physics_candidate'], 'randomisation': report['randomisation'],
            'checkpoint_sha256': report['checkpoint_sha256'], **counts,
            'policy_rate': policy_rate, 'teacher_rate': teacher_rate,
            'real_evidence': False, 'validator': 'rosy-sim-l1-gate/1'}
