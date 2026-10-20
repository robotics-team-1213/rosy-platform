"""Independent conversation contract; user text and model output are untrusted."""
import hashlib
import json
import math
import re
from typing import Literal

from core_common.intent import interpret
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator
from rosy.decision.deliberation import canonical
from .preprocessing import DISCORD_REVISION, VERSION, InferenceUsage, control_issue, prepare, resolve_reference


MODEL = 'qwen3-vl:8b-instruct'
MODEL_DIGEST = '0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319'


def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class Profile(Strict):
    profile_id: Literal['qwen-conversation-primary'] = 'qwen-conversation-primary'
    revision: str = Field(pattern=r'^d728-[a-z0-9-]{1,40}$')
    model_id: Literal[MODEL] = MODEL
    model_digest: Literal[MODEL_DIGEST] = MODEL_DIGEST
    protocol: Literal['rosy-conversation-v1'] = 'rosy-conversation-v1'
    context_length: Literal[8192] = 8192
    timeout_s: Literal[30] = 30
    max_calls: Literal[1] = 1
    max_cost_usd: Literal[0] = 0


def source_policy(source_commit, profile):
    policy = {'schema': 'rosy.conversation-policy/1', 'source_commit': source_commit,
            'profile_hash': digest(profile.model_dump()), 'authority': 'proposal_only',
            'output_kinds': ['CHAT', 'STATUS', 'CLARIFY', 'CONTROL', 'REFUSE']}
    if profile.revision == DISCORD_REVISION:
        policy['preprocessing_version'] = VERSION
    return policy


class History(Strict):
    authority: Literal['model_proposal_only'] = 'model_proposal_only'
    execution_state: Literal['NOT_DISPATCHED'] = 'NOT_DISPATCHED'
    accepted_execution_context: None = None
    request_id: str = Field(min_length=1, max_length=96)
    principal_id: str = Field(min_length=1, max_length=96)
    author_id: str = Field(pattern=r'^[0-9]{17,20}$')
    guild_id: str = Field(pattern=r'^[0-9]{17,20}$')
    channel_id: str = Field(pattern=r'^[0-9]{17,20}$')
    question: str = Field(min_length=1, max_length=2000)
    content_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    answered_at: FiniteFloat
    environment_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    kind: Literal['CHAT', 'STATUS', 'CLARIFY', 'CONTROL', 'REFUSE']
    intent: dict | None
    response: str | None = Field(default=None, max_length=1000)


class AcceptedContext(Strict):
    authority: Literal['fleet_execution_selection'] = 'fleet_execution_selection'
    execution_state: Literal['COMPLETED'] = 'COMPLETED'
    principal_id: str = Field(min_length=1, max_length=96)
    author_id: str = Field(pattern=r'^[0-9]{17,20}$')
    guild_id: str = Field(pattern=r'^[0-9]{17,20}$')
    channel_id: str = Field(pattern=r'^[0-9]{17,20}$')
    request_id: str = Field(min_length=1, max_length=96)
    task_id: str = Field(min_length=1, max_length=96)
    robot_id: str = Field(min_length=1, max_length=96)
    place_id: str = Field(min_length=1, max_length=96)
    catalog_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    evidence_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    generation: int = Field(ge=0)
    expires_at: FiniteFloat
    boot_id: str | None = Field(default=None, max_length=96)
    run_id: str | None = Field(default=None, max_length=96)
    attempt_id: str | None = Field(default=None, max_length=96)
    owner_generation: int | None = Field(default=None, ge=0)


class ConversationInput(Strict):
    schema_version: Literal[1] = 1
    request_id: str = Field(min_length=1, max_length=96)
    principal_id: str = Field(min_length=1, max_length=96)
    author_id: str = Field(pattern=r'^[0-9]{17,20}$')
    guild_id: str = Field(pattern=r'^[0-9]{17,20}$')
    channel_id: str = Field(pattern=r'^[0-9]{17,20}$')
    content_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    question: str = Field(min_length=1, max_length=2000)
    observed_at: FiniteFloat
    environment: dict
    history: list[History] = Field(max_length=4)
    accepted_execution_context: dict | None = None

    @property
    def digest(self):return digest(self.model_dump())

    @model_validator(mode='after')
    def history_scope(self):
        for h in self.history:
            if (any(getattr(h, k) != getattr(self, k) for k in
                    ('principal_id', 'author_id', 'guild_id', 'channel_id'))
                    or not 0 <= self.observed_at-h.answered_at <= 120
                    or h.environment_hash != digest(self.environment)):
                raise ValueError('CONVERSATION_HISTORY_SCOPE_CHANGED')
        if bounded_environment(self.environment) != self.environment:
            raise ValueError('CONVERSATION_ENVIRONMENT_NOT_BOUNDED')
        if self.accepted_execution_context is not None:
            context = AcceptedContext.model_validate(self.accepted_execution_context).model_dump()
            if (context != self.accepted_execution_context or context['request_id'] == self.request_id
                    or any(context[k] != getattr(self, k) for k in
                           ('principal_id', 'author_id', 'guild_id', 'channel_id'))
                    or not 0 < context['expires_at']-self.observed_at <= 120
                    or context['catalog_hash'] != digest({'robot_ids':sorted(r['robot_id'] for r in
                        self.environment['robots']), 'map':self.environment['map'],
                        'work_catalog':self.environment['work_catalog']})
                    or context['robot_id'] not in {r['robot_id'] for r in self.environment['robots']}
                    or context['place_id'] not in {p['id'] for p in (self.environment['map'] or {}).get('places', [])}):
                raise ValueError('CONVERSATION_ACCEPTED_CONTEXT_CHANGED')
        return self


def bounded_environment(raw):
    rows = raw.get('robots')
    if type(rows) is not list or len(rows) > 15:raise ValueError('CONVERSATION_ROBOT_LIMIT')
    robots = []
    for row in rows:
        if (type(row) is not dict or type(row.get('robot_id')) is not str or
                re.fullmatch('[A-Za-z0-9_.:-]{1,96}', row['robot_id']) is None
                or row.get('online') is not None and type(row['online']) is not bool):
            raise ValueError('CONVERSATION_ROBOT_INVALID')
        state = row.get('state') if row.get('online') is True else None
        state = state if type(state) is dict else row
        safety, line = state.get('safety') or {}, state.get('line_follow') or {}
        entry = {'robot_id':row['robot_id'], 'online':row.get('online'), 'mode':state.get('mode'),
            'estop':safety.get('estop', state.get('estop')),
            'line_state':line.get('state', state.get('line_state'))}
        if any(entry[k] is not None and (type(entry[k]) is not str or
                re.fullmatch('[A-Za-z0-9_.:-]{1,96}', entry[k]) is None) for k in ('mode', 'line_state')):
            raise ValueError('CONVERSATION_ROBOT_INVALID')
        if entry['estop'] is not None and type(entry['estop']) is not bool:
            raise ValueError('CONVERSATION_ROBOT_INVALID')
        robots.append(entry)
    if len({r['robot_id'] for r in robots}) != len(robots):raise ValueError('CONVERSATION_ROBOT_DUPLICATE')
    robots.sort(key=lambda r:r['robot_id'])
    map_data = raw.get('map')
    places = [] if map_data is None else map_data['places']
    if type(places) is not list or len(places) > 64:raise ValueError('CONVERSATION_MAP_LIMIT')
    selected = []
    for p in places:
        if (type(p) is not dict or not {'id', 'name', 'x', 'y'} <= set(p) or set(p)-{'id','name','x','y','yaw'}
                or any(type(p[k]) is not str or not 1 <= len(p[k]) <= 96 or
                       re.search(r'[\x00-\x1f<>@]', p[k]) for k in ('id', 'name'))
                or any(type(p[k]) not in (int, float) or not math.isfinite(p[k]) or abs(p[k]) > 100000 for k in ('x', 'y'))):
            raise ValueError('CONVERSATION_PLACE_INVALID')
        if p.get('yaw') is not None and (type(p['yaw']) not in (int, float) or
                not math.isfinite(p['yaw']) or abs(p['yaw']) > math.pi):
            raise ValueError('CONVERSATION_PLACE_INVALID')
        selected.append(p)
    if len({p['id'] for p in selected}) != len(selected):raise ValueError('CONVERSATION_PLACE_DUPLICATE')
    if map_data is not None and (set(map_data)-{'version', 'sha256', 'places', 'places_complete'}
            or not {'version', 'sha256', 'places'} <= set(map_data)
            or type(map_data.get('places_complete', True)) is not bool
            or type(map_data['version']) is not int or map_data['version'] < 1
            or re.fullmatch('[0-9a-f]{64}', map_data['sha256']) is None):
        raise ValueError('CONVERSATION_MAP_REVISION_REQUIRED')
    work = raw.get('work_catalog', [])
    if type(work) is not list or len(work) > 32 or any(type(w) is not str or
            re.fullmatch('[A-Za-z0-9_.:-]{1,96}', w) is None for w in work):
        raise ValueError('CONVERSATION_CATALOG_INVALID')
    return {'robots': robots, 'map': None if map_data is None else
            {**map_data, 'places': sorted(selected, key=lambda p:p['id'])}, 'work_catalog': sorted(set(work))}


def conversation_input(receipt, snapshot, bot_id, history=(), *, now, accepted_execution_context=None):
    if hashlib.sha256(receipt['content'].encode()).hexdigest() != receipt['content_hash']:
        raise ValueError('CONVERSATION_ORIGINAL_CHANGED')
    question = re.sub(r'<@!?'+re.escape(bot_id)+r'>', '', receipt['content']).strip()
    return ConversationInput(**{k:receipt[k] for k in ('request_id', 'principal_id', 'author_id',
        'guild_id', 'channel_id', 'content_hash')}, question=question, observed_at=now,
        environment=bounded_environment(snapshot), history=list(history),
        accepted_execution_context=accepted_execution_context)


class Answer(Strict):
    kind: Literal['CHAT', 'STATUS', 'CLARIFY', 'CONTROL', 'REFUSE']
    response: str = Field(min_length=1, max_length=1000)
    intent: dict | None
    evidence_refs: list[str] = Field(max_length=32)
    review_required: bool
    reason: Literal['MISSING_TARGET', 'MISSING_ACTION', 'AMBIGUOUS_REFERENCE', 'UNSUPPORTED',
                    'SAFETY', 'CONFLICT', 'CREDENTIALS'] | None = None
    usage: InferenceUsage | None = Field(default=None, exclude=True)

    @model_validator(mode='after')
    def proposal_only(self):
        if (self.kind == 'CONTROL') != (self.intent is not None):
            raise ValueError('CONTROL_PROPOSAL_REQUIRED')
        if self.kind in ('CLARIFY', 'REFUSE') and self.reason is None:
            raise ValueError('CONVERSATION_TYPED_REASON_REQUIRED')
        if re.search(r'[@<>\x00-\x08]|https?://|(?:token|password|api[_ -]?key)\s*[:=]|[A-Za-z0-9_=-]{40,}', self.response, re.I):
            raise ValueError('UNSAFE_CONVERSATION_REPLY')
        return self


class SemanticStep(Strict):
    verb: Literal['navigate','home','cancel','stop','move','follow','follow_cancel','dock','undock',
                  'formation_start','formation_stop','formation_resume','estop']
    robot_id: str | None
    place_id: str | None
    parameters_json: str = Field(max_length=1000)


class SemanticAnswer(Strict):
    kind: Literal['CHAT', 'STATUS', 'CLARIFY', 'CONTROL', 'REFUSE']
    response: str = Field(min_length=1, max_length=1000)
    steps: list[SemanticStep] = Field(max_length=8)
    evidence_refs: list[str] = Field(max_length=32)
    review_required: bool
    reason: Literal['MISSING_TARGET', 'MISSING_ACTION', 'AMBIGUOUS_REFERENCE', 'UNSUPPORTED',
                    'SAFETY', 'CONFLICT', 'CREDENTIALS'] | None


def semantic_answer(value, question, *, preprocessing=False):
    semantic = SemanticAnswer.model_validate(value)
    if preprocessing and semantic.kind == 'CONTROL':
        issue = control_issue(prepare(question), steps=len(semantic.steps))
        if issue:
            return Answer(kind='CLARIFY', response='대상과 단일 동작을 다시 확인해 주세요.',
                          intent=None, evidence_refs=[], review_required=False, reason=issue)
    steps = []
    for step in semantic.steps:
        parameters = json.loads(step.parameters_json)
        if type(parameters) is not dict or {'do','robot','waypoint','steps'} & set(parameters):
            raise ValueError('CONVERSATION_PARAMETERS_REFUSED')
        current = {'do':step.verb, **parameters}
        robot, place = step.robot_id, step.place_id
        if preprocessing:
            try:
                robot = resolve_reference(robot, 'robot', question.environment)
                place = resolve_reference(place, 'place', question.environment)
            except ValueError:
                return Answer(kind='CLARIFY', response='등록된 로봇과 장소를 다시 지정해 주세요.',
                    intent=None, evidence_refs=[], review_required=False, reason='AMBIGUOUS_REFERENCE')
        if robot is not None:current['robot'] = robot
        if place is not None:current['waypoint'] = place
        steps.append(current)
    if (semantic.kind == 'CONTROL') != bool(steps):raise ValueError('CONTROL_SEMANTIC_STEPS_REQUIRED')
    return checked_answer({'kind':semantic.kind,'response':semantic.response,'intent':
        None if not steps else steps[0] if len(steps) == 1 else {'steps':steps},
        'evidence_refs':semantic.evidence_refs,'review_required':semantic.review_required,'reason':semantic.reason},
        question, preprocessing=preprocessing)


def answer_schema():
    return SemanticAnswer.model_json_schema()


def checked_answer(value, question, *, preprocessing=False):
    answer = Answer.model_validate(value)
    robots = {r['robot_id'] for r in question.environment['robots']}
    places = {} if question.environment['map'] is None else {p['id']:p for p in question.environment['map']['places']}
    allowed = {'robot:'+r for r in robots} | {'place:'+p for p in places}
    if not set(answer.evidence_refs) <= allowed:raise ValueError('CONVERSATION_EVIDENCE_UNKNOWN')
    if preprocessing and answer.intent is not None:
        prepared = prepare(question)
        calls = interpret(answer.intent)
        issue = control_issue(prepared, steps=len(calls))
        if not issue and prepared.uses_context:
            context = question.accepted_execution_context
            if any(call.verb != 'navigate' or call.robot != context['robot_id']
                   or call.body.get('waypoint') != context['place_id'] for call in calls):
                issue = 'AMBIGUOUS_REFERENCE'
        if issue:
            return Answer(kind='CLARIFY', response='대상과 단일 동작을 다시 확인해 주세요.', intent=None,
                evidence_refs=[], review_required=False, reason=issue, usage=answer.usage)
    if answer.intent is not None:
        for call in interpret(answer.intent):
            if call.scope == 'robot' and call.robot not in robots:
                raise ValueError('CONVERSATION_REGISTERED_ROBOT_REQUIRED')
            if any(r not in robots for r in ([call.body['target_robot_id']] if 'target_robot_id' in call.body else [])
                    + ([call.body['leader']] if 'leader' in call.body else [])+call.body.get('members', [])):
                raise ValueError('CONVERSATION_REGISTERED_ROBOT_REQUIRED')
            if call.verb == 'navigate' and (call.body.get('waypoint') not in places
                    or set(call.body)-{'waypoint', 'x', 'y', 'yaw'}):
                raise ValueError('CONVERSATION_REGISTERED_PLACE_REQUIRED')
            if call.verb == 'navigate' and any(call.body[k] != places[call.body['waypoint']].get(k)
                    for k in ('x', 'y', 'yaw') if k in call.body):
                raise ValueError('CONVERSATION_REGISTERED_PLACE_CHANGED')
    if answer.kind == 'CHAT' and (answer.evidence_refs or any(r in answer.response for r in robots)
            or re.search(r'온라인|오프라인|작동\s*중|이동\s*완료|정지\s*완료|연결되어|배터리|전압|'
                r'보내겠|보내드|이동하겠|정지하겠|실행하겠|현재.*(?:로봇|상태)|즉시.*이동|정상.*이동|'
                r'\b(?:online|offline|battery|voltage|healthy|executed|completed|stopped|connected|moving)\b',
                answer.response, re.I)):
        raise ValueError('CHAT_DEVICE_FACTS_REFUSED')
    return answer


def reply(answer, question, *, preprocessing=False):
    if answer.kind in ('CLARIFY', 'REFUSE'):
        reasons = {'MISSING_TARGET':'어느 로봇과 등록된 장소를 말하는지 알려주세요.',
            'MISSING_ACTION':'원하는 동작을 구체적으로 말씀해 주세요.',
            'AMBIGUOUS_REFERENCE':'이 대화에서 대상을 확정할 수 없습니다. 로봇과 장소를 다시 지정해 주세요.',
            'UNSUPPORTED':'현재 등록된 조종 범위에서 처리할 수 없습니다. 지원하는 동작으로 구체화해 주세요.',
            'SAFETY':'안전 규칙을 무시하거나 비상정지를 자동 해제하는 요청은 처리할 수 없습니다.',
            'CONFLICT':'요청과 현재 근거가 충돌하여 보류했습니다. 대상과 동작을 구체적으로 알려주세요.',
            'CREDENTIALS':'인증 정보는 대화에서 제공하지 않습니다.'}
        return reasons[answer.reason]
    if answer.kind == 'STATUS':
        rows = question.environment['robots']
        if preprocessing and answer.evidence_refs:
            rows = [row for row in rows if 'robot:'+row['robot_id'] in answer.evidence_refs]
            if not rows and question.environment['robots']:
                return '상태를 조회할 로봇을 지정해 주세요.'
        return '현재 관제에서 확인한 상태입니다.\n'+'\n'.join(
            r['robot_id']+' · '+('상태 미확인' if r['online'] is None else '온라인' if r['online'] else '오프라인')
            for r in rows) if rows else '등록된 로봇이 없습니다.'
    if answer.kind == 'CONTROL':
        verbs = [c.verb for c in interpret(answer.intent)]
        return '요청을 이해했습니다. 조종 제안을 기록했으며 권한·지도·기기 안전 검증이 필요합니다.'+(
            '\nstop은 비상정지를 잠그는 요청입니다. 해제는 자동으로 하지 않습니다.' if 'stop' in verbs else '')
    return answer.response
