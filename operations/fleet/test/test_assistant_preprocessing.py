"""D-831 preserves submitted text and prevents unsafe candidates becoming commands."""
import copy
import json
import unicodedata

import pytest

from rosy.decision.conversation.operator import OperatorInput, OperatorScope


def question(text, facts=()):
    return OperatorInput(scope=OperatorScope(principal_id='alice', conversation_id='conv'),
        request_id='request', question=text, observed_at=1000., facts=list(facts))


def prepare(text, **kwargs):
    from rosy.decision.conversation.preprocessing import prepare
    return prepare(question(text), **kwargs)


def test_normalization_preserves_raw_quotes_signs_units_and_line_boundaries():
    raw = unicodedata.normalize('NFD', '로봇') + '  r1\t -1.5 m/s\n"A  B"로 보내지 마'
    value = prepare(raw)
    assert value.normalized == '로봇 r1 -1.5 m/s\n"A  B"로 보내지 마'
    assert value.original == raw
    assert question(raw).question == raw


def test_same_normalized_text_never_merges_different_original_requests():
    left, right = prepare('로봇  r1 상태'), prepare('로봇 r1 상태')
    assert left.normalized == right.normalized
    assert left.input_hash != right.input_hash
    assert left.digest != right.digest


def test_registered_place_alias_collision_is_preserved_as_ambiguity():
    catalog = {'robots':[{'robot_id':'r1'}], 'map':{'version':1, 'sha256':'a'*64, 'places':[
        {'id':'east', 'name':'입구', 'x':1., 'y':2.},
        {'id':'west', 'name':'입구', 'x':-1., 'y':2.}]}}
    before = copy.deepcopy(catalog)
    value = prepare('r1을 입구로 보내줘', environment=catalog)
    assert value.ambiguous == ('입구',)
    assert catalog == before
    from rosy.decision.conversation.preprocessing import control_issue
    assert control_issue(value) == 'AMBIGUOUS_REFERENCE'


@pytest.mark.parametrize('text', [
    'r1을 입구로 보내지 마', 'r1을 움직이지 마세요',
    '보내지 말라는 뜻이야', "Don't move r1", 'Do not send r1',
    '만약 r1을 보내면 어떻게 돼?', 'If r1 moves, what happens?',
    '"r1을 움직여"라는 뜻을 설명해', 'Explain "move r1"',
    'r1을 보내줘 그리고 r2는 취소해',
])
def test_nonaffirmative_or_compound_text_cannot_become_control(text):
    from rosy.decision.conversation.preprocessing import control_issue
    assert control_issue(prepare(text)) is not None


def test_parameters_in_quotes_are_not_mistaken_for_quoted_actions():
    from rosy.decision.conversation.preprocessing import control_issue
    assert control_issue(prepare('r1을 "정문"으로 보내줘')) is None
    assert control_issue(prepare('Move r1 to "entrance"')) is None


def test_structured_multiple_steps_are_not_silently_cut_to_one():
    from rosy.decision.conversation.preprocessing import control_issue
    assert control_issue(prepare('r1을 보내줘'), steps=2) == 'CONFLICT'


def test_status_with_negative_scope_is_still_a_status_answer():
    from rosy.decision.conversation.operator import checked_operator_answer
    value = checked_operator_answer(dict(kind='STATUS', response='Classified', evidence_refs=[]),
                                    question('r1 말고 r2 상태 알려줘'))
    assert value.kind == 'STATUS'


def test_console_rechecks_a_forged_positive_classification_of_negation():
    from rosy.decision.conversation.operator import checked_operator_answer
    value = checked_operator_answer(dict(kind='CONTROL', response='Classified', evidence_refs=[]),
                                    question('r1을 움직이지 마'))
    assert value.kind == 'CLARIFY'


def test_prompt_context_omits_auth_ids_but_preserves_question_and_facts():
    from core_common.protocol.assistant import AssistantFact
    from rosy.decision.conversation.preprocessing import prepare
    q = question('r1 현재 상태', [AssistantFact(ref='robot:r1', observed_at=1000., text='r1 online')])
    value = prepare(q)
    assert value.context['question'] == q.question
    assert value.context['facts'] == [f.model_dump() for f in q.facts]
    assert 'scope' not in value.context and 'request_id' not in value.context
    assert value.context['preparation']['input_hash'] == q.digest


def test_usage_reserves_generation_budget_and_rejects_forged_or_invalid_counts():
    from rosy.decision.conversation.preprocessing import InferenceUsage
    data = dict(input_tokens=100, output_tokens=10, elapsed_ms=12., preparation_hash='a'*64)
    assert InferenceUsage(**data).input_tokens == 100
    for change in [{'input_tokens':True}, {'input_tokens':7169}, {'output_tokens':1025},
                   {'elapsed_ms':float('nan')}, {'preparation_hash':'not-a-hash'}]:
        with pytest.raises(ValueError):
            InferenceUsage(**(data | change))


def inference_exchange(captured, *, input_tokens=100, output_tokens=10, extra=None):
    def exchange(path, body, remaining):
        if path == '/api/ps':
            return {}
        captured.append(body)
        return dict(model='qwen3-vl:8b-instruct', done=True, done_reason='stop',
            prompt_eval_count=input_tokens, eval_count=output_tokens,
            message=dict(role='assistant', content=json.dumps(
                dict(kind='CHAT', response='Classified', evidence_refs=[]) | (extra or {}))))
    return exchange


def test_operator_broker_uses_prepared_copy_and_records_actual_usage(monkeypatch):
    from deploy.ai_pc import operator_broker
    from rosy.decision.conversation.operator import OperatorProfile, checked_operator_answer
    from rosy.decision.conversation.preprocessing import prepare
    q = question(unicodedata.normalize('NFD', '안녕')+'  r1')
    seen = []
    monkeypatch.setattr(operator_broker, 'loaded', lambda _:None)
    monkeypatch.setattr(operator_broker, 'exchange', inference_exchange(seen))
    output = operator_broker.execute(q, OperatorProfile(), 30)
    answer = checked_operator_answer(output, q)
    assert answer.usage is not None and answer.usage.input_tokens == 100
    assert answer.usage.output_tokens == 10 and answer.usage.preparation_hash == prepare(q).digest
    assert 'usage' not in answer.model_dump()
    assert 'usage' not in seen[0]['format']['properties']
    content = seen[0]['messages'][1]['content']
    context, latest = content.split('\nLATEST USER MESSAGE:\n')
    assert json.loads(context)['question'] == q.question
    assert 'scope' not in json.loads(context)
    assert latest == '안녕 r1'
    assert prepare(q).original == q.question


def test_model_cannot_supply_its_own_usage_and_generation_reserve_is_enforced(monkeypatch):
    from deploy.ai_pc import operator_broker
    from rosy.decision.conversation.operator import OperatorProfile
    monkeypatch.setattr(operator_broker, 'loaded', lambda _:None)
    monkeypatch.setattr(operator_broker, 'exchange', inference_exchange([], extra={
        'usage':dict(input_tokens=1, output_tokens=1, elapsed_ms=0., preparation_hash='a'*64)}))
    with pytest.raises(ValueError):
        operator_broker.execute(question('안녕'), OperatorProfile(), 30)
    monkeypatch.setattr(operator_broker, 'exchange', inference_exchange([], input_tokens=7169))
    with pytest.raises(ValueError):
        operator_broker.execute(question('안녕'), OperatorProfile(), 30)


def semantic_question(text, *, duplicate=False):
    from rosy.decision.conversation.codec import ConversationInput
    return ConversationInput(request_id='request', principal_id='alice', author_id='1'*17,
        guild_id='2'*17, channel_id='3'*17, content_hash='a'*64, question=text, observed_at=1000.,
        environment={'robots':[dict(robot_id='r1', online=True, mode='IDLE', estop=False, line_state='OFF')],
            'map':dict(version=1, sha256='b'*64, places=[dict(id='east', name='입구', x=1., y=2.)] +
                ([dict(id='west', name='입구', x=-1., y=2.)] if duplicate else [])), 'work_catalog':[]}, history=[])


def navigation_answer(*, steps=1, place='입구'):
    return dict(kind='CONTROL', response='이동 제안입니다.', steps=[dict(verb='navigate', robot_id='r1',
        place_id=place, parameters_json='{}') for _ in range(steps)], evidence_refs=[], review_required=False, reason=None)


def test_new_semantic_profile_resolves_unique_names_and_clarifies_collisions_or_multiple_actions():
    from rosy.decision.conversation.codec import semantic_answer
    q = semantic_question('r1을 입구로 보내줘')
    value = semantic_answer(navigation_answer(), q, preprocessing=True)
    assert value.intent == {'do':'navigate', 'robot':'r1', 'waypoint':'east'}
    assert semantic_answer(navigation_answer(), semantic_question(q.question, duplicate=True),
                           preprocessing=True).kind == 'CLARIFY'
    assert semantic_answer(navigation_answer(steps=2, place='east'), q, preprocessing=True).kind == 'CLARIFY'


def test_legacy_semantic_profile_still_requires_canonical_ids():
    from rosy.decision.conversation.codec import semantic_answer
    with pytest.raises(ValueError):
        semantic_answer(navigation_answer(), semantic_question('r1을 입구로 보내줘'))


def test_model_prompt_retains_evaluated_question_but_omits_private_provenance():
    from core_common.protocol.assistant import AssistantFact
    from rosy.decision.conversation.preprocessing import prepare
    q = question('r1 상태', [AssistantFact(ref='robot:r1', observed_at=1000., text='r1 online')])
    value = prepare(q)
    prompt = json.loads(value.prompt_json)
    assert prompt['facts'] == [dict(ref='robot:r1', observed_at=1000., text='r1 online')]
    assert prompt['question'] == value.original and 'preparation' not in prompt and 'scope' not in prompt
    assert value.context['question'] == q.question
    assert value.context['preparation']['input_hash'] == q.digest


@pytest.mark.parametrize('name', ['unaccepted_followup', 'prior_map_changed'])
def test_unaccepted_prior_place_never_resolves_demonstrative_control(name):
    from deploy.ai_pc import conversation_acceptance as acceptance
    from rosy.decision.conversation.codec import semantic_answer
    case = next(case for case in acceptance.CASES if case[0] == name)
    q = acceptance.question(case, 1000.)
    raw = navigation_answer(place='A')
    raw['steps'][0]['robot_id'] = 'rosy_40'
    assert semantic_answer(raw, q, preprocessing=True).kind == 'CLARIFY'


def test_accepted_reference_is_bound_to_the_completed_robot_and_place():
    from deploy.ai_pc import conversation_acceptance as acceptance
    from rosy.decision.conversation.codec import semantic_answer
    case = next(case for case in acceptance.CASES if case[0] == 'accepted_followup')
    q = acceptance.question(case, 1000.)
    raw = navigation_answer(place='A')
    raw['steps'][0]['robot_id'] = 'rosy_40'
    assert semantic_answer(raw, q, preprocessing=True).kind == 'CONTROL'
    raw['steps'][0]['robot_id'] = 'rosy_41'
    assert semantic_answer(raw, q, preprocessing=True).kind == 'CLARIFY'


def test_preprocessed_status_reply_uses_selected_facts_without_changing_legacy_reply():
    from rosy.decision.conversation.codec import Answer, reply
    q = semantic_question('r1 말고 r2 상태')
    environment = copy.deepcopy(q.environment)
    environment['robots'].append(dict(environment['robots'][0], robot_id='r2'))
    q = q.model_copy(update={'environment':environment})
    answer = Answer(kind='STATUS', response='상태', intent=None, evidence_refs=['robot:r2'], review_required=False)
    current = reply(answer, q, preprocessing=True)
    assert 'r2' in current and 'r1' not in current
    assert 'r1' in reply(answer, q)


def test_registered_name_spacing_is_preserved_and_folded_collisions_cannot_select_another_place():
    from rosy.decision.conversation.preprocessing import prepare, control_issue
    from rosy.decision.conversation.codec import semantic_answer
    q = semantic_question('Move r1 to North  gate')
    environment = copy.deepcopy(q.environment)
    environment['map']['places'] = [dict(id='east', name='North  gate', x=1., y=2.),
                                    dict(id='west', name='North gate', x=-1., y=2.)]
    q = q.model_copy(update={'environment':environment})
    prepared = prepare(q)
    assert prepared.normalized == 'Move r1 to North  gate'
    assert control_issue(prepared) == 'AMBIGUOUS_REFERENCE'
    assert semantic_answer(navigation_answer(place='west'), q, preprocessing=True).kind == 'CLARIFY'


def test_a_single_registered_name_with_repeated_spaces_resolves_without_rewriting_it():
    from rosy.decision.conversation.preprocessing import prepare
    from rosy.decision.conversation.codec import semantic_answer
    q = semantic_question('Move r1 to North  gate')
    environment = copy.deepcopy(q.environment)
    environment['map']['places'][0]['name'] = 'North  gate'
    q = q.model_copy(update={'environment':environment})
    assert prepare(q).normalized == q.question
    value = semantic_answer(navigation_answer(place='North  gate'), q, preprocessing=True)
    assert value.intent == dict(do='navigate', robot='r1', waypoint='east')


def test_place_only_status_evidence_does_not_claim_a_populated_roster_is_empty():
    from rosy.decision.conversation.codec import Answer, reply
    q = semantic_question('입구 상태')
    answer = Answer(kind='STATUS', response='상태', intent=None, evidence_refs=['place:east'], review_required=False)
    result = reply(answer, q, preprocessing=True)
    assert '등록된 로봇이 없습니다' not in result
    assert '로봇' in result and '지정' in result


def test_decomposed_registered_name_keeps_significant_spacing():
    from rosy.decision.conversation.preprocessing import prepare, resolve_reference
    name = '입구  통로'
    text = 'r1을 '+unicodedata.normalize('NFD', name)+'로 보내줘'
    q = semantic_question(text)
    environment = copy.deepcopy(q.environment)
    environment['map']['places'][0]['name'] = name
    q = q.model_copy(update={'environment':environment})
    assert prepare(q).normalized == text
    assert resolve_reference(unicodedata.normalize('NFD', name), 'place', environment) == 'east'


@pytest.mark.parametrize('other_name', ['입구  통로', '입구 통로'])
def test_quoted_decomposed_name_collision_cannot_select_a_canonical_target(other_name):
    from rosy.decision.conversation.preprocessing import prepare, control_issue
    from rosy.decision.conversation.codec import semantic_answer
    text = 'Move r1 to "'+unicodedata.normalize('NFD', '입구  통로')+'"'
    q = semantic_question(text)
    environment = copy.deepcopy(q.environment)
    environment['map']['places'] = [dict(id='east', name='입구  통로', x=1., y=2.),
                                    dict(id='west', name=other_name, x=-1., y=2.)]
    q = q.model_copy(update={'environment':environment})
    prepared = prepare(q)
    assert prepared.normalized == text and prepared.original == text
    assert control_issue(prepared) == 'AMBIGUOUS_REFERENCE'
    assert semantic_answer(navigation_answer(place='west'), q, preprocessing=True).kind == 'CLARIFY'


@pytest.mark.parametrize('text', ['"r1을 움직여"라는 뜻을 설명해',
                                 '"r1을 보내지 마"', 'Move r1 to "거기"'])
def test_decomposed_quoted_cues_are_checked_without_rewriting_the_quote(text):
    from rosy.decision.conversation.preprocessing import control_issue
    raw = unicodedata.normalize('NFD', text)
    prepared = prepare(raw)
    assert prepared.original == raw
    assert control_issue(prepared) is not None


def test_new_discord_profile_is_not_connected_to_automatic_execution(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from fleet.server.channel.conversation import runtime
    from rosy.decision.conversation.codec import Profile
    from rosy.decision.conversation.preprocessing import DISCORD_REVISION
    installed = []
    monkeypatch.setattr(runtime, 'ConversationJobs', lambda *args:SimpleNamespace())
    monkeypatch.setattr(runtime, 'ConversationWorker', lambda *args, **kwargs:SimpleNamespace())
    from fleet.server.channel.execution import runtime as execution
    monkeypatch.setattr(execution, 'install_execution', lambda *args, **kwargs:installed.append(True))
    @asynccontextmanager
    async def lifespan(app):
        yield
    config = SimpleNamespace(profile=Profile(revision=DISCORD_REVISION), producer_scope=lambda:{})
    app = SimpleNamespace(state=SimpleNamespace(channel_requests=SimpleNamespace(reply_outbox=object()),
        fleet_gather=object()), router=SimpleNamespace(lifespan_context=lifespan))
    runtime.install_conversation(app, config, object(), task_service=object())
    assert installed == []


@pytest.mark.parametrize('channel', ['console', 'discord'])
@pytest.mark.parametrize('wrong_hash', [False, True])
def test_fleet_checks_usage_binding_and_logs_no_original_text_or_identity(monkeypatch, caplog, channel, wrong_hash):
    import asyncio
    import logging
    from rosy.decision.conversation.preprocessing import DISCORD_REVISION, prepare
    from rosy.decision.conversation.codec import Profile, source_policy
    from test_assistant_provider import configuration
    if channel == 'console':
        from fleet.server.assistant import provider as module
        q, cfg = question('private utterance sentinel'), configuration()
        adapter = module.OperatorProvider(cfg)
        args = (q, 30)
        response = dict(kind='CHAT', response='안녕하세요.', evidence_refs=[])
    else:
        from fleet.server.channel.conversation import runtime as module
        profile = Profile(revision=DISCORD_REVISION)
        q = semantic_question('private utterance sentinel')
        cfg = module.ConversationConfig(host='ai-host', key_file='/run/rosy-deliberation/broker.key',
            known_hosts_file='/run/rosy-deliberation/known_hosts', profile=profile, source_commit='a'*40,
            valid_until=4102444800., primary_admitted=True, semantic_evidence_sha256='b'*64,
            policy=source_policy('a'*40, profile))
        adapter, args = module.ConversationProvider(cfg), (q, profile, 30)
        response = dict(kind='CHAT', response='안녕하세요.', evidence_refs=[], intent=None, review_required=False)
    usage = dict(input_tokens=100, output_tokens=10, elapsed_ms=1.,
                 preparation_hash='b'*64 if wrong_hash else prepare(q).digest)
    async def exchange(config, command, packet, remaining):
        body = json.loads(packet)
        return {key:body[key] for key in ('source_commit', 'profile', 'input_hash')} | {
            **({'semantic_evidence_sha256':body['semantic_evidence_sha256']} if channel == 'console' else {}),
            'cost_usd':0., 'answer':response | {'usage':usage}}
    monkeypatch.setattr(module, 'exchange', exchange)
    if wrong_hash:
        with pytest.raises(ValueError, match='PREPARATION_CHANGED'):
            asyncio.run(adapter(*args))
    else:
        with caplog.at_level(logging.INFO, logger='uvicorn.error'):
            result = asyncio.run(adapter(*args))
        assert result['kind'] == 'CHAT' and 'usage' not in result
        assert '"input_tokens": 100' in caplog.text
        assert 'private utterance sentinel' not in caplog.text and 'alice' not in caplog.text
