"""D-831 preserves submitted text and prevents unsafe candidates becoming commands."""
import copy
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
