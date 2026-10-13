"""Reviewed label diagnostics; measured rates do not certify physical result provenance."""
import math

from .operational_comparison import fields, sha, text, timestamp

ERRORS = ('missing_evidence_error', 'risk_omission', 'wrong_case', 'unnecessary_intervention')
TRUTH = ('id', 'subject_id', 'case_id', 'session_id', 'recording_id', 'session_sha256', 'recording_sha256',
         'start', 'end', 'expected', 'actor', 'resolved', 'recurrence', 'result_source_sha256',
         'recurrence_source_sha256', 'latency_source_sha256', 'latency_ms', *ERRORS)


def measure_truth(rows):
    if type(rows) is not list or not 1 <= len(rows) <= 10000: raise ValueError('BOUNDED_OPERATING_TRUTH_ROWS_REQUIRED')
    ids, cases, missing, latencies, normal, resolved, recurred, unknown = set(), set(), set(), [], 0, 0, 0, 0
    counts = dict.fromkeys(ERRORS, 0)
    for row in rows:
        fields(row, TRUTH)
        for key in ('id', 'subject_id', 'session_id', 'recording_id'): text(row[key])
        for key in ('session_sha256', 'recording_sha256'): sha(row[key])
        if row['id'] in ids: raise ValueError('DUPLICATE_OPERATING_TRUTH_ID')
        ids.add(row['id'])
        if not 0 < timestamp(row['end']) - timestamp(row['start']) <= 86400:
            raise ValueError('OPERATING_TRUTH_WINDOW_DIFFERS')
        if (row['expected'] not in {'DO_NOT_INTERVENE', 'BACK_AND_RETRY', 'HUMAN_FINAL'}
                or row['actor'] not in {'none', 'model', 'rule', 'core', 'human'}
                or any(type(row[key]) is not bool for key in ERRORS)
                or any(row[key] is not None and type(row[key]) is not bool for key in ('resolved', 'recurrence'))):
            raise ValueError('INVALID_REVIEWED_OPERATING_TRUTH')
        for key in ('result_source_sha256', 'recurrence_source_sha256', 'latency_source_sha256'):
            if row[key] is not None: sha(row[key])
        if row['latency_ms'] is not None: latencies.append(timestamp(row['latency_ms']))
        if row['latency_ms'] is None or row['latency_source_sha256'] is None: missing.add('latency_originals')
        if row['recurrence'] is None or row['recurrence_source_sha256'] is None: missing.add('recurrence_originals')
        if row['resolved'] is None or row['result_source_sha256'] is None: missing.add('outcome_originals')
        if row['case_id'] is None:
            if row['expected'] != 'DO_NOT_INTERVENE' or row['actor'] != 'none':
                raise ValueError('NORMAL_TRUTH_CANNOT_CLAIM_PHYSICAL_ACTOR')
            normal += 1
        else:
            key = (row['subject_id'], text(row['case_id']))
            if key in cases: raise ValueError('DUPLICATE_OPERATING_TRUTH_CASE')
            cases.add(key); resolved += row['resolved'] is True; recurred += row['recurrence'] is True
            unknown += row['resolved'] is None
        for key in ERRORS: counts[key] += row[key]
    count = len(cases)
    latencies.sort()
    return dict(case_count=count, normal_window_count=normal, resolved_known=resolved, unknown_outcomes=unknown,
        resolved_rate=None if not count or unknown else resolved / count,
        recurrence_rate=None if not count or 'recurrence_originals' in missing else recurred / count,
        p95_latency_ms=None if 'latency_originals' in missing else latencies[math.ceil(.95 * len(latencies)) - 1],
        error_counts=counts, actual_invoice_micros=None), sorted(missing)
