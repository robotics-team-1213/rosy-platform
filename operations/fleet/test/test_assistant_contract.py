"""Console intake is strict and never impersonates Discord identity."""
import pytest
from pydantic import ValidationError
from core_common.protocol import assistant as schemas


def message(**changes):
    return dict(conversation_id='conversation-1', request_id='request-1', text='현재 상태 알려줘',
                selected_robot_id=None) | changes


def contract():
    assert hasattr(schemas, 'AssistantMessage'), 'Console assistant contract is missing'
    return schemas.AssistantMessage


def test_console_message_preserves_original_text_and_rejects_identity_in_body():
    model = contract()
    text = '  현재 상태\n알려줘  '
    assert model(**message(text=text)).text == text
    for field in ('principal_id', 'author_id', 'guild_id', 'channel_id', 'source'):
        with pytest.raises(ValidationError):
            model(**message(**{field: 'forged'}))


@pytest.mark.parametrize('change', [dict(text=' '), dict(text='x'*2001), dict(text='a\x00b'),
    dict(request_id='../other'), dict(conversation_id=''), dict(selected_robot_id='<script>')])
def test_console_message_limits_are_checked(change):
    with pytest.raises(ValidationError):
        contract()(**message(**change))


def test_console_model_scope_is_distinct_from_discord_v1():
    from rosy.decision.conversation import operator
    scope = operator.OperatorScope(principal_id='alice', conversation_id='conversation-1')
    assert scope.source == 'console'
    with pytest.raises(ValidationError):
        operator.OperatorScope(principal_id='alice', conversation_id='conversation-1', guild_id='12345678901234567')
    from rosy.decision.conversation.codec import ConversationInput
    with pytest.raises(ValidationError):
        ConversationInput.model_validate({'scope': scope.model_dump(), 'question': '안녕'})
