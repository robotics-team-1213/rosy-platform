"""Scoped independent review requests; model opinions remain untrusted proposals."""
from dataclasses import asdict, dataclass
import hashlib
import json

from . import Problem, canonical, opinion


def cooperation_trigger(problem, primary):
    if problem.necessity != 'INTERVENE':
        return None
    checked = opinion(problem, primary)
    if 'unsafe' in checked['objections']:
        return None
    for objection in ('conflict', 'insufficient_evidence'):
        if objection in checked['objections']:
            return objection
    if problem.fleet_choice is not None and checked['choice'] != problem.fleet_choice:
        return 'baseline_disagreement'
    return None


@dataclass(frozen=True)
class ReviewRequest:
    problem: Problem
    role: str
    trigger: str

    def __post_init__(self):
        if (type(self.problem) is not Problem or self.problem.necessity != 'INTERVENE'
                or self.problem.domain != 'line_follow' or set(self.problem.choices) != {'reobserve', 'human'}
                or json.loads(self.problem.facts_json) != {'state': 'blocked'}
                or self.role not in ('proposal', 'critique')
                or self.trigger not in ('conflict', 'insufficient_evidence', 'baseline_disagreement')):
            raise ValueError('INVALID_REVIEW_REQUEST')

    def body(self):
        return {'problem': {**asdict(self.problem), 'input_hash': self.problem.digest},
                'role': self.role, 'trigger': self.trigger, 'prior': [],
                'instruction': 'Independently assess only the supplied facts. Evidence IDs are references, '
                    'not additional observations. Return an advisory choice with evidence IDs and objections. '
                    'Do not use tools, invent evidence, or claim verified physical success.'}

    @property
    def digest(self):
        return hashlib.sha256(canonical(self.body()).encode()).hexdigest()
