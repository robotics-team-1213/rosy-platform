"""D-1024 1: simulated L1 evaluation record. Sim evidence replaces only the held-out part of L1, never L2/L3 (D-911 4)."""
import hashlib
import math

TASKS = ('stack-t1', 'stack-t2', 'stack-t3')
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
    digest = hashlib.sha256()
    for ref in sorted(policy['files'], key=lambda r: r['path']):
        digest.update(ref['path'].encode() + b'\0' + (root / ref['path']).read_bytes())
    return digest.hexdigest()


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


def sim_l1_assessment(report):
    """Recompute the verdict: same task, same physics candidate and randomisation, policy rate >= teacher rate."""
    if report.get('schema') != 'rosy.sim-l1-eval/1':
        raise ValueError('unsupported sim L1 report schema')
    if report.get('task') not in TASKS:
        raise ValueError('task must be one of ' + ', '.join(TASKS))
    _name(report.get('physics_candidate'), 'physics candidate')
    _sha256(report.get('checkpoint_sha256'))
    _ranges(report.get('randomisation'))
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
