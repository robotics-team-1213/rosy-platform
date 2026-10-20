"""Sample approval ledger for UI development; never issues an execution lease."""
import re
from response import error, reply

RULES = {'stages': ['L0', 'L1', 'L2', 'L3', 'LIMITED'], 'two_person_stages': ['L3', 'LIMITED'],
         'windows': {
             'shadow': {'min_stage': 'L2', 'default_minutes': 480, 'max_minutes': 480, 'two_person': False, 'runtime_lease': False},
             'supervised': {'min_stage': 'L3', 'default_minutes': 15, 'max_minutes': 30, 'two_person': True, 'runtime_lease': True},
             'limited': {'min_stage': 'LIMITED', 'default_minutes': 480, 'max_minutes': 480, 'two_person': True, 'runtime_lease': True}},
         'lease_default_ms': 1000, 'lease_max_ms': 2000,
         'reasons': ['new_policy', 'revision_mismatch', 'environment_out_of_range', 'policy_output_rejected',
                     'target_not_reached', 'timing_budget_exceeded', 'owner_fault', 'owner_hold', 'other'],
         'resolutions': ['resume', 'abort', 'send_to_learning']}


class Governance:
    def __init__(self):
        self.state = {'workcell_id': 'sample-cell', 'now_ns': 1792454400000000000,
                      'policies': [], 'proposals': [], 'windows': [], 'confirmations': [], 'incidents': [], 'rules': RULES}

    def advance(self, event):
        if event != 'expire':
            raise ValueError('unknown policy event')
        self.state['now_ns'] += 24 * 3600 * 1000000000
        for window in self.state['windows']:
            window['active'] = False

    def handle(self, method, path, body, actor='sample'):
        base = '/workcells/sample-cell/policy'
        if (method, path) == ('GET', base):
            return reply(self.state)
        if path == base + '/lease' and method == 'POST':
            return error(409, 'NO_ACTIVE_WINDOW')
        if method != 'POST' or not path.startswith(base + '/'):
            return None
        action = path.removeprefix(base)
        if action == '/confirmations/sync-owner':
            return error(503, 'OWNER_STATE_UNAVAILABLE')
        if body.get('operator_confirmed') is not True:
            return error(422, 'INVALID_REQUEST')
        now = self.state['now_ns']
        if action == '/windows':
            rule = RULES['windows'].get(body.get('kind'))
            if rule is None:
                return error(422, 'UNKNOWN_WINDOW_KIND')
            minutes = body.get('minutes', rule['default_minutes'])
            if type(minutes) is not int or not 1 <= minutes <= rule['max_minutes'] or not body.get('scope'):
                return error(422, 'WINDOW_TOO_LONG')
            policy = next((p for p in self.state['policies'] if p['policy_revision'] == body.get('policy_revision')), None)
            if policy is None or RULES['stages'].index(policy['stage']) < RULES['stages'].index(rule['min_stage']):
                return error(409, 'STAGE_TOO_LOW')
            if any(policy[key] != body.get(key) for key in ('rig_revision', 'calibration_revision')):
                return error(409, 'REVISION_CHANGED_REAPPROVAL_REQUIRED')
            if any(p['cleared_ns'] is None for p in self.state['incidents']):
                return error(409, 'INCIDENT_OPEN')
            row = {key: body[key] for key in ('policy_revision', 'kind', 'scope')}
            row.update(window_id=f'sample-window-{len(self.state["windows"]) + 1}', workcell_id='sample-cell',
                       minutes=minutes, requested_by=actor, requested_ns=now, approved_by=None,
                       starts_ns=None, expires_ns=None, closed_ns=None, closed_reason=None, active=False)
            self.state['windows'].append(row)
            return reply(row)
        match = re.fullmatch('/windows/([^/]+)/(approve|close)', action)
        if match:
            row = next((p for p in self.state['windows'] if p['window_id'] == match[1]), None)
            if row is None:
                return error(404, 'WINDOW_NOT_FOUND')
            if match[2] == 'close':
                if not isinstance(body.get('reason'), str) or not body['reason'].strip():
                    return error(422, 'INVALID_REQUEST')
                if row['closed_ns'] is None:
                    row.update(active=False, closed_ns=now, closed_reason=f'closed by {actor}: {body["reason"]}')
                return reply(row)
            if row['approved_by'] or row['closed_ns'] is not None:
                return error(409, 'WINDOW_ALREADY_DECIDED')
            if RULES['windows'][row['kind']]['two_person'] and row['requested_by'] == actor:
                return error(403, 'APPROVER_MUST_DIFFER_FROM_PROPOSER')
            if any(p['cleared_ns'] is None for p in self.state['incidents']):
                return error(409, 'INCIDENT_OPEN')
            if any(p['active'] for p in self.state['windows']):
                return error(409, 'ANOTHER_WINDOW_ACTIVE')
            row.update(approved_by=actor, starts_ns=now, expires_ns=now + row['minutes'] * 60_000_000_000, active=True)
            return reply(row)
        if action == '/proposals':
            if not all(isinstance(body.get(key), str) and body[key].strip() for key in
                       ('policy_revision', 'to_stage', 'rig_revision', 'calibration_revision', 'evidence_sha256', 'note')):
                return error(422, 'INVALID_REQUEST')
            policies = self.state['policies']
            current = next((p for p in policies if p['policy_revision'] == body['policy_revision']), None)
            stages = RULES['stages']
            expected = stages[stages.index(current['stage']) + 1] if current and current['stage'] != stages[-1] else None if current else stages[0]
            if body['to_stage'] != expected:
                return error(409, 'STAGE_SKIP_REFUSED')
            if any(p['policy_revision'] == body['policy_revision'] and p['state'] == 'PENDING' for p in self.state['proposals']):
                return error(409, 'PROPOSAL_ALREADY_PENDING')
            row = {**body, 'proposal_id': f'sample-proposal-{len(self.state["proposals"]) + 1}',
                   'from_stage': current['stage'] if current else None, 'proposed_by': actor, 'proposed_ns': now,
                   'state': 'PENDING', 'decided_by': None, 'decided_ns': None}
            self.state['proposals'].append(row)
            return reply(row)
        match = re.fullmatch('/proposals/([^/]+)/decision', action)
        if match:
            row = next((p for p in self.state['proposals'] if p['proposal_id'] == match[1]), None)
            if row is None:
                return error(404, 'PROPOSAL_NOT_FOUND')
            if row['state'] != 'PENDING':
                return error(409, 'PROPOSAL_ALREADY_DECIDED')
            if not isinstance(body.get('approve'), bool):
                return error(422, 'INVALID_REQUEST')
            if body['approve'] and row['to_stage'] in RULES['two_person_stages'] and row['proposed_by'] == actor:
                return error(403, 'APPROVER_MUST_DIFFER_FROM_PROPOSER')
            if body['approve'] and row['to_stage'] in RULES['two_person_stages'] and any(p['cleared_ns'] is None for p in self.state['incidents']):
                return error(409, 'INCIDENT_OPEN')
            row.update(state='APPROVED' if body['approve'] else 'REJECTED', decided_by=actor, decided_ns=now)
            if body['approve']:
                policy = {'policy_revision': row['policy_revision'], 'stage': row['to_stage'],
                          'rig_revision': row['rig_revision'], 'calibration_revision': row['calibration_revision']}
                self.state['policies'] = [p for p in self.state['policies'] if p['policy_revision'] != row['policy_revision']] + [policy]
            return reply(row)
        if action == '/incidents':
            if not isinstance(body.get('description'), str) or not body['description'].strip():
                return error(422, 'INVALID_REQUEST')
            row = {'incident_id': f'sample-incident-{len(self.state["incidents"]) + 1}', 'description': body['description'],
                   'reported_by': actor, 'reported_ns': now, 'cleared_ns': None, 'cleared_by': None}
            self.state['incidents'].append(row)
            for window in self.state['windows']:
                window.update(active=False, closed_ns=now)
            return reply(row)
        match = re.fullmatch('/incidents/([^/]+)/clear', action)
        if match:
            row = next((p for p in self.state['incidents'] if p['incident_id'] == match[1]), None)
            if row is None:
                return error(404, 'INCIDENT_NOT_FOUND')
            if row['reported_by'] == actor:
                return error(403, 'APPROVER_MUST_DIFFER_FROM_PROPOSER')
            if row['cleared_ns'] is not None:
                return error(409, 'INCIDENT_ALREADY_CLEARED')
            row.update(cleared_by=actor, cleared_ns=now)
            return reply(row)
        if action == '/confirmations':
            if body.get('reason') not in RULES['reasons']:
                return error(422, 'UNKNOWN_REASON')
            row = {**body, 'confirmation_id': f'sample-confirmation-{len(self.state["confirmations"]) + 1}',
                   'created_by': actor, 'created_ns': now, 'resolution': None, 'evidence': body.get('evidence', {})}
            self.state['confirmations'].append(row)
            return reply(row)
        match = re.fullmatch('/confirmations/([^/]+)/resolve', action)
        if match:
            row = next((p for p in self.state['confirmations'] if p['confirmation_id'] == match[1]), None)
            if row is None:
                return error(404, 'CONFIRMATION_NOT_FOUND')
            if row['resolution'] is not None:
                return error(409, 'CONFIRMATION_ALREADY_RESOLVED')
            if body.get('resolution') not in RULES['resolutions']:
                return error(422, 'INVALID_REQUEST')
            row.update(resolution=body['resolution'], resolved_by=actor, resolved_ns=now)
            return reply(row)
        return None
