"""Operator dialogue bodies carry no identity or execution authority."""
import pytest
from pydantic import ValidationError

from core_common.protocol.assistant import AssistantMessage, AssistantNavigation, AssistantStatus


def test_message_keeps_original_text_and_locale_without_accepting_identity():
    body = dict(conversation_id='conversation-1', request_id='request-1', text='  보내지 마\n')
    assert AssistantMessage(**body).text == body['text']
    assert AssistantMessage(**body).locale == 'ko-KR'
    assert AssistantMessage(**body, locale='en-US').locale == 'en-US'
    for field in ('principal_id', 'guild_id', 'source', 'action_admissible'):
        with pytest.raises(ValidationError):
            AssistantMessage(**body, **{field: 'forged'})
    with pytest.raises(ValidationError):
        AssistantMessage(**body, locale='unsupported')


@pytest.mark.parametrize('x', [True, '1', float('inf'), float('nan'), 100001.])
def test_explicit_navigation_refuses_coercion_and_invalid_coordinates(x):
    with pytest.raises(ValidationError):
        AssistantNavigation(robot_id='robot-1', x=x, y=0.)


def test_explicit_navigation_and_default_status_do_not_enable_execution():
    assert AssistantNavigation(robot_id='robot-1', x=-1.5, y=2.).yaw == 0.
    status = AssistantStatus(available=True)
    assert status.mode == 'READ_ONLY'
    assert status.execution_enabled is False
