"""Explicit locale is shared by text and optional local speech."""
import asyncio

import pytest
from pydantic import ValidationError

from core_common.protocol.assistant import AssistantMessage
from test_assistant_service import fixture, message


def test_english_text_reaches_model_and_server_rendered_reply(tmp_path):
    async def provider(question, _):
        assert question.locale == 'en-US'
        return dict(kind='CHAT', response='Hello', evidence_refs=[])
    service, _, _, _ = fixture(tmp_path, provider=provider)
    service.submit('alice', message(text='Hello', locale='en-US'))
    asyncio.run(service.step('alice', 'req-1'))
    assert service.read('alice', 'req-1').response.startswith('Hello')


def test_unsupported_locale_is_not_silently_changed():
    with pytest.raises(ValidationError): message(locale='xx-XX')
