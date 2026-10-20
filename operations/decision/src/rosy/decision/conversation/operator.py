"""Console-specific read-only model input; Discord v1 identity stays unchanged."""
from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from core_common.protocol.assistant import AssistantFact
from .codec import MODEL, MODEL_DIGEST, Strict, checked_answer, digest
from .preprocessing import InferenceUsage, control_issue, prepare


class OperatorProfile(Strict):
    profile_id: Literal['qwen-operator-readonly'] = 'qwen-operator-readonly'
    revision: Literal['d831-preprocessing-v1'] = 'd831-preprocessing-v1'
    model_id: Literal[MODEL] = MODEL
    model_digest: Literal[MODEL_DIGEST] = MODEL_DIGEST
    protocol: Literal['rosy-operator-v1'] = 'rosy-operator-v1'


def operator_policy(source_commit):
    return {'schema':'rosy.operator-policy/1', 'source_commit':source_commit,
            'profile_hash':digest(OperatorProfile().model_dump()), 'authority':'read_only',
            'max_calls':1, 'max_cost_usd':0}


class OperatorScope(Strict):
    source: Literal['console'] = 'console'
    principal_id: str = Field(min_length=1, max_length=96)
    conversation_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,96}$')


class OperatorTurn(Strict):
    question: str = Field(min_length=1, max_length=2000)
    response: str = Field(min_length=1, max_length=1000)


class OperatorInput(Strict):
    schema_version: Literal[1] = 1
    scope: OperatorScope
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,96}$')
    question: str = Field(min_length=1, max_length=2000)
    locale: Literal['ko-KR', 'en-US'] = 'ko-KR'
    selected_robot_id: str | None = None
    observed_at: FiniteFloat
    facts: list[AssistantFact] = Field(max_length=64)
    history: list[OperatorTurn] = Field(default_factory=list, max_length=4)

    @property
    def digest(self):
        return digest(self.model_dump())

    @model_validator(mode='after')
    def unique_facts(self):
        if len({f.ref for f in self.facts}) != len(self.facts):
            raise ValueError('ASSISTANT_FACT_DUPLICATE')
        return self

    @property
    def environment(self):
        return {'robots':[{'robot_id':f.ref[6:]} for f in self.facts if f.ref.startswith('robot:')], 'map':None}


class OperatorAnswer(Strict):
    kind: Literal['CHAT', 'STATUS', 'CAUSE', 'CLARIFY', 'CONTROL', 'REFUSE']
    response: str = Field(min_length=1, max_length=1000)
    evidence_refs: list[str] = Field(max_length=64)
    usage: InferenceUsage | None = Field(default=None, exclude=True)


def checked_operator_answer(value, question):
    answer = OperatorAnswer.model_validate(value)
    if not set(answer.evidence_refs) <= {f.ref for f in question.facts}:
        raise ValueError('ASSISTANT_UNKNOWN_EVIDENCE')
    if answer.kind == 'CONTROL' and control_issue(prepare(question)):
        return OperatorAnswer(kind='CLARIFY', response='Classified', evidence_refs=[], usage=answer.usage)
    if answer.kind == 'CHAT':
        checked_answer({'kind':'CHAT', 'response':answer.response, 'evidence_refs':answer.evidence_refs,
                        'intent':None, 'review_required':False}, question)
    return answer
