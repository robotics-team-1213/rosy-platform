"""Explicit local-file load assessment and bounded passive monitoring; no hardware commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from core_common.motor_health import read_motor_health_snapshot

from .hardware_profile import _number
from .load_assessment import assess_candidates
from .load_monitor import LoadMonitor
from .motion_characteristics import (
    _count, characteristics_digest, document_digest, load_characteristics, load_json,
    save_characteristics, write_json,
)


def _emit(report, output):
    if output is not None:
        write_json(output, report)
    print(json.dumps(report, sort_keys=True, allow_nan=False))


def _protect_inputs(output, *inputs):
    if output is not None and Path(output).resolve() in {Path(p).resolve() for p in inputs}:
        raise ValueError('analysis output cannot replace an input file')


def _watch(args, profile, request):
    _count(args.samples, 'samples', 10000)
    interval = _number(args.interval_s, 'interval_s', positive=True)
    if interval > profile['monitor']['max_gap_s']:
        raise ValueError('poll interval exceeds measured feedback gap limit')
    monitor = LoadMonitor(profile, request, accepted_digest=args.accepted_sha256,
                          candidate_id=args.candidate_id, command_id=args.command_id,
                          started_at=args.started_at, session_id=args.session_id)
    initial_request_digest = document_digest(request)
    last_signature = None
    for index in range(args.samples):
        now = time.time()
        try:
            if (characteristics_digest(load_characteristics(args.profile)) != args.accepted_sha256
                    or document_digest(load_json(args.request)) != initial_request_digest):
                report = monitor.unavailable('configuration_changed', now=now)
            else:
                health, captured = read_motor_health_snapshot(
                    Path(args.health).absolute(), profile['binding']['owner_id'], now=now)
                signature = document_digest(health.model_dump(
                    exclude={'sample_age_s': True, 'motors': {'__all__': {'sample_age_s'}}}))
                # Polling the same capture cannot renew freshness or count as a new oscillation sample.
                duplicate = (signature == last_signature and captured == monitor.last_capture
                             and monitor.last_now is not None
                             and now >= monitor.last_now and health.status == 'active'
                             and health.sample_age_s is not None
                             and health.sample_age_s <= profile['monitor']['max_age_s'])
                if duplicate:
                    if now - monitor.last_now > profile['monitor']['max_gap_s'] + 1e-9:
                        report = monitor.unavailable('feedback_gap', now=now)
                    elif any(m.sample_age_s > profile['monitor']['max_age_s'] for m in health.motors):
                        report = monitor.unavailable('stale_feedback', now=now)
                    else:
                        report = None
                else:
                    report = monitor.observe(health, captured_at=captured, now=now, context=request['context'])
                last_signature = signature
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            report = monitor.unavailable('source_unavailable', now=now)
        if report is not None:
            _emit(report, args.output)
            if report['status'] == 'hold_for_owner_review':
                return 3
        if index + 1 < args.samples:
            time.sleep(interval)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    save = commands.add_parser('save', help='validate and atomically save a characteristics JSON document')
    save.add_argument('source', type=Path)
    save.add_argument('destination', type=Path)
    for name in ('assess', 'watch'):
        command = commands.add_parser(name)
        command.add_argument('profile', type=Path)
        command.add_argument('request', type=Path)
        command.add_argument('--accepted-sha256', required=True)
        command.add_argument('--output', type=Path)
        if name == 'watch':
            command.add_argument('--health', type=Path, required=True)
            command.add_argument('--candidate-id', required=True)
            command.add_argument('--command-id', required=True)
            command.add_argument('--session-id', required=True)
            command.add_argument('--started-at', type=float, required=True)
            command.add_argument('--samples', type=int, required=True)
            command.add_argument('--interval-s', type=float, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'save':
            digest = save_characteristics(args.destination, load_json(args.source))
            _emit({'schema': 'rosy.omx-characteristics-saved.v1', 'characteristics_sha256': digest,
                   'motion_admitted': False, 'automatic_recovery_enabled': False}, None)
            return 0
        protected = [args.profile, args.request]
        if args.command == 'watch':
            protected.append(args.health)
        _protect_inputs(args.output, *protected)
        profile, request = load_characteristics(args.profile), load_json(args.request)
        if args.command == 'watch':
            return _watch(args, profile, request)
        result = assess_candidates(profile, request, accepted_digest=args.accepted_sha256)
        _emit(result, args.output)
        return 0 if result['selected_candidate_id'] is not None else 3
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        _emit({'schema': 'rosy.omx-load-input-error.v1', 'error': str(exc),
               'motion_admitted': False, 'automatic_recovery_enabled': False}, None)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
