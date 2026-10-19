"""Compare frozen operational evidence; independent truth and runtime admission remain separate."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys


# Format pinned: operational comparison evidence stores this digest; test_canonical_hash_formats.
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


def budget_limits(value):
    fields(value, ('started_at', 'deadline', 'max_calls', 'max_observations', 'max_cost_usd', 'role_limits'))
    if not 0 < timestamp(value['deadline']) - timestamp(value['started_at']) <= 120:
        raise ValueError('INVALID_COMPARISON_BUDGET_WINDOW')
    count(value['max_calls'], 8); count(value['max_observations'], 8)
    cost = value['max_cost_usd']
    if type(cost) not in (int, float) or not 0 <= cost <= 10 or not math.isfinite(cost):
        raise ValueError('INVALID_COMPARISON_BUDGET_COST')
    roles = value['role_limits']
    if type(roles) not in (list, tuple) or len(roles) > 2: raise ValueError('INVALID_COMPARISON_ROLE_LIMITS')
    limits = {}
    for row in roles:
        if (type(row) not in (list, tuple) or len(row) != 2 or type(row[0]) is not str
                or row[0] not in {'primary', 'reviewer'} or row[0] in limits or count(row[1], 8) < 1):
            raise ValueError('INVALID_COMPARISON_ROLE_LIMITS')
        limits[row[0]] = row[1]
    return limits


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
    if (exported['schema'] not in {'rosy.incident.model_feedback/1', 'rosy.incident.model_feedback/2', 'rosy.incident.model_feedback/3'}
            or exported['label_state'] != 'UNREVIEWED' or exported['field_accepted'] is not False
            or digest(exported['case']) != sha(exported['digest'])):
        raise ValueError('UNBOUND_COMPARISON_EXPORT')
    case = exported['case']
    single = exported['schema'].endswith('/3')
    if single:
        from rosy.contracts.learning.incident_profiles import validate_primary_roles
        validate_primary_roles(case)
    base = {'scope', 'budget', 'profiles', 'state', 'reason', 'calls', 'observations',
            'spent_micros', 'reserved_micros', 'attempts', 'closure', 'outcome'}
    fields(case, base | ({'handoff'} if exported['schema'].endswith('/2') or single and 'handoff' in case else set()))
    limits = budget_limits(case['budget'])
    scope = case['scope']
    fields(scope, ('subject_id', 'case_id', 'owner_id', 'profile_sha256', 'policy_revision'))
    for value in scope.values(): text(value)
    sha(scope['profile_sha256'])
    profiles = case['profiles']
    expected_roles = ['primary'] if single else ['primary', 'reviewer']
    if (type(profiles) is not list or len(profiles) != len(expected_roles) or any(type(p) is not dict for p in profiles)
            or [p.get('role') for p in profiles] != expected_roles
            or digest(profiles) != scope['profile_sha256']):
        raise ValueError('INVALID_PAIRED_STRATEGY_PROFILES')
    if case['state'] not in {'ACTIVE', 'HOLD', 'NOT_NEEDED'}: raise ValueError('INVALID_CASE_STATE')
    text(case['reason'])
    if case['reason'] == 'RESOLVED_OBSERVED' and case['closure'] is None:
        raise ValueError('MISSING_COMPARISON_CLOSURE')
    expected = ('IN_PROGRESS' if case['state'] == 'ACTIVE' else
                'DO_NOT_INTERVENE' if case['state'] == 'NOT_NEEDED' else
                'RESOLVED_OBSERVED' if case['closure'] is not None else 'UNRESOLVED')
    if case['outcome'] != expected: raise ValueError('CASE_OUTCOME_CHANGED')
    for key in ('calls', 'observations', 'spent_micros', 'reserved_micros'): count(case[key])
    if case['calls'] > case['budget']['max_calls'] or case['observations'] > case['budget']['max_observations']:
        raise ValueError('COMPARISON_BUDGET_COUNTER_CHANGED')
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
    if limits and any(row['kind'] == 'model' and row['role'] not in limits for row in attempts):
        raise ValueError('COMPARISON_UNDECLARED_ROLE')
    if any(sum(row['kind'] == 'model' and row['role'] == role for row in attempts) > limit for role, limit in limits.items()):
        raise ValueError('COMPARISON_ROLE_BUDGET_CHANGED')
    if case['state'] == 'NOT_NEEDED' and attempts: raise ValueError('INTERVENTION_IN_NOT_NEEDED_CASE')
    if case['closure'] is not None:
        proof = case['closure']
        fields(proof, ('scope', 'requested_at', 'observed_at', 'closed_at', 'normal_revision', 'action_credit', 'state'))
        if (case['state'] != 'HOLD' or proof['scope'] != scope or proof['state'] != 'RESOLVED_OBSERVED'
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
    if type(cohort) is dict and cohort.get('schema') == 'rosy.incident.operational_cohort/2':
        return compare_with_rules(cohort, exports)
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
        if candidate['strategy'] not in {'primary', 'primary_reviewer'}: raise ValueError('MODEL_EXPORT_CANNOT_PROVE_RULE')
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
            if candidate['strategy'] != ('primary' if len(case['profiles']) == 1 else 'primary_reviewer'):
                raise ValueError('COMPARISON_STRATEGY_CHANGED')
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
        missing=['rule_baseline', *([name + '_baseline' for name in ('primary', 'primary_reviewer')
                 if name not in {row['strategy'] for row in reports}]), 'independent_truth', 'acceptance_limits',
                 'normal_command_coverage', 'recurrence_coverage', 'actual_invoice', 'runtime_admission',
                 'input_lineage_admission', 'strategy_provenance'])


def checked_rule_export(exported):
    from rosy.contracts.learning.incident_rule import validate_rule
    fields(exported, ('schema', 'scope', 'records', 'digest', 'label_state', 'field_accepted', 'coverage'))
    if (exported['schema'] != 'rosy.incident.rule_feedback/1' or exported['label_state'] != 'UNREVIEWED'
            or exported['field_accepted'] is not False or exported['coverage'] != 'retained_selections_only'
            or digest(dict(scope=exported['scope'], records=exported['records'])) != sha(exported['digest'])):
        raise ValueError('UNBOUND_RULE_COMPARISON_EXPORT')
    scope = exported['scope']
    fields(scope, ('subject_id', 'case_id', 'owner_id', 'config_sha256', 'policy_revision', 'start', 'end'))
    for name in ('subject_id', 'case_id', 'owner_id', 'policy_revision'): text(scope[name])
    sha(scope['config_sha256'])
    if not 0 < timestamp(scope['end']) - timestamp(scope['start']) <= 86400:
        raise ValueError('INVALID_RULE_COMPARISON_WINDOW')
    records = exported['records']
    if type(records) is not list or not 1 <= len(records) <= 4096: raise ValueError('EMPTY_RULE_COMPARISON_RECORDS')
    ids, selections, necessities = [], {}, {}
    for row in records:
        fields(row, ('selection_id', 'received_at', 'receipt', 'sha256'))
        if count(row['selection_id']) < 1: raise ValueError('INVALID_RULE_COMPARISON_CURSOR')
        received = timestamp(row['received_at'])
        receipt = validate_rule(row['receipt']); assessment = receipt['assessment']; request = assessment['request']
        raw = json.dumps(receipt, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        if (hashlib.sha256(raw).hexdigest() != sha(row['sha256']) or receipt['strategy'] != 'RULE_ONLY'
                or (request['subject_id'], request['case_id'], request['owner']) !=
                   (scope['subject_id'], scope['case_id'], scope['owner_id'])
                or receipt['config_sha256'] != scope['config_sha256'] or assessment['policy_revision'] != scope['policy_revision']
                or not scope['start'] <= received <= scope['end'] or received < assessment['evaluated_at']):
            raise ValueError('RULE_COMPARISON_SCOPE_CHANGED')
        ids.append(row['selection_id'])
        for counts, value in ((selections, receipt['selection']['kind']), (necessities, assessment['necessity'])):
            counts[value] = counts.get(value, 0) + 1
    if ids != sorted(set(ids)): raise ValueError('DUPLICATE_RULE_COMPARISON_CURSOR')
    return scope, selections, necessities


def compare_with_rules(cohort, exports):
    fields(cohort, ('schema', 'domain', 'training', 'fit', 'evaluation', 'candidates', 'rules'))
    digest(cohort)
    if type(exports) is not list or len(exports) > 4096: raise ValueError('INVALID_EXPORT_SET')
    models, available = [], {}
    for exported in exports:
        if type(exported) is dict and exported.get('schema') == 'rosy.incident.rule_feedback/1':
            checked = checked_rule_export(exported)
            if exported['digest'] in available: raise ValueError('DUPLICATE_RULE_COMPARISON_EXPORT')
            available[exported['digest']] = checked
        else: models.append(exported)
    model_cohort = {key: value for key, value in cohort.items() if key != 'rules'}
    model_cohort['schema'] = 'rosy.incident.operational_cohort/1'
    report = compare(model_cohort, models)
    cases = identities(cohort['evaluation'], evaluation=True)[1]
    if type(cohort['rules']) is not list or not 1 <= len(cohort['rules']) <= 4: raise ValueError('EMPTY_RULE_CANDIDATES')
    used, strategies = set(), {row['strategy_sha256'] for row in report['candidates']}
    for candidate in cohort['rules']:
        fields(candidate, ('strategy_sha256', 'config_sha256', 'owner_id', 'policy_revision', 'exports'))
        strategy = sha(candidate['strategy_sha256']); sha(candidate['config_sha256'])
        text(candidate['owner_id']); text(candidate['policy_revision'])
        if strategy in strategies: raise ValueError('DUPLICATE_STRATEGY')
        strategies.add(strategy)
        if type(candidate['exports']) is not list or len(candidate['exports']) != len(cases): raise ValueError('INCOMPLETE_RULE_CASES')
        matched, selections, necessities = set(), {}, {}
        for binding in candidate['exports']:
            fields(binding, ('subject_id', 'case_id', 'digest'))
            key, receipt_hash = (text(binding['subject_id']), text(binding['case_id'])), sha(binding['digest'])
            if key not in cases or key in matched or receipt_hash not in available or receipt_hash in used:
                raise ValueError('RULE_COMPARISON_CASE_CHANGED')
            scope, selected, necessary = available[receipt_hash]
            if ((scope['subject_id'], scope['case_id']) != key or scope['config_sha256'] != candidate['config_sha256']
                    or scope['owner_id'] != candidate['owner_id'] or scope['policy_revision'] != candidate['policy_revision']):
                raise ValueError('RULE_COMPARISON_STRATEGY_CHANGED')
            matched.add(key); used.add(receipt_hash)
            for total, counts in ((selections, selected), (necessities, necessary)):
                for name, value in counts.items(): total[name] = total.get(name, 0) + value
        report['candidates'].append(dict(strategy='rule', strategy_sha256=strategy,
            config_sha256=candidate['config_sha256'], policy_revision=candidate['policy_revision'],
            case_count=len(matched), selections=selections, necessities=necessities, outcomes=None,
            model_call_count=None, known_marginal_micros=None, reserved_liability_micros=None,
            unknown_cost_attempts=None, observed_invoice_micros=None, normal_command_count=None, recurrence_count=None))
    if used != set(available): raise ValueError('EXTRA_RULE_COMPARISON_EXPORT')
    report.update(schema='rosy.incident.operational_comparison/2', cohort_sha256=digest(cohort))
    report['missing'].remove('rule_baseline')
    report['missing'] += ['rule_operational_baseline', 'rule_command_coverage', 'rule_model_call_coverage']
    return report


def compare_with_inventory(cohort, exports, inventories, *, expected_digests):
    report = compare(cohort, exports)
    candidates = {(row['profile_sha256'], row['policy_revision']) for row in cohort['candidates']}
    if (type(inventories) is not list or type(expected_digests) is not list
            or len(inventories) != len(candidates) or len(expected_digests) != len(inventories)):
        raise ValueError('EXPLICIT_FROZEN_INVENTORIES_REQUIRED')
    available = {}
    for exported in exports:
        if exported['schema'].startswith('rosy.incident.model_feedback/'):
            case, _ = checked_export(exported)
            scope = case['scope']
            cases = available.setdefault((scope['profile_sha256'], scope['policy_revision']), {})
            key = (scope['subject_id'], scope['case_id'])
            if key in cases: raise ValueError('AMBIGUOUS_INVENTORY_CASE_EXPORT')
            cases[key] = case
    used, receipts = set(), []
    keys = ('scope', 'budget', 'state', 'reason', 'calls', 'observations', 'spent_micros', 'reserved_micros')
    for inventory, expected in zip(inventories, expected_digests):
        fields(inventory, ('schema', 'scope', 'records', 'digest', 'label_state', 'field_accepted', 'coverage'))
        if (inventory['schema'] != 'rosy.incident.case_inventory/1' or inventory['label_state'] != 'UNREVIEWED'
                or inventory['field_accepted'] is not False or inventory['coverage'] != 'retained_case_rows_only'
                or digest(dict(scope=inventory['scope'], records=inventory['records'])) != sha(expected)
                or inventory['digest'] != expected): raise ValueError('INVENTORY_DIGEST_OR_ADMISSION_DIFFERS')
        scope = inventory['scope']
        fields(scope, ('owner_id', 'policy_revision', 'profile_sha256', 'start', 'end'))
        text(scope['owner_id']); text(scope['policy_revision']); sha(scope['profile_sha256'])
        if not 0 < timestamp(scope['end']) - timestamp(scope['start']) <= 86400: raise ValueError('INVALID_INVENTORY_WINDOW')
        strategy = (scope['profile_sha256'], scope['policy_revision'])
        if strategy not in candidates or strategy in used: raise ValueError('INVENTORY_STRATEGY_DIFFERS')
        rows = inventory['records']
        if type(rows) is not list or len(rows) > 1000: raise ValueError('INVENTORY_CASE_LIMIT')
        matched = set()
        for row in rows:
            fields(row, keys)
            fields(row['scope'], ('subject_id', 'case_id', 'owner_id', 'profile_sha256', 'policy_revision'))
            key = (text(row['scope']['subject_id']), text(row['scope']['case_id']))
            cases = available.get(strategy, {})
            if key in matched or key not in cases: raise ValueError('INVENTORY_CASE_SET_DIFFERS')
            case = cases[key]
            if (row != {name: case[name] for name in keys} or case['scope']['owner_id'] != scope['owner_id']
                    or not scope['start'] <= case['budget']['started_at'] < scope['end']):
                raise ValueError('INVENTORY_CASE_STATE_DIFFERS')
            matched.add(key)
        if matched != set(available.get(strategy, {})): raise ValueError('INVENTORY_CASE_SET_DIFFERS')
        used.add(strategy); receipts.append(expected)
    report['case_inventory'] = dict(coverage='retained_case_rows_only', digests=receipts)
    return report


def main(argv=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'contracts/learning/src'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cohort', type=Path)
    parser.add_argument('exports', type=Path, nargs='+')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, nargs='+')
    parser.add_argument('--inventory-digest', nargs='+')
    args = parser.parse_args(argv)
    def read(path):
        with path.open('rb') as source: raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024: raise ValueError('COMPARISON_INPUT_LIMIT')
        return json.loads(raw)
    if (args.inventory is None) != (args.inventory_digest is None):
        raise ValueError('EXPLICIT_FROZEN_INVENTORIES_REQUIRED')
    cohort, exports = read(args.cohort), [read(path) for path in args.exports]
    report = (compare_with_inventory(cohort, exports, [read(path) for path in args.inventory],
              expected_digests=args.inventory_digest) if args.inventory else compare(cohort, exports))
    with args.out.open('x', encoding='utf-8') as output:
        output.write(json.dumps(report, sort_keys=True, allow_nan=False) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
