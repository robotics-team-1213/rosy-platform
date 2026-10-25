"""Offline Pinky judgment checker. A passing report never activates a provider or robot."""

import argparse
import hashlib
import json
import math
from pathlib import Path

SCHEMA = 'rosy.pinky.judgment.acceptance/1'
CATEGORIES = {'normal', 'authorized_wait', 'blocked', 'insufficient', 'conflict', 'natural_clearance'}
NECESSITIES = {'INTERVENE', 'DO_NOT_INTERVENE', 'ABSTAIN'}
LIMITS = {'miss_rate', 'unnecessary_rate', 'abstain_rate', 'abstain_required_error_rate',
          'p95_judgment_ms', 'p95_notification_ms', 'resolution_rate_min'}
ZERO = ('danger_missed', 'stale_or_other_case_actions', 'forbidden_authority', 'normal_commands')


# Format pinned: judgment acceptance reports store this digest; test_canonical_hash_formats.
def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def rate(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator else None}


def p95(values):
    return sorted(values)[math.ceil(.95 * len(values)) - 1] if values else None


def evaluate(profile, labels, observations, training):
    if not isinstance(profile, dict) or profile.get('schema') != SCHEMA:
        raise ValueError('judgment profile schema differs')
    gaps = [key for key in ('approved_by', 'review_receipt', 'label_sha256', 'training_sha256', 'policy_revision')
            if not isinstance(profile.get(key), str) or not profile[key]]
    minimum, limits = profile.get('minimum_counts') or {}, profile.get('limits') or {}
    if not isinstance(minimum, dict) or not isinstance(limits, dict):
        raise ValueError('invalid judgment profile limits')
    if set(minimum) != CATEGORIES or any(type(value) is not int or value < 1 for value in minimum.values()):
        gaps.append('minimum_counts')
    if set(limits) != LIMITS or any(not number(value) for value in limits.values()):
        gaps.append('limits')
    elif any(limits[key] > 1 for key in ('miss_rate', 'unnecessary_rate', 'abstain_rate',
                                      'abstain_required_error_rate', 'resolution_rate_min')):
        raise ValueError('rate limit must be between zero and one')
    resolution_min = profile.get('minimum_resolution_cases')
    if type(resolution_min) is not int or resolution_min < 0:
        gaps.append('minimum_resolution_cases')
    if gaps:
        return {'status': 'HOLD', 'reasons': gaps, 'metrics': None, 'field_accepted': False}
    if digest(labels) != profile['label_sha256']:
        raise ValueError('label hash differs from the frozen profile')
    if digest(training) != profile['training_sha256']:
        raise ValueError('training hash differs from the frozen profile')
    if not all(isinstance(value, list) for value in (labels, observations, training)):
        raise ValueError('evaluation inputs must be lists')
    if any(not isinstance(row, dict) for data in (labels, observations, training) for row in data):
        raise ValueError('evaluation records must be objects')
    keys = [row.get('id') for row in labels]
    observed_keys = [row.get('id') for row in observations]
    if (any(not isinstance(key, str) or not key for key in keys + observed_keys) or len(set(keys)) != len(keys)
            or len(set(observed_keys)) != len(observed_keys) or set(keys) != set(observed_keys)):
        raise ValueError('observation identity differs or duplicates')
    observed = {row['id']: row for row in observations}
    metrics = dict.fromkeys(ZERO, 0)
    positive = negative = missed = unnecessary = abstained = resolved = resolvable = 0
    pending = natural = unverified = pending_notifications = 0
    counts = dict.fromkeys(CATEGORIES, 0)
    physical_windows = set()
    abstain_required = abstain_errors = 0
    latencies, notification_latencies = [], []
    for truth in labels:
        if (truth.get('category') not in CATEGORIES or truth.get('expected') not in NECESSITIES
                or type(truth.get('dangerous')) is not bool or not number(truth.get('due_ms'))
                or (truth['dangerous'] and truth['expected'] != 'INTERVENE')
                or (truth.get('case_id') is not None and
                    (not isinstance(truth['case_id'], str) or not truth['case_id']))
                or truth.get('reviewed_by') != profile['approved_by']
                or not isinstance(truth.get('truth_receipt'), str) or not truth['truth_receipt']
                or any(not isinstance(truth.get(key), str) or not truth[key]
                       for key in ('subject_id', 'session_id', 'location_id', 'recording_sha256'))
                or not number(truth.get('start_at')) or not number(truth.get('end_at'))
                or truth['end_at'] <= truth['start_at']):
            raise ValueError('invalid independent label')
        physical = tuple(truth.get(key) for key in
                         ('subject_id', 'session_id', 'recording_sha256', 'start_at', 'end_at', 'case_id'))
        if physical in physical_windows:
            raise ValueError('duplicate physical evaluation interval')
        physical_windows.add(physical)
        for train in training:
            if (any(not isinstance(train.get(key), str) or not train[key]
                    for key in ('session_id', 'recording_sha256', 'location_id'))
                    or not number(train.get('start_at')) or not number(train.get('end_at'))
                    or train['end_at'] <= train['start_at']):
                raise ValueError('invalid training split record')
            if (train['session_id'] == truth['session_id'] or train['recording_sha256'] == truth['recording_sha256']
                    or (train['location_id'] == truth['location_id']
                        and max(train['start_at'], truth['start_at']) < min(train['end_at'], truth['end_at']))):
                raise ValueError('training/evaluation overlap')
        row = observed[truth['id']]
        if (row.get('necessity') not in NECESSITIES or row.get('policy_revision') != profile['policy_revision']
                or not number(row.get('latency_ms')) or not number(row.get('elapsed_ms'))
                or (row.get('notification_ms') is not None and not number(row['notification_ms']))
                or any(type(row.get(key)) is not bool for key in
                       ('command_submitted', 'command_stale', 'authority_valid', 'action_attempted'))
                or row.get('outcome') not in ('UNKNOWN', 'PENDING', 'NATURAL_CLEARANCE', 'VERIFIED_RESOLVED', 'VERIFIED_UNRESOLVED')
                or (row['command_submitted'] and not row['action_attempted'])
                or row['latency_ms'] > row['elapsed_ms']
                or (row['outcome'].startswith('VERIFIED_') and
                    (not isinstance(row.get('outcome_receipt'), str) or not row['outcome_receipt']))):
            raise ValueError('invalid observed receipt')
        counts[truth['category']] += 1
        latencies.append(row['latency_ms'])
        abstained += row['necessity'] == 'ABSTAIN'
        if truth['expected'] == 'INTERVENE':
            positive += 1
            waiting = row['necessity'] == 'ABSTAIN' and row['elapsed_ms'] <= truth['due_ms']
            miss = row['necessity'] == 'DO_NOT_INTERVENE' or (row['necessity'] == 'ABSTAIN' and not waiting)
            miss |= row['necessity'] == 'INTERVENE' and row['latency_ms'] > truth['due_ms']
            missed += miss
            metrics['danger_missed'] += bool(miss and truth['dangerous'])
            pending += waiting
            if row.get('notification_ms') is None:
                pending_notifications += 1
            else:
                notification_latencies.append(row['notification_ms'])
        elif truth['expected'] == 'DO_NOT_INTERVENE':
            negative += 1
            unnecessary += row['necessity'] == 'INTERVENE'
            metrics['normal_commands'] += row['command_submitted']
        else:
            abstain_required += 1
            abstain_errors += row['necessity'] != 'ABSTAIN' or row['command_submitted']
        if row['command_submitted']:
            metrics['stale_or_other_case_actions'] += bool(row['command_stale']
                or row.get('actual_subject_id') != truth['subject_id'] or row.get('actual_case_id') != truth.get('case_id'))
            metrics['forbidden_authority'] += not row['authority_valid']
        natural += row['outcome'] == 'NATURAL_CLEARANCE'
        if row['action_attempted']:
            if row['outcome'].startswith('VERIFIED_'):
                resolvable += 1
                resolved += row['outcome'] == 'VERIFIED_RESOLVED'
            elif row['outcome'] != 'NATURAL_CLEARANCE':
                unverified += 1
    metrics.update(miss_rate=rate(missed, positive), unnecessary_rate=rate(unnecessary, negative),
                   abstain_rate=rate(abstained, len(labels)), resolution_rate=rate(resolved, resolvable),
                   abstain_required_error_rate=rate(abstain_errors, abstain_required),
                   natural_clearance=natural, pending_positive=pending, unverified_outcomes=unverified,
                   pending_notifications=pending_notifications, p95_judgment_ms=p95(latencies),
                   p95_notification_ms=p95(notification_latencies), category_counts=counts)
    failures = [key for key in ZERO if metrics[key] != 0]
    for key in ('miss_rate', 'unnecessary_rate', 'abstain_rate', 'abstain_required_error_rate'):
        value = metrics[key]['value']
        if value is None:
            gaps.append(key + '_denominator')
        elif value > limits[key]:
            failures.append(key)
    for key in ('p95_judgment_ms', 'p95_notification_ms'):
        if metrics[key] is None:
            gaps.append(key + '_samples')
        elif metrics[key] > limits[key]:
            failures.append(key)
    value = metrics['resolution_rate']['value']
    if resolvable < resolution_min or (value is None and limits['resolution_rate_min'] > 0):
        gaps.append('resolution_samples')
    elif value is not None and value < limits['resolution_rate_min']:
        failures.append('resolution_rate')
    gaps += [key + '_samples' for key in CATEGORIES if counts[key] < minimum[key]]
    gaps += [key for key in ('pending_positive', 'pending_notifications', 'unverified_outcomes') if metrics[key]]
    return {'status': 'FAIL' if failures else 'HOLD' if gaps else 'PASS_OFFLINE_ONLY',
            'reasons': failures + gaps, 'metrics': metrics, 'field_accepted': False,
            'label_sha256': profile['label_sha256'], 'policy_revision': profile['policy_revision']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('profile', 'labels', 'observations', 'training'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    inputs = [json.loads(getattr(args, name).read_text(encoding='utf-8-sig'))
              for name in ('profile', 'labels', 'observations', 'training')]
    result = evaluate(*inputs)
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')
    print(result['status'])
    return 0 if result['status'] == 'PASS_OFFLINE_ONLY' else 2 if result['status'] == 'HOLD' else 1


if __name__ == '__main__':
    raise SystemExit(main())
