"""Authenticated original review/capture records; never an operating approval."""
import hashlib
import hmac
import json

from .operational_comparison import fields, sha, text, timestamp

STREAMS = ('observation', 'model', 'command', 'submission', 'result', 'recurrence', 'invoice')
KINDS = {'operational_truth', 'operational_limits', 'operational_capture', 'operational_review', 'operational_runtime'}


def encoded(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > 1024 * 1024: raise ValueError('OPERATING_ORIGINAL_LIMIT')
    return raw


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def verify_attestation(receipt, original, *, trusted, kind, now):
    fields(receipt, ('principal', 'payload', 'signature'))
    principal, payload = text(receipt['principal']), receipt['payload']
    fields(payload, ('schema', 'kind', 'source_sha256', 'valid_from_s', 'expires_s'))
    timestamp(now)
    if (kind not in KINDS or payload['schema'] != 'rosy.incident.evidence_attestation/1'
            or payload['kind'] != kind or sha(payload['source_sha256']) != digest(original)
            or not timestamp(payload['valid_from_s']) <= now < timestamp(payload['expires_s'])):
        raise ValueError('OPERATING_SOURCE_BINDING_OR_TIME_DIFFERS')
    trust = trusted.get(principal) if type(trusted) is dict else None
    if (type(trust) is not dict or set(trust) != {'key', 'kinds'} or type(trust['key']) is not bytes
            or len(trust['key']) < 32 or type(trust['kinds']) not in (set, frozenset) or kind not in trust['kinds']):
        raise ValueError('OPERATING_SOURCE_PRINCIPAL_NOT_TRUSTED')
    expected = hmac.new(trust['key'], encoded(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sha(receipt['signature']), expected):
        raise ValueError('OPERATING_SOURCE_SIGNATURE_DIFFERS')
    return json.loads(encoded(receipt))


def validate_window(window, *, trusted, now):
    fields(window, ('schema', 'subject_id', 'start', 'end', 'streams', 'attestation'))
    if window['schema'] != 'rosy.incident.operational_window/1': raise ValueError('INVALID_OPERATING_WINDOW_SCHEMA')
    subject = text(window['subject_id'])
    start, end = timestamp(window['start']), timestamp(window['end'])
    if not 0 < end - start <= 86400: raise ValueError('INVALID_OPERATING_WINDOW_BOUNDS')
    original = {k: v for k, v in window.items() if k != 'attestation'}
    verify_attestation(window['attestation'], original, trusted=trusted, kind='operational_capture', now=now)
    fields(window['streams'], STREAMS)
    checked = dict(subject_id=subject, start=start, end=end, source_sha256=digest(original), streams={})
    for name, stream in window['streams'].items():
        fields(stream, ('run_id', 'frames')); text(stream['run_id'])
        frames = stream['frames']
        if type(frames) is not list or not 2 <= len(frames) <= 4096: raise ValueError('OPERATING_WINDOW_FRAME_LIMIT')
        events, ids, previous = [], set(), None
        for frame in frames:
            fields(frame, ('sequence', 'received_at', 'monotonic_at', 'events'))
            seq, received, mono = frame['sequence'], timestamp(frame['received_at']), timestamp(frame['monotonic_at'])
            if (type(seq) is not int or seq < 1 or previous is not None and
                    (seq != previous['sequence'] + 1 or received <= previous['received_at'] or mono <= previous['monotonic_at'])):
                raise ValueError('OPERATING_WINDOW_SEQUENCE_OR_CLOCK_DIFFERS')
            if type(frame['events']) is not list or len(frame['events']) > 4096:
                raise ValueError('OPERATING_WINDOW_EVENT_LIMIT')
            for event in frame['events']:
                fields(event, ('event_id', 'at', 'case_id', 'generation', 'source_sha256', 'payload'))
                identity = text(event['event_id']); stamp = timestamp(event['at']); sha(event['source_sha256'])
                if (identity in ids or not start <= stamp <= end or stamp > received
                        or previous is not None and stamp <= previous['received_at']
                        or type(event['payload']) is not dict):
                    raise ValueError('OPERATING_EVENT_ID_OR_WINDOW_DIFFERS')
                if event['case_id'] is not None: text(event['case_id'])
                if event['generation'] is not None: text(event['generation'])
                if event['case_id'] is not None and event['generation'] is None:
                    raise ValueError('OPERATING_EVENT_GENERATION_REQUIRED')
                ids.add(identity); events.append(json.loads(encoded(event)))
            previous = frame
        if frames[0]['received_at'] > start or frames[-1]['received_at'] < end:
            raise ValueError('OPERATING_WINDOW_BOUNDARY_MISSING')
        checked['streams'][name] = dict(run_id=stream['run_id'], events=events,
            gaps=[max(b['received_at'] - a['received_at'], b['monotonic_at'] - a['monotonic_at'])
                  for a, b in zip(frames, frames[1:])])
    return checked
