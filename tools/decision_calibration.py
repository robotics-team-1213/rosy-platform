"""Model PC offline calibration receipt; no provider, promotion or device access."""
import argparse
import json
from pathlib import Path
import sys

LIMIT = 16 * 1024 * 1024


def feedback_bundle(data):
    """Join evidence to explicit review; never synthesize labels or refresh approval hashes."""
    from dataclasses import asdict
    from decimal import Decimal, ROUND_CEILING
    from learning.evaluation.decision.operational_comparison import checked_export, digest, fields, sha
    from rosy.decision.deliberation import Problem, canonical
    from rosy.decision.deliberation.profiles import ModelProfile, BoundProfile, incident_profiles
    from rosy.decision.deliberation.judgment import judgment
    from rosy.decision.deliberation.contracts.billing import CostEvidence
    from rosy.decision.deliberation.evaluation.calibration import LINEAGE, ERRORS, IDENTITY
    fields(data, ('schema', 'exports', 'fit', 'evaluation', 'training', 'reviewed_profile'))
    if data['schema'] != 'rosy.calibration.feedback_input/1': raise ValueError('INVALID_FEEDBACK_CALIBRATION_SCHEMA')
    frozen = data['reviewed_profile']
    if type(frozen) is not dict: raise ValueError('INVALID_REVIEWED_PROFILE')
    exports = data['exports']
    if type(exports) is not list or not 1 <= len(exports) <= 4096: raise ValueError('INVALID_FEEDBACK_EXPORTS')
    available, required = {}, set()
    for exported in exports:
        case, _ = checked_export(exported)
        export_id = exported['digest']
        if export_id in available: raise ValueError('DUPLICATE_FEEDBACK_EXPORT')
        profiles = incident_profiles(tuple(ModelProfile(**p) for p in case['profiles']))
        selected = [p for p in profiles if digest(asdict(p)) == frozen['full_profile_sha256']]
        if len(selected) != 1: raise ValueError('FEEDBACK_PROFILE_CHANGED')
        profile = selected[0]
        attempts = {a['attempt_id']: a for a in case['attempts']}
        required.update((export_id, a['attempt_id']) for a in attempts.values()
                        if a['kind'] == 'model' and a['role'] == profile.role)
        available[export_id] = (case, attempts, profile)
    result = {k: data[k] for k in ('training', 'reviewed_profile')}
    used, inputs, used_exports = set(), set(), set()
    binding_keys = ('export_digest', 'subject_id', 'case_id', 'attempt_id', 'receipt_sha256', 'latency_source_sha256')
    review_keys = ('id', *LINEAGE, 'reviewed_by', 'expected', 'latency_ms', *ERRORS)
    for split in ('fit', 'evaluation'):
        rows = data[split]
        if type(rows) is not list or not 1 <= len(rows) <= 10000: raise ValueError('INVALID_FEEDBACK_REVIEW_ROWS')
        result[split] = []
        for row in rows:
            fields(row, (*review_keys, *binding_keys))
            key = (sha(row['export_digest']), row['attempt_id'])
            if key not in required or key in used: raise ValueError('UNBOUND_OR_DUPLICATE_FEEDBACK_REVIEW')
            case, attempts, profile = available[key[0]]
            attempt = attempts[key[1]]
            receipt = attempt['model_receipt']
            if (attempt['state'] not in {'COMPLETED', 'REJECTED'} or type(receipt) is not dict
                    or digest(receipt) != sha(row['receipt_sha256'])):
                raise ValueError('MISSING_OR_CHANGED_FEEDBACK_PREDICTION')
            versioned = receipt.get('schema') == 'rosy.incident.model_receipt/2' or (
                receipt.get('schema') == 'rosy.incident.model_receipt/3' and 'cost_evidence' in receipt)
            fields(receipt, ('schema', 'profiles', 'role', 'problem', 'judgment', *(['cost_evidence'] if versioned else [])))
            if (receipt['schema'] not in {'rosy.incident.model_receipt/1', 'rosy.incident.model_receipt/2', 'rosy.incident.model_receipt/3'}
                    or receipt['profiles'] != case['profiles'] or receipt['role'] != profile.role
                    or (len(case['profiles']) == 1) != receipt['schema'].endswith('/3')):
                raise ValueError('FEEDBACK_RECEIPT_PROFILE_CHANGED')
            canonical(receipt)
            problem = Problem(**receipt['problem'])
            bound = BoundProfile(profile, problem.digest)
            identity = dict(profile_revision=profile.profile_revision, model_revision=profile.model_revision,
                            domain=problem.domain, calibration_revision=profile.calibration_revision,
                            full_profile_sha256=digest(asdict(profile)))
            if (canonical(asdict(problem)) != canonical(receipt['problem'])
                    or problem.domain not in profile.domains or 'text' not in profile.modalities
                    or any(identity[k] != frozen[k] for k in IDENTITY)
                    or list(problem.choices) != frozen['choices']
                    or (problem.subject_id, problem.case_id) != (row['subject_id'], row['case_id'])
                    or (problem.subject_id, problem.case_id) != (case['scope']['subject_id'], case['scope']['case_id'])
                    or attempt['input_hash'] != problem.digest or attempt['observation_revision'] != problem.generation
                    or problem.digest in inputs):
                raise ValueError('FEEDBACK_SAMPLE_IDENTITY_CHANGED')
            checked = judgment(problem, bound, receipt['judgment'])
            if versioned:
                evidence = CostEvidence(canonical(receipt['cost_evidence']))
                cost = evidence.payload['marginal_cash_usd']
                evidence.validate(problem, bound, checked, cost)
                if int((Decimal(str(cost))*1_000_000).to_integral_value(rounding=ROUND_CEILING)) != attempt['actual_micros']:
                    raise ValueError('FEEDBACK_COST_CHANGED')
            binding = {k: row[k] for k in binding_keys}
            sha(binding['latency_source_sha256'])
            binding.update(input_hash=problem.digest, observation_revision=problem.generation)
            result[split].append(dict(**{k: row[k] for k in review_keys}, **identity,
                alternatives=checked.payload['alternatives'], abstained=checked.choice is None,
                feedback_binding=binding))
            used.add(key); inputs.add(problem.digest); used_exports.add(key[0])
    if used != required or used_exports != set(available): raise ValueError('INCOMPLETE_FEEDBACK_REVIEW')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='frozen fit/evaluation/training/reviewed_profile JSON')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--compare', action='store_true', help='compare 2-4 bundles on identical held-out truth')
    mode.add_argument('--candidate', action='store_true', help='bind a full profile to recomputed calibration inputs')
    parser.add_argument('--from-feedback', action='store_true', help='bind model exports to separately reviewed samples')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / 'operations/decision/src'), str(root / 'contracts/foundation'),
                   str(root / 'contracts/learning/src')]
    try:
        from rosy.decision.deliberation.calibration import evaluate_calibration
        with args.input.open('rb') as source:
            raw = source.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('CALIBRATION_INPUT_EXCEEDED')
        data = json.loads(raw)
        if args.candidate:
            from rosy.decision.deliberation.evaluation.reasoning_candidate import build_candidate
            if type(data) is not dict or set(data) != {'profile', 'calibration_input'}:
                raise ValueError('INVALID_REASONING_CANDIDATE_INPUT')
            inputs = feedback_bundle(data['calibration_input']) if args.from_feedback else data['calibration_input']
            candidate = build_candidate(data['profile'], inputs)
            print(json.dumps(candidate, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False))
            return 0 if candidate['calibration_report']['state'] == 'PASS_OFFLINE_ONLY' else 1
        if args.from_feedback:
            data = [feedback_bundle(b) for b in data] if args.compare and type(data) is list else feedback_bundle(data)
        if args.compare:
            from rosy.decision.deliberation.evaluation.comparison import compare_calibrations
            artifact = compare_calibrations(data)
        else:
            if type(data) is not dict or set(data) != {'fit', 'evaluation', 'training', 'reviewed_profile'}:
                raise ValueError('INVALID_CALIBRATION_BUNDLE')
            artifact = evaluate_calibration(data['fit'], data['evaluation'],
                training=data['training'], reviewed_profile=data['reviewed_profile'])
        print(artifact.report_json)
        return 0 if artifact.report['state'] in {'PASS_OFFLINE_ONLY', 'PASS_COMPARISON_OFFLINE_ONLY'} else 1
    except (OSError, ValueError, TypeError, KeyError, ImportError, RecursionError, OverflowError):
        print('{"state":"HOLD","reason":"INVALID_CALIBRATION_INPUT","field_accepted":false}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
