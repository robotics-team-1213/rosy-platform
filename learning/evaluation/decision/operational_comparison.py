"""Compare frozen operational evidence; independent truth and runtime admission remain separate."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > 1024 * 1024: raise ValueError('COMPARISON_INPUT_LIMIT')
    return hashlib.sha256(raw).hexdigest()


def fields(value, expected):
    if type(value) is not dict or set(value) != set(expected): raise ValueError('INVALID_COMPARISON_FIELDS')


def text(value):
    if type(value) is not str or not value or len(value) > 512 or value != value.strip():
        raise ValueError('INVALID_COMPARISON_ID')
    return value


def sha(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('INVALID_COMPARISON_HASH')
    return value


def count(value, maximum=1_000_000_000_000):
    if type(value) is not int or not 0 <= value <= maximum: raise ValueError('INVALID_COMPARISON_COUNTER')
    return value


def timestamp(value):
    if type(value) not in (int, float) or not 0 <= value <= 1_000_000_000_000 or not math.isfinite(value):
        raise ValueError('INVALID_COMPARISON_TIME')
    return value


def identities(rows, *, evaluation=False):
    if type(rows) is not list or len(rows) > 4096: raise ValueError('INVALID_COHORT_SIZE')
    seen = {key: set() for key in ('session_id', 'recording_id', 'source_sha256')}
    cases = set()
    for row in rows:
        fields(row, (*seen, 'subject_id', 'case_id') if evaluation else seen)
        for key in seen:
            value = sha(row[key]) if key.endswith('sha256') else text(row[key])
            seen[key].add(value)
        if evaluation:
            identity = (text(row['subject_id']), text(row['case_id']))
            if identity in cases: raise ValueError('DUPLICATE_COHORT_CASE')
            cases.add(identity)
    return seen, cases


def checked_export(exported):
    fields(exported, ('schema', 'case', 'digest', 'label_state', 'field_accepted'))
    if (exported['schema'] not in {'rosy.incident.model_feedback/1', 'rosy.incident.model_feedback/2'}
            or exported['label_state'] != 'UNREVIEWED' or exported['field_accepted'] is not False
            or digest(exported['case']) != sha(exported['digest'])):
        raise ValueError('UNBOUND_COMPARISON_EXPORT')
    case = exported['case']
    base = {'scope', 'budget', 'profiles', 'state', 'reason', 'calls', 'observations',
            'spent_micros', 'reserved_micros', 'attempts', 'closure', 'outcome'}
    fields(case, base | ({'handoff'} if exported['schema'].endswith('/2') else set()))
    scope = case['scope']
    fields(scope, ('subject_id', 'case_id', 'owner_id', 'profile_sha256', 'policy_revision'))
    for value in scope.values(): text(value)
    sha(scope['profile_sha256'])
    profiles = case['profiles']
    if (type(profiles) is not list or len(profiles) != 2 or any(type(p) is not dict for p in profiles)
            or [p.get('role') for p in profiles] != ['primary', 'reviewer']
            or digest(profiles) != scope['profile_sha256']):
        raise ValueError('INVALID_PAIRED_STRATEGY_PROFILES')
    if case['state'] not in {'ACTIVE', 'HOLD', 'NOT_NEEDED'}: raise ValueError('INVALID_CASE_STATE')
    text(case['reason'])
    expected = ('IN_PROGRESS' if case['state'] == 'ACTIVE' else
                'DO_NOT_INTERVENE' if case['state'] == 'NOT_NEEDED' else
                'RESOLVED_OBSERVED' if case['closure'] is not None else 'UNRESOLVED')
    if case['outcome'] != expected: raise ValueError('CASE_OUTCOME_CHANGED')
    for key in ('calls', 'observations', 'spent_micros', 'reserved_micros'): count(case[key])
    attempts = case['attempts']
    if type(attempts) is not list or len(attempts) > 16: raise ValueError('INVALID_COMPARISON_ATTEMPTS')
    costs, liabilities, unknown, calls, observations, ids = 0, 0, 0, 0, 0, set()
    for row in attempts:
        fields(row, ('attempt_id', 'input_hash', 'observation_revision', 'kind', 'role', 'state',
                     'reserved_micros', 'actual_micros', 'summary', 'model_receipt'))
        if text(row['attempt_id']) in ids: raise ValueError('DUPLICATE_COMPARISON_ATTEMPT')
        ids.add(row['attempt_id']); sha(row['input_hash']); text(row['observation_revision'])
        if row['kind'] not in {'model', 'observation'} or row['state'] not in {'RESERVED', 'SUBMITTING', 'COMPLETED', 'REJECTED', 'UNKNOWN'}:
            raise ValueError('INVALID_COMPARISON_ATTEMPT')
        if row['role'] not in {None, 'primary', 'reviewer'} or row['kind'] == 'observation' and row['role'] is not None:
            raise ValueError('INVALID_ATTEMPT_ROLE')
        amount, actual = count(row['reserved_micros']), row['actual_micros']
        if actual is not None: costs += count(actual)
        if row['state'] in {'COMPLETED', 'REJECTED'} and actual is None: raise ValueError('MISSING_TERMINAL_COST')
        if row['state'] in {'RESERVED', 'SUBMITTING'} and actual is not None: raise ValueError('IMPOSSIBLE_ATTEMPT_COST')
        if row['kind'] == 'observation' and (amount or actual not in (None, 0)): raise ValueError('INVALID_OBSERVATION_COST')
        if row['state'] in {'RESERVED', 'SUBMITTING', 'UNKNOWN'}:
            liabilities += amount if actual is None else max(0, amount - actual)
        calls += row['kind'] == 'model'; observations += row['kind'] == 'observation'
        unknown += row['kind'] == 'model' and actual is None
    if (calls, observations, costs, liabilities) != (case['calls'], case['observations'], case['spent_micros'], case['reserved_micros']):
        raise ValueError('COMPARISON_COUNTERS_CHANGED')
    if case['state'] == 'NOT_NEEDED' and attempts: raise ValueError('INTERVENTION_IN_NOT_NEEDED_CASE')
    if case['closure'] is not None:
        proof = case['closure']
        fields(proof, ('scope', 'requested_at', 'observed_at', 'closed_at', 'normal_revision', 'action_credit', 'state'))
        if (proof['scope'] != scope or proof['state'] != 'RESOLVED_OBSERVED'
                or case['reason'] != proof['state'] or proof['action_credit'] not in {'NONE', 'UNVERIFIED'}):
            raise ValueError('INVALID_COMPARISON_CLOSURE')
        requested = timestamp(proof['requested_at'])
        if (requested != case['budget']['started_at'] or timestamp(proof['observed_at']) <= requested
                or timestamp(proof['closed_at']) <= requested
                or any(row['state'] in {'RESERVED', 'SUBMITTING'} for row in attempts)):
            raise ValueError('INVALID_COMPARISON_CLOSURE_TIME')
        text(proof['normal_revision'])
    if 'handoff' in case:
        from rosy.contracts.learning.incident_handoff import validate_handoff
        validate_handoff(case['handoff'], scope, case['budget']['started_at'])
    return case, unknown


def compare(cohort, exports):
    """Report unreviewed evidence counts, never causal success or accepted quality."""
    digest(cohort)
    fields(cohort, ('schema', 'domain', 'training', 'fit', 'evaluation', 'candidates'))
    if cohort['schema'] != 'rosy.incident.operational_cohort/1': raise ValueError('INVALID_COHORT_SCHEMA')
    text(cohort['domain'])
    groups = [identities(cohort[key], evaluation=key == 'evaluation') for key in ('training', 'fit', 'evaluation')]
    for index, (left, _) in enumerate(groups):
        for right, _ in groups[index + 1:]:
            if any(left[key] & right[key] for key in left): raise ValueError('COMPARISON_SPLIT_LEAK')
    cases = groups[-1][1]
    candidates = cohort['candidates']
    if not cases or type(candidates) is not list or not 1 <= len(candidates) <= 4: raise ValueError('EMPTY_COMPARISON_COHORT')
    if type(exports) is not list or len(exports) > 4096: raise ValueError('INVALID_EXPORT_SET')
    available = {}
    for exported in exports:
        case, unknown = checked_export(exported)
        if exported['digest'] in available: raise ValueError('DUPLICATE_COMPARISON_EXPORT')
        available[exported['digest']] = (case, unknown)
    reports, used, strategies = [], set(), set()
    for candidate in candidates:
        fields(candidate, ('strategy', 'strategy_sha256', 'profile_sha256', 'policy_revision', 'exports'))
        if candidate['strategy'] != 'primary_reviewer': raise ValueError('PAIRED_EXPORT_CANNOT_PROVE_RULE_OR_PRIMARY')
        strategy = sha(candidate['strategy_sha256'])
        if strategy in strategies: raise ValueError('DUPLICATE_STRATEGY')
        strategies.add(strategy); sha(candidate['profile_sha256']); text(candidate['policy_revision'])
        bindings = candidate['exports']
        if type(bindings) is not list or len(bindings) != len(cases): raise ValueError('INCOMPLETE_COMPARISON_CASES')
        matched, outcomes, spent, reserved, unknowns = set(), {}, 0, 0, 0
        for binding in bindings:
            fields(binding, ('subject_id', 'case_id', 'digest'))
            key = (text(binding['subject_id']), text(binding['case_id']))
            receipt = sha(binding['digest'])
            if key not in cases or key in matched or receipt not in available or receipt in used:
                raise ValueError('COMPARISON_CASE_BINDING_CHANGED')
            case, unknown = available[receipt]; scope = case['scope']
            if ((scope['subject_id'], scope['case_id']) != key or scope['profile_sha256'] != candidate['profile_sha256']
                    or scope['policy_revision'] != candidate['policy_revision']):
                raise ValueError('COMPARISON_SCOPE_CHANGED')
            matched.add(key); used.add(receipt)
            outcomes[case['outcome']] = outcomes.get(case['outcome'], 0) + 1
            spent += case['spent_micros']; reserved += case['reserved_micros']; unknowns += unknown
        reports.append(dict(strategy=candidate['strategy'], strategy_sha256=strategy,
            profile_sha256=candidate['profile_sha256'], case_count=len(matched), outcomes=outcomes,
            known_marginal_micros=spent, reserved_liability_micros=reserved, unknown_cost_attempts=unknowns,
            observed_invoice_micros=None, normal_command_count=None, recurrence_count=None))
    if used != set(available): raise ValueError('EXTRA_COMPARISON_EXPORT')
    return dict(schema='rosy.incident.operational_comparison/1', state='HOLD', promotion_state='HOLD',
        field_accepted=False, truth_admitted=False, cohort_sha256=digest(cohort), candidates=reports,
        missing=['rule_baseline', 'primary_baseline', 'independent_truth', 'acceptance_limits',
                 'normal_command_coverage', 'recurrence_coverage', 'actual_invoice', 'runtime_admission',
                 'input_lineage_admission', 'strategy_provenance'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cohort', type=Path)
    parser.add_argument('exports', type=Path, nargs='+')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    def read(path):
        with path.open('rb') as source: raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024: raise ValueError('COMPARISON_INPUT_LIMIT')
        return json.loads(raw)
    report = compare(read(args.cohort), [read(path) for path in args.exports])
    with args.out.open('x', encoding='utf-8') as output:
        output.write(json.dumps(report, sort_keys=True, allow_nan=False) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
