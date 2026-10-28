"""Scoped independent review requests; model opinions remain untrusted proposals."""
from dataclasses import asdict, dataclass
import hashlib
import json

from . import Problem, canonical, identifier, opinion
from .contracts.profiles import ModelProfile, AdapterCapabilities, bind_profile
from .cooperation_schedule import number


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


@dataclass(frozen=True)
class ReviewReceipt:
    profile_key: str
    request_hash: str
    call_id: str
    opinion_json: str
    cost_usd: float

    def validate(self, request, provider):
        if (self.profile_key != provider.profile_key or self.request_hash != request.digest
                or self.call_id != provider.call_id(request)):
            raise ValueError('REVIEW_RECEIPT_CHANGED')
        number(self.cost_usd)
        if self.cost_usd > provider.profile.max_cost_usd:
            raise ValueError('REVIEW_COST_EXCEEDED')
        return opinion(request.problem, json.loads(self.opinion_json))


class CooperationProvider:
    """Explicit isolated transport port; never adapts a v2 Judgment into a v1 opinion."""

    def __init__(self, profile, adapter, exchange, *, prompt_revision):
        if (type(profile) is not ModelProfile or type(adapter) is not AdapterCapabilities
                or profile.role not in ('primary', 'reviewer') or not callable(exchange)
                or not callable(getattr(exchange, 'cancel', None))):
            raise ValueError('EXPLICIT_REVIEW_TRANSPORT_REQUIRED')
        self.profile, self.adapter, self.exchange = profile, adapter, exchange
        self.prompt_revision = identifier(prompt_revision)

    @property
    def profile_id(self):
        return self.profile.profile_id

    @property
    def profile_key(self):
        return hashlib.sha256(canonical({'profile': asdict(self.profile), 'adapter': asdict(self.adapter),
                                         'prompt_revision': self.prompt_revision}).encode()).hexdigest()

    def call_id(self, request):
        return hashlib.sha256(canonical([request.digest, self.profile_key]).encode()).hexdigest()

    async def __call__(self, request, remaining, *, budget_usd):
        bind_profile(request.problem, self.profile, self.adapter, required_modalities=('text',))
        role = 'proposal' if self.profile.role == 'primary' else 'critique'
        if request.role != role or not 0 < number(remaining) <= self.profile.timeout_s:
            raise ValueError('REVIEW_ROLE_OR_TIME_CHANGED')
        if not 0 <= number(budget_usd) <= self.profile.max_cost_usd:
            raise ValueError('REVIEW_BUDGET_EXCEEDED')
        key, call_id = self.profile_key, self.call_id(request)
        body = {**request.body(), 'schema_version': 'cooperation-v1', 'request_hash': request.digest,
                'profile_key': key, 'prompt_revision': self.prompt_revision, 'call_id': call_id,
                'budget_usd': budget_usd}
        canonical(body)
        response = await self.exchange(body, remaining, budget_usd=budget_usd)
        if (type(response) is not dict
                or set(response) != {'request_hash', 'profile_key', 'cost_usd', 'opinion'}
                or response['request_hash'] != request.digest or response['profile_key'] != key
                or self.profile_key != key or len(canonical(response).encode()) > self.profile.max_output_bytes
                or number(response['cost_usd']) > budget_usd):
            raise ValueError('INVALID_REVIEW_RESPONSE')
        checked = opinion(request.problem, response['opinion'])
        return ReviewReceipt(key, request.digest, call_id, canonical(checked), response['cost_usd'])

    async def cancel(self, call_id):
        return await self.exchange.cancel(call_id) is True


from .cooperation_runtime import CooperationSupervisor
