"""Read existing poll evidence for one incident; never gather, invoke models or command CORE."""

from dataclasses import dataclass
import json
import time

from rosy.decision.deliberation import Problem
from rosy_situation.assessment import Assessment
from rosy_situation.snapshot_assessment import POLICY


@dataclass(frozen=True)
class IncidentReadback:
    payload_json: str

    @property
    def payload(self):
        return json.loads(self.payload_json)


class IncidentObservationPort:
    def __init__(self, board, *, human_owned, clock=time.time):
        if not callable(human_owned):
            raise ValueError('HUMAN_OWNERSHIP_UNAVAILABLE')
        self._board, self._human_owned, self._clock = board, human_owned, clock

    def read(self, problem, step, *, snapshot):
        if not isinstance(problem, Problem) or problem.domain != 'line_follow':
            raise ValueError('INCIDENT_BACKEND_UNAVAILABLE')
        if (type(step) is not dict or set(step) != {'tool_name', 'arguments', 'evidence_ids'}
                or step['tool_name'] != 'get_incident_status' or step['arguments'] != {}
                or type(step['arguments']) is not dict):
            raise ValueError('INCIDENT_TOOL_NOT_ALLOWED')
        evidence = step['evidence_ids']
        if (type(evidence) is not list or not evidence or len(evidence) > 16
                or any(type(ref) is not str or ref not in problem.evidence_ids for ref in evidence)
                or len(set(evidence)) != len(evidence)):
            raise ValueError('INCIDENT_EVIDENCE_SCOPE_MISMATCH')
        rows = snapshot.get('robots') if type(snapshot) is dict else None
        if type(rows) is not list:
            raise ValueError('INCIDENT_POLL_UNAVAILABLE')
        matches = [row for row in rows if type(row) is dict and row.get('robot_id') == problem.subject_id]
        if len(matches) != 1 or matches[0].get('online') is not True:
            raise ValueError('INCIDENT_SUBJECT_UNAVAILABLE')
        row = matches[0]
        state = row.get('state')
        if type(state) is not dict or type(state.get('seq')) is not int or state['seq'] < 0:
            raise ValueError('INCIDENT_REVISION_UNAVAILABLE')
        assessment = self._board.intervention_assessment(problem.subject_id)
        now = self._clock()
        if (not isinstance(assessment, Assessment)
                or not assessment.applies_to(assessment.request, now=now, policy_revision=POLICY.revision)):
            raise ValueError('INCIDENT_ASSESSMENT_UNAVAILABLE')
        request = assessment.request
        line = state.get('line_follow')
        stuck = line.get('stuck') if type(line) is dict else None
        if (request.subject_id != problem.subject_id or request.case_id != problem.case_id
                or request.owner != 'core' or type(stuck) is not dict
                or stuck.get('stuck_id') != problem.case_id):
            raise ValueError('INCIDENT_CASE_SCOPE_MISMATCH')
        if request.revision != f"core:{state['seq']}:{state.get('timestamp')}":
            raise ValueError('INCIDENT_POLL_REVISION_MISMATCH')
        try:
            human_owned = self._human_owned(problem.subject_id, problem.case_id)
        except Exception:
            raise ValueError('HUMAN_OWNERSHIP_UNAVAILABLE') from None
        if human_owned is not False:
            raise ValueError('INCIDENT_HUMAN_OWNED')
        if any(item.source != 'core_state' for item in request.evidence):
            raise ValueError('INCIDENT_EVIDENCE_SOURCE_MISMATCH')
        payload = dict(subject_id=request.subject_id, case_id=request.case_id, generation=request.revision,
                       observed_at=min(item.observed_at for item in request.evidence),
                       evidence_ids=[item.reference for item in request.evidence],
                       necessity=assessment.necessity, reason=assessment.reason,
                       policy_revision=assessment.policy_revision,
                       facts={'state': 'blocked' if request.condition == 'blocked' else 'unknown'},
                       action_admissible=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(encoded.encode()) > 4096:
            raise ValueError('INCIDENT_READBACK_TOO_LARGE')
        return IncidentReadback(encoded)
