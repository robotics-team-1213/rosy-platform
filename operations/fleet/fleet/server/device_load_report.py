"""Validate the existing advisory monitor output without treating it as owner feedback."""
import json
import re
from uuid import UUID

from rosy.contracts.motion.characteristics import _number, _text, characteristics_digest


FIELDS = set('schema status recommendation reasons errors_rad command_id candidate_id command_binding '
             'trajectory_sha256 characteristics_sha256 characteristics_revision request_sha256 context '
             'source_sequence task_id scene_revision session_id captured_at assessed_at joint_captured_at '
             'new_joint_samples motion_admitted automatic_recovery_enabled'.split())


def validate_report(report, document, *, now):
    try:
        report = json.loads(json.dumps(report, allow_nan=False))
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError('expected finite JSON report') from None
    if not isinstance(report, dict) or set(report) != FIELDS or document is None:
        raise ValueError('expected existing monitor output and saved characteristics')
    if (report['schema'] != 'rosy.omx-load-monitor.v1' or report['motion_admitted'] is not False
            or report['automatic_recovery_enabled'] is not False
            or report['command_binding'] != 'caller_supplied_unverified'):
        raise ValueError('report must remain advisory with unverified command binding')
    if (document['status'] != 'measured' or report['context'] != document['binding']
            or report['characteristics_revision'] != document['revision']
            or report['characteristics_sha256'] != characteristics_digest(document)):
        raise ValueError('report characteristics or configuration mismatch')
    status = report['status']
    expected = {'observing': 'continue_observation_only',
                'hold_for_owner_review': 'replan_from_fresh_state_after_owner_recovery'}
    if status not in expected or report['recommendation'] != expected[status]:
        raise ValueError('unsupported status or recommendation')
    for key in ('command_id', 'candidate_id', 'task_id', 'scene_revision', 'session_id'):
        _text(report[key], key)
    if str(UUID(report['session_id'])) != report['session_id']:
        raise ValueError('invalid session')
    for key in ('trajectory_sha256', 'request_sha256'):
        if not isinstance(report[key], str) or re.fullmatch('[0-9a-f]{64}', report[key]) is None:
            raise ValueError('invalid digest')
    if type(report['source_sequence']) is not int or report['source_sequence'] < 0:
        raise ValueError('invalid source sequence')
    stamp = _number(report['assessed_at'], 'assessed_at', positive=True)
    if stamp > now + 0.25:
        raise ValueError('future report')
    captured = report['captured_at']
    if captured is not None and not 0 < _number(captured, 'captured_at') <= stamp:
        raise ValueError('invalid capture time')
    reasons = report['reasons']
    if not isinstance(reasons, list) or len(reasons) > 128:
        raise ValueError('invalid reasons')
    for reason in reasons:
        _text(reason, 'reason')
    if bool(reasons) != (status == 'hold_for_owner_review') or len(set(reasons)) != len(reasons):
        raise ValueError('inconsistent reasons')
    names = set(document['joints'])
    for field in ('errors_rad', 'joint_captured_at'):
        values = report[field]
        if not isinstance(values, dict) or values.keys() - names:
            raise ValueError('unknown joints')
        for value in values.values():
            _number(value, field)
            if field == 'joint_captured_at' and not 0 < value <= stamp:
                raise ValueError('invalid joint capture')
    samples = report['new_joint_samples']
    if not isinstance(samples, list) or samples != sorted(report['errors_rad']):
        raise ValueError('sample coverage mismatch')
    if status == 'observing' and (captured is None or set(report['joint_captured_at']) != names):
        raise ValueError('observing requires every joint capture')
    return report


def analysis_view(report, document, *, now):
    if report is None or document is None:
        return None
    age = now - report['assessed_at']
    captures = list(report['joint_captured_at'].values())
    limit = document['monitor']['max_age_s']
    fresh = (0 <= age <= limit and report['captured_at'] is not None
             and 0 <= now - report['captured_at'] <= limit
             and set(report['joint_captured_at']) == set(document['joints'])
             and all(0 <= now - stamp <= limit for stamp in captures))
    evidence_age = max([age, now - report['captured_at'] if report['captured_at'] is not None else limit + 1,
                        *[now - stamp for stamp in captures]])
    return {**report, 'fresh': fresh, 'age_s': max(0, age), 'evidence_age_s': max(0, evidence_age), 'max_age_s': limit}
