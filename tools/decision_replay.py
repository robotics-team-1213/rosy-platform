"""Offline, loopback-only choice replay for Jev-compatible decision servers."""

import argparse
import hashlib
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def replay(data: Path, endpoint: str, model: str, timeout: float) -> dict:
    url = urllib.parse.urlsplit(endpoint)
    if (url.scheme != "http" or url.hostname not in ("localhost", "127.0.0.1", "::1")
            or url.path != "/v1/systemone" or url.query or url.fragment):
        raise ValueError("endpoint must be a loopback http://.../v1/systemone URL")
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    raw = data.read_bytes()
    cases = []
    seen = set()
    for line_number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        case_id = case["id"]
        criteria = case["criteria"]
        if (not isinstance(case_id, str) or not case_id or case_id in seen
                or not isinstance(criteria, dict) or len(criteria) < 2
                or any(not isinstance(k, str) or not k or not isinstance(v, str)
                       for k, v in criteria.items())
                or case["expected"] not in criteria
                or not isinstance(case["instructions"], str)
                or not case["instructions"]):
            raise ValueError(f"invalid case at line {line_number}")
        seen.add(case_id)
        cases.append((case_id, case, criteria))
    if not cases:
        raise ValueError("no cases")

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    rows = []
    for case_id, case, criteria in cases:
        body = {"state": case["state"], "model": model, "questions": {
            "decision": {"type": "choice", "instructions": case["instructions"],
                         "criteria": criteria}}}
        req = urllib.request.Request(endpoint, json.dumps(body).encode("utf-8"),
                                     {"Content-Type": "application/json"}, method="POST")
        started = time.perf_counter()
        predicted = None
        error = None
        try:
            with opener.open(req, timeout=timeout) as response:
                answer = json.load(response)["answers"]["decision"]
                predicted = answer["choice"]
                if not isinstance(predicted, str) or predicted not in criteria:
                    predicted = None
                    raise ValueError("choice outside criteria")
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError,
                TypeError, json.JSONDecodeError) as exc:
            error = type(exc).__name__
        rows.append({"id": case_id, "expected": case["expected"],
                     "predicted": predicted, "correct": predicted == case["expected"],
                     "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                     "error": error})
    latencies = sorted(row["latency_ms"] for row in rows)
    return {"model": model, "dataset_sha256": hashlib.sha256(raw).hexdigest(),
            "cases": rows, "summary": {
        "count": len(rows), "correct": sum(row["correct"] for row in rows),
        "abstain_or_error": sum(row["predicted"] is None for row in rows),
        "p95_latency_ms": latencies[math.ceil(0.95 * len(latencies)) - 1]}}


def compare_deliberation(cases, runs, *, training_sessions, limits,
                         training_recordings=None, reviewed_profile=None, cooperation=False):
    """Independent same-case metrics. No provider call, learned policy write or FIELD approval."""
    if type(cooperation) is not bool:
        raise ValueError('explicit cooperation comparison mode required')
    modes = ('rules', 'single', 'deliberation') + (('sequential', 'parallel', 'auto') if cooperation else ())
    if not cases or len(cases) > 10000 or type(training_sessions) is not list:
        raise ValueError('invalid evaluation set')
    if training_recordings is not None and type(training_recordings) is not list:
        raise ValueError('invalid frozen training recording manifest')
    digest = hashlib.sha256(json.dumps(cases, sort_keys=True, allow_nan=False).encode()).hexdigest()
    by_id, physical = {}, set()
    for case in cases:
        for field in ('id', 'session_id', 'recording_id'):
            value = case[field]
            if type(value) is not str or not value or value != value.strip() or len(value) > 128:
                raise ValueError('invalid frozen case identity')
        key = case['id']
        source = case['recording_id']
        if (type(key) is not str or not key or key in by_id or source in physical
                or case['session_id'] in training_sessions
                or case['recording_id'] in (training_recordings or []) or case['expected'] not in {
                    None, 'reobserve', 'human', 'map_correction', 'object_reacquire'}
                or type(case['problem_hash']) is not str or len(case['problem_hash']) != 64):
            raise ValueError('invalid, duplicate or leaked evaluation case')
        by_id[key] = case
        physical.add(source)
    rows = {}
    for row in runs:
        key = (row['mode'], row['case_id'])
        if key in rows or key[0] not in modes or key[1] not in by_id:
            raise ValueError('invalid comparison row')
        if cooperation and key[0] in ('sequential', 'parallel', 'auto'):
            allowed = {'sequential', 'parallel', 'hold'} if key[0] == 'auto' else {key[0], 'hold'}
            if (row.get('effective_mode') not in allowed or type(row.get('decision_hash')) is not str
                    or len(row['decision_hash']) != 64
                    or any(c not in '0123456789abcdef' for c in row['decision_hash'])
                    or any(type(row.get(field)) is not str or not row[field].strip()
                           for field in ('environment_revision', 'measurement_revision'))):
                raise ValueError('invalid cooperation selection evidence')
        if (row['problem_hash'] != by_id[key[1]]['problem_hash']
                or not row['profile_revision'] or not row['policy_revision']
                or type(row['forbidden_effect']) is not bool or type(row['binding_error']) is not bool
                or row['choice'] not in {None, 'reobserve', 'human', 'map_correction', 'object_reacquire'}):
            raise ValueError('comparison binding or effect invalid')
        for field in ('latency_ms', 'cost_usd'):
            if type(row[field]) not in (int, float) or not math.isfinite(row[field]) or row[field] < 0:
                raise ValueError('comparison latency or cost unknown')
        rows[key] = row
    if len(rows) != len(modes) * len(cases):
        raise ValueError('all modes must use exactly the same independent cases')
    if limits is not None:
        if set(limits) != {'error_rate', 'p95_latency_ms', 'cost_usd'}:
            raise ValueError('invalid limits')
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in limits.values()):
            raise ValueError('invalid finite limits')
        if limits['error_rate'] > 1:
            raise ValueError('invalid error rate')
    report = {'state': 'PASS_OFFLINE_ONLY', 'field_accepted': False,
              'dataset_sha256': digest, 'modes': {}}
    if (limits is None or training_recordings is None or reviewed_profile is None
            or any(not c.get('reviewed_by') for c in cases)):
        report['state'] = 'HOLD'
    if reviewed_profile is not None:
        if (set(reviewed_profile) != {'dataset_sha256', 'limits', 'reviewed_by', 'minimum_cases', 'revisions'}
                or reviewed_profile['dataset_sha256'] != digest or reviewed_profile['limits'] != limits
                or type(reviewed_profile['reviewed_by']) is not str or not reviewed_profile['reviewed_by'].strip()
                or type(reviewed_profile['minimum_cases']) is not int or reviewed_profile['minimum_cases'] < 1):
            raise ValueError('invalid frozen reviewed profile')
        revisions = reviewed_profile['revisions']
        if type(revisions) is not dict or set(revisions) != set(modes):
            raise ValueError('invalid frozen revisions')
        for mode, revision in revisions.items():
            if (type(revision) is not dict or set(revision) != {'profile_revision', 'policy_revision'}
                    or any(type(v) is not str or not v.strip() for v in revision.values())
                    or any(any(row[field] != revision[field] for field in revision)
                           for row in rows.values() if row['mode'] == mode)):
                raise ValueError('comparison revision differs from reviewed profile')
        if len(cases) < reviewed_profile['minimum_cases']:
            report['state'] = 'HOLD'
    for mode in modes:
        selected = [rows[(mode, key)] for key in by_id]
        latencies = sorted(r['latency_ms'] for r in selected)
        metrics = dict(count=len(cases), correct=sum(r['choice'] == by_id[r['case_id']]['expected'] for r in selected),
                       abstain=sum(r['choice'] is None for r in selected),
                       forbidden=sum(r['forbidden_effect'] or r['binding_error'] for r in selected),
                       p95_latency_ms=latencies[math.ceil(0.95 * len(cases)) - 1],
                       cost_usd=sum(r['cost_usd'] for r in selected))
        if cooperation:
            metrics['p50_latency_ms'] = latencies[math.ceil(0.5 * len(cases)) - 1]
        metrics['error_rate'] = 1 - metrics['correct'] / len(cases)
        report['modes'][mode] = metrics
        if metrics['forbidden'] or (limits is not None and any(metrics[k] > limits[k] for k in limits)):
            report['state'] = 'FAIL'
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path, help="JSONL with id, state, instructions, criteria, expected")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1/systemone")
    parser.add_argument("--model", help="server model ID; required for network replay")
    parser.add_argument("--comparison-runs", type=Path, help="offline same-case rules/single/deliberation rows")
    parser.add_argument("--cooperation", action="store_true", help="also compare independent sequential/parallel/auto rows")
    parser.add_argument("--reviewed-profile", type=Path, help="pre-reviewed dataset hash, limits and minimum cases")
    parser.add_argument("--training-manifest", type=Path, help="frozen training sessions and recording IDs")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    try:
        if args.comparison_runs:
            profile = json.loads(args.reviewed_profile.read_text()) if args.reviewed_profile else None
            manifest = json.loads(args.training_manifest.read_text()) if args.training_manifest else {}
            result = compare_deliberation(json.loads(args.data.read_text()),
                json.loads(args.comparison_runs.read_text()), training_sessions=manifest.get('sessions', []),
                training_recordings=manifest.get('recordings'), reviewed_profile=profile,
                limits=profile.get('limits') if profile else None, cooperation=args.cooperation)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return {'PASS_OFFLINE_ONLY': 0, 'HOLD': 2, 'FAIL': 1}[result['state']]
        if args.cooperation:
            parser.error('--cooperation requires --comparison-runs')
        if not args.model:
            parser.error('--model is required for network replay')
        result = replay(args.data, args.endpoint, args.model, args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(any(case["error"] is not None for case in result["cases"]))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"decision replay: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
