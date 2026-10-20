"""Sample approval ledger for UI development; never issues an execution lease."""
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

    def handle(self, method, path, body):
        base = '/workcells/sample-cell/policy'
        if (method, path) == ('GET', base):
            return reply(self.state)
        if path == base + '/lease' and method == 'POST':
            return error(409, 'NO_ACTIVE_WINDOW')
        return None
