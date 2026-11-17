"""Sample arm AI proposals and skill states: 10 labelled cases, no real endpoint and no command authority.

Served read-only at GET /api/fleet/arm-proposals; the only write is POST .../{id}/admit, which in the sample only moves
the sample case. The proposer never approves their own proposal (AI and Assistant proposals included). Endpoint names are
provisional until the contract ADR (plan 2026-11-14-rosy-vla-decision-ai-command.md, C2). The shape is the contract in
shared/web/sample-data.js (armAiCaseProblems): candidates carry no coordinates, joints or executor choice.
"""
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from response import error, reply

LIVE_ID = 'arm-ai-2'  # the case the dev-panel events (/__dev/advance, flow arm_ai) move
WAITING = ('proposed', 'waiting_approval', 'fallback_proposed')


def _digest(case):
    return hashlib.sha256(f"{case['id']}|{case['lifecycle']}|{case.get('step')}|{case['generation']}".encode()).hexdigest()[:16]


class ArmAI:
    def __init__(self):
        raw = json.loads((Path(__file__).parent / 'fixtures/arm-ai.json').read_text(encoding='utf-8'))
        self.label = raw['label']
        self.initial = {case['id']: case for case in raw['cases']}
        self.cases = {}
        for key, case in self.initial.items():
            self.cases[key] = deepcopy(case)
            self.cases[key]['generation'] = 1
            self.cases[key]['digest'] = _digest(self.cases[key])

    def _touch(self, case):
        case['generation'] += 1
        case['digest'] = _digest(case)

    def handle(self, method, path, body, actor='sample'):
        if (method, path) == ('GET', '/arm-proposals'):
            return reply({'sample': True, 'label': self.label, 'cases': list(self.cases.values())})
        match = re.fullmatch('/arm-proposals/([^/]+)/admit', path)
        if method != 'POST' or not match:
            return None
        case = self.cases.get(match[1])
        if case is None:
            return error(404, 'UNKNOWN_PROPOSAL')
        if body.get('expected_proposal_digest') != case['digest'] or body.get('expected_generation') != case['generation']:
            return error(409, 'PROPOSAL_CHANGED')
        if case['lifecycle'] not in WAITING:
            return error(409, 'PROPOSAL_NOT_WAITING')
        if actor in (case['requested_by'], case.get('proposed_by')):
            case['approval_attempt'] = {'by': actor, 'result': 'refused', 'reason': '제안자는 자기 제안을 승인할 수 없습니다'}
            return error(403, 'PROPOSER_CANNOT_APPROVE')
        case['lifecycle'] = 'approved'
        case['approval_attempt'] = {'by': actor, 'result': 'accepted', 'reason': ''}
        self._touch(case)
        return reply(case)

    def advance(self, event):
        case = self.cases[LIVE_ID]
        state = case['lifecycle']
        if event == 'propose':
            fresh = deepcopy(self.initial[LIVE_ID])
            fresh['generation'] = case['generation']
            self.cases[LIVE_ID] = case = fresh
        elif event == 'admit' and state in WAITING:
            case['lifecycle'] = 'approved'
        elif event == 'step' and state == 'approved':
            case.update(lifecycle='running', step={'n': 1, 'of': 5}, guard='ok')
        elif event == 'step' and state == 'running':
            if case['step']['n'] < case['step']['of']:
                case['step'] = {**case['step'], 'n': case['step']['n'] + 1}
            else:
                case.update(lifecycle='measured_success', measured='verify_placed')
        elif event == 'hold' and state in ('approved', 'running'):
            case.update(lifecycle='stopped', guard='hold', cause='owner가 HOLD 했습니다. 해제는 사람만 합니다')
        elif event == 'fail' and state == 'running':
            case.update(lifecycle='measured_failure', guard='ok', cause='놓임 확인에서 목표 칸 밖에 놓였습니다')
        elif event == 'timeout' and state == 'running':
            case.update(lifecycle='timed_out', guard='hold', cause='리스가 만료되어 HOLD 되었습니다')
        elif event == 'fallback' and state in ('measured_failure', 'timed_out'):  # a stop never falls back; this is a NEW proposal
            case.update(lifecycle='fallback_proposed', executor='ik_chunk', supersedes=case['id'], guard='ok')
            case.pop('cause', None)
            case.pop('step', None)
        else:
            raise ValueError('arm_ai transition rejected')
        self._touch(case)
