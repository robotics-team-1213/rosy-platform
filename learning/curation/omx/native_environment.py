"""Offline environment lineage. Sparse image proxies never establish continuous readiness."""
import copy
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'contracts/learning/src'))
from rosy.contracts.learning.omx import WRIST, camera_role, camera_roles  # noqa: E402  D-794 B


SCHEMA = 'rosy.omx-native-environment.v1'
POLICY = 'omx-photometric-v3'
ROLES = ('top', WRIST)
CONDITIONS = {'NORMAL', 'UNDEREXPOSED', 'OVEREXPOSED', 'MIXED_LIGHTING',
              'LOW_CONTRAST', 'LOW_SPATIAL_SIGNAL'}
STATES = {'OBSERVING', 'NORMAL', 'UNSUPPORTED', 'COOLDOWN', 'BUDGET_LIMITED',
          'EXHAUSTED', 'ADJUSTING', 'SETTLING', 'STALE', 'WAITING_FRAME'}
MAX_LOG_BYTES = 8 * 1024 * 1024


def _require(value, message):
    if not value:
        raise ValueError('environment: ' + message)


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('environment: nonfinite JSON constant ' + value)


def _float(value):
    result = float(value)
    _require(math.isfinite(result), 'nonfinite JSON number')
    return result


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _image_condition(item, stamp_ns, previous):
    quality = item.get('quality') or {}
    stamp, seq = item.get('source_stamp'), item.get('sequence')
    if not (_number(stamp) and stamp > 0 and type(seq) is int and seq > 0
            and stamp > previous[0] and seq > previous[1] and item.get('fresh') is True
            and -.25 <= stamp_ns/1e9-stamp <= 2
            and _number(item.get('receipt_age_s')) and 0 <= item['receipt_age_s'] <= 2
            and _number(item.get('source_age_s')) and -.25 <= item['source_age_s'] <= 2
            and quality.get('policy') == POLICY
            and type(quality.get('usable')) is bool
            and quality['usable'] == (quality.get('condition') == 'NORMAL')
            and all(_number(quality.get(key)) and 0 <= quality[key] <= 255
                    for key in ('mean_intensity', 'spatial_contrast', 'p5', 'p95'))
            and all(_number(quality.get(key)) and 0 <= quality[key] <= 1
                    for key in ('dark_fraction', 'clipped_fraction'))):
        return 'UNKNOWN', previous
    return quality['condition'], (stamp, seq)


def _events(raw):
    _require(isinstance(raw, str), 'UTF-8 log required')
    encoded = raw.encode('utf-8')
    _require(0 < len(encoded) <= MAX_LOG_BYTES and raw.endswith('\n'), 'empty, oversized or partial log')
    result, previous, frames = [], 0, {}
    for line in raw.splitlines():
        try:
            event = json.loads(line, object_pairs_hook=_object, parse_constant=_constant, parse_float=_float)
        except (ValueError, TypeError) as exc:
            raise ValueError('environment: invalid log JSON') from exc
        _require(isinstance(event, dict), 'event object required')
        stamp = event.get('recorded_ns')
        _require(type(stamp) is int and stamp > 0 and stamp >= previous, 'invalid or reversed host clock')
        previous = stamp
        _require(event.get('policy') == POLICY and _text(event.get('run_id'))
                 and _hash(event.get('profile_sha256')), 'event policy/run/profile differs')
        _require(event.get('motion_admitted') is False and event.get('physical_acceptance') is False,
                 'image evidence cannot grant physical admission')
        _require(type(event.get('photometric_ready')) is bool, 'missing photometric assessment')
        plans, observations = event.get('environment'), event.get('observations')
        _require(isinstance(plans, dict) and len(plans) == len(ROLES) and isinstance(observations, dict)
                 and _roles(plans) == set(ROLES), 'both camera roles required')
        # D-794 B: a recorder that already says "wrist" is read as the same wrist camera.
        plans = event['environment'] = {camera_role(k): v for k, v in plans.items()}
        observations = {camera_role(k): v for k, v in observations.items()}
        event['_image_conditions'] = {}
        for role in ROLES:
            plan = plans[role]
            _require(isinstance(plan, dict) and isinstance(plan.get('state'), str)
                     and plan['state'] in STATES
                     and (plan.get('condition') is None or isinstance(plan.get('condition'), str)
                          and plan['condition'] in CONDITIONS | {'TEMPORAL_CHANGE'}), 'invalid recovery state')
            _require(all(type(plan.get(key)) is int and plan[key] >= 0
                         for key in ('environment_epoch', 'control_generation')), 'invalid epoch/generation')
            item = observations.get(role, {})
            _require(isinstance(item, dict), 'invalid observation')
            quality = item.get('quality')
            if quality is not None:
                _require(isinstance(quality, dict) and quality.get('policy') == POLICY
                         and isinstance(quality.get('condition'), str)
                         and quality['condition'] in CONDITIONS, 'invalid image policy/condition')
            key = (event['run_id'], role)
            condition, frame = _image_condition(item, stamp, frames.get(key, (0., 0)))
            frames[key] = frame
            event['_image_conditions'][role] = condition
        result.append(event)
    return result


def _roles(names):
    try:
        return camera_roles(names)
    except ValueError:
        return None


def seal_environment(raw, windows, files, *, rig_revision, calibration_revision):
    """Bind a completed original log and recorder-declared host-clock episode windows."""
    try:
        text = raw.decode('utf-8')
    except (AttributeError, UnicodeError) as exc:
        raise ValueError('environment: original UTF-8 bytes required') from exc
    evidence = dict(schema=SCHEMA, clock='fleet_host_unix_ns', log_utf8=text,
                    log_sha256=hashlib.sha256(raw).hexdigest(), dataset_files=copy.deepcopy(files),
                    rig_revision=rig_revision, calibration_revision=calibration_revision,
                    episodes=copy.deepcopy(windows))
    _require(isinstance(windows, list), 'episode windows required')
    bind_environment([dict(episode_index=i) for i in range(len(windows))], files,
                     rig_revision=rig_revision, calibration_revision=calibration_revision, evidence=evidence)
    return evidence


def bind_environment(episodes, files, *, rig_revision, calibration_revision, evidence=None):
    """Recompute summaries from original bytes on inspection, splitting and training."""
    summary = dict(status='unrecorded' if evidence is None else 'recorded',
                   coverage='sparse_transition_events', photometric_continuity_verified=False,
                   physical_acceptance=False, task_success=None, episodes=[])
    if evidence is None:
        summary['episodes'] = [dict(episode_index=e['episode_index'], status='unobserved', event_count=0,
                                    roles={r: dict(image_conditions={}, recovery_states={}) for r in ROLES})
                               for e in episodes]
        return summary
    _require(isinstance(evidence, dict), 'evidence object required')
    _require(evidence.get('schema') == SCHEMA and evidence.get('clock') == 'fleet_host_unix_ns',
             'schema/clock differs')
    _require(_text(rig_revision) and _text(calibration_revision)
             and evidence.get('rig_revision') == rig_revision
             and evidence.get('calibration_revision') == calibration_revision, 'rig/calibration differs')
    _require(evidence.get('dataset_files') == files and isinstance(files, dict) and bool(files)
             and all(_hash(value) for value in files.values()), 'dataset bytes differ')
    raw = evidence.get('log_utf8')
    events = _events(raw)
    _require(evidence.get('log_sha256') == hashlib.sha256(raw.encode('utf-8')).hexdigest(), 'log hash differs')
    windows = evidence.get('episodes')
    _require(isinstance(windows, list) and len(windows) == len(episodes), 'windows must cover every episode')
    prior_end = 0
    identities = {(e['run_id'], e['profile_sha256']) for e in events}
    for source, window in zip(episodes, windows):
        _require(isinstance(window, dict) and type(window.get('episode_index')) is int
                 and window['episode_index'] == source['episode_index'], 'episode identity/order differs')
        start, end = window.get('start_ns'), window.get('end_ns')
        _require(type(start) is int and type(end) is int and 0 < start < end and start >= prior_end,
                 'invalid, reordered or overlapping episode window')
        prior_end = end
        identity = (window.get('run_id'), window.get('profile_sha256'))
        _require(all(isinstance(v, str) for v in identity) and identity in identities, 'unknown run/profile')
        selected = [event for event in events if start <= event['recorded_ns'] < end]
        _require(all((e['run_id'], e['profile_sha256']) == identity for e in selected),
                 'window crosses run/profile boundary')
        roles = {}
        for role in ROLES:
            conditions, states = Counter(), Counter()
            for event in selected:
                conditions[event['_image_conditions'][role]] += 1
                states[event['environment'][role]['state']] += 1
            roles[role] = dict(image_conditions=dict(conditions), recovery_states=dict(states))
        summary['episodes'].append(dict(episode_index=source['episode_index'],
                                        status='observed' if selected else 'unobserved',
                                        event_count=len(selected), roles=roles))
    return summary


def validate_environment(report):
    summary = bind_environment(report['episodes'], report['files'], rig_revision=report['rig_revision'],
                               calibration_revision=report['calibration_revision'],
                               evidence=report.get('environment_evidence'))
    if 'environment_summary' in report or report.get('environment_evidence') is not None:
        _require(report.get('environment_summary') == summary, 'summary differs from original log')
    return summary


def split_coverage(summary, decisions):
    """Event counts and review outcomes, including excluded and unobserved attempts; not frame coverage."""
    _require(len(summary['episodes']) == len(decisions), 'review coverage differs')
    result = {}
    for episode, decision in zip(summary['episodes'], decisions):
        name = decision['split']
        group = result.setdefault(name, dict(episodes=0, unobserved_episodes=0, outcomes={},
                                             roles={r: {} for r in ROLES}))
        group['episodes'] += 1
        group['unobserved_episodes'] += int(episode['status'] == 'unobserved')
        outcome = decision['outcome']
        group['outcomes'][outcome] = group['outcomes'].get(outcome, 0)+1
        for role in ROLES:
            for condition, count in episode['roles'][role]['image_conditions'].items():
                group['roles'][role][condition] = group['roles'][role].get(condition, 0)+count
    return result
