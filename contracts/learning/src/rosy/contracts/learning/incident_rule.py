"""Unreviewed actual rule selection; never a command or outcome admission."""
import json
import math
import re
from .digest import is_sha256_hex


def validate_rule(value):
    def fields(item, names):
        if type(item) is not dict or set(item) != set(names.split()):
            raise ValueError('INVALID_RULE_SELECTION_FIELDS')
    def text(item, *, empty=False, nullable=False):
        if nullable and item is None: return
        if type(item) is not str or len(item) > 512 or item != item.strip() or not empty and not item:
            raise ValueError('INVALID_RULE_SELECTION_ID')
    def finite(item, *, nullable=False):
        if nullable and item is None: return
        if type(item) not in (int, float) or not math.isfinite(item):
            raise ValueError('INVALID_RULE_SELECTION_CLOCK')
    fields(value, 'schema assessment selection source_sha256 config_sha256 strategy verification action_admissible outcome')
    if (value['schema'] != 'rosy.incident.rule_selection/1' or value['strategy'] not in ('RULE_ONLY', 'MIXED')
            or value['verification'] != 'selected_not_executed' or value['action_admissible'] is not False
            or value['outcome'] is not None):
        raise ValueError('RULE_SELECTION_CANNOT_ADMIT_ACTION_OR_OUTCOME')
    for name in ('source_sha256', 'config_sha256'):
        if type(value[name]) is not str or not is_sha256_hex(value[name]):
            raise ValueError('INVALID_RULE_SELECTION_HASH')
    assessment = value['assessment']
    fields(assessment, 'necessity reason request policy_revision evaluated_at valid_until')
    if assessment['necessity'] not in ('INTERVENE', 'DO_NOT_INTERVENE', 'ABSTAIN'):
        raise ValueError('INVALID_RULE_NECESSITY')
    text(assessment['reason']); text(assessment['policy_revision'])
    finite(assessment['evaluated_at']); finite(assessment['valid_until'])
    if assessment['valid_until'] < assessment['evaluated_at']:
        raise ValueError('INVALID_RULE_SELECTION_TTL')
    request = assessment['request']
    fields(request, 'subject_id case_id revision owner condition evidence since until conflicted')
    text(request['subject_id']); text(request['case_id'], nullable=True)
    text(request['revision'], empty=assessment['necessity'] == 'ABSTAIN')
    text(request['owner'], nullable=True); text(request['condition'])
    finite(request['since'], nullable=True); finite(request['until'], nullable=True)
    if type(request['conflicted']) is not bool or type(request['evidence']) is not list or len(request['evidence']) > 64:
        raise ValueError('INVALID_RULE_EVIDENCE')
    for evidence in request['evidence']:
        fields(evidence, 'subject_id source reference observed_at case_id')
        text(evidence['subject_id']); text(evidence['source']); text(evidence['reference'], empty=True)
        text(evidence['case_id'], nullable=True); finite(evidence['observed_at'], nullable=True)
    selection = value['selection']
    # D-622: only a REALIGN answer carries the digest of its manoeuvre body; other shapes are unchanged.
    realign = type(selection) is dict and 'realign_sha256' in selection
    fields(selection, 'kind rule decision reason yield_m yield_turn_rad' + ' realign_sha256' * realign)
    kind = selection['kind']
    if kind not in ('NONE', 'ANSWER', 'HOLD', 'HANDOFF'):
        raise ValueError('INVALID_RULE_SELECTION_KIND')
    for name in ('rule', 'decision', 'reason'): text(selection[name], nullable=True)
    for name in ('yield_m', 'yield_turn_rad'): finite(selection[name], nullable=True)
    if kind == 'ANSWER':
        if selection['rule'] is None or selection['decision'] not in ('WAIT', 'BACK_AND_RETRY', 'YIELD', 'RESUME', 'REALIGN'):
            raise ValueError('INVALID_RULE_ANSWER')
        if (selection['decision'] == 'REALIGN') != realign or realign and (
                type(selection['realign_sha256']) is not str or not is_sha256_hex(selection['realign_sha256'])):
            raise ValueError('UNBOUND_RULE_REALIGN')
        if selection['decision'] != 'YIELD' and any(selection[n] is not None for n in ('yield_m', 'yield_turn_rad')):
            raise ValueError('UNBOUND_RULE_YIELD')
    elif realign or any(selection[n] is not None for n in ('rule', 'decision', 'yield_m', 'yield_turn_rad')) or (
            (kind == 'NONE') != (selection['reason'] is None)):
        raise ValueError('INVALID_RULE_HOLD_OR_HANDOFF')
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(raw.encode()) > 65536 or re.search(r'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----', raw):
        raise ValueError('RULE_SELECTION_LIMIT_OR_CREDENTIAL')
    return json.loads(raw)


def baseline_choice(value):
    value = validate_rule(value)
    if value['strategy'] != 'RULE_ONLY' or value['assessment']['necessity'] != 'INTERVENE': return None
    selection = value['selection']
    if selection['kind'] == 'HOLD': return 'reobserve'
    if selection['kind'] == 'HANDOFF': return 'human'
    return None
