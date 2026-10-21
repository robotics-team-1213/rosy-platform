"""Durable Console dialogue, independent of Discord and device execution."""
import asyncio

import pytest
from fastapi import HTTPException

from core_common.protocol.assistant import AssistantMessage, AssistantFact
from fleet.server.task_store import FleetTaskStore


def fixture(tmp_path, *, provider=None, admitted=True):
    from fleet.server.assistant.journal import AssistantJournal
    from fleet.server.assistant.service import AssistantService
    store = FleetTaskStore(tmp_path/'tasks.sqlite')
    clock = [1000.]
    journal = AssistantJournal(store._connect, clock=lambda: clock[0])
    calls = []

    async def context(principal, selected, locale='ko-KR'):
        return [AssistantFact(ref='robot:r1', text='r1: 온라인, 모드 IDLE', observed_at=clock[0])]

    async def model(question, remaining):
        calls.append(question)
        if provider:
            return await provider(question, remaining)
        return dict(kind='STATUS', response='상태를 확인합니다.', evidence_refs=['robot:r1'])

    service = AssistantService(journal, context=context, provider=model,
        admitted=lambda: admitted, authorized=lambda p: p in ('alice', 'bob'), clock=lambda: clock[0])
    return service, journal, calls, clock


def message(**changes):
    return AssistantMessage(**(dict(request_id='req-1', conversation_id='conv-1', text='상태 알려줘') | changes))


def test_same_request_is_durable_once_and_conflict_is_rejected(tmp_path):
    service, journal, calls, _ = fixture(tmp_path)
    first, created = service.submit('alice', message())
    assert created and first.state == 'PENDING'
    assert service.submit('alice', message())[1] is False
    with pytest.raises(HTTPException) as failure:
        service.submit('alice', message(text='다른 질문'))
    assert failure.value.status_code == 409
    asyncio.run(service.step('alice', 'req-1'))
    result = service.read('alice', 'req-1')
    assert result.state == 'ANSWERED' and result.action_admissible is False
    assert result.facts[0].ref == 'robot:r1'
    assert 'IDLE' in result.response
    asyncio.run(service.step('alice', 'req-1'))
    assert len(calls) == 1
    with pytest.raises(HTTPException) as failure:
        service.read('bob', 'req-1')
    assert failure.value.status_code == 404
    assert journal.history('bob', 'conv-1') == []


def test_unconfigured_model_holds_without_call_and_history_is_scoped(tmp_path):
    service, journal, calls, _ = fixture(tmp_path, admitted=False)
    row, _ = service.submit('alice', message())
    assert row.state == 'HOLD' and row.reason == 'ASSISTANT_NOT_ADMITTED'
    asyncio.run(service.step('alice', 'req-1'))
    assert not calls
    assert len(journal.history('alice', 'conv-1')) == 1
    assert journal.history('alice', 'other') == []


def test_restart_never_replays_running_model(tmp_path):
    service, journal, calls, _ = fixture(tmp_path)
    service.submit('alice', message())
    assert journal.start('alice', 'req-1')
    journal.recover()
    assert service.read('alice', 'req-1').state == 'UNKNOWN'
    asyncio.run(service.step('alice', 'req-1'))
    assert not calls


@pytest.mark.parametrize('output', [
    dict(kind='STATUS', response='오류', evidence_refs=['robot:foreign']),
    dict(kind='CHAT', response='<script>alert(1)</script>', evidence_refs=[]),
    dict(kind='STATUS', response='완료', evidence_refs=[], intent={'do':'move'}),
])
def test_untrusted_model_output_cannot_add_facts_tools_or_markup(tmp_path, output):
    async def model(*_): return output
    service, _, _, _ = fixture(tmp_path, provider=model)
    service.submit('alice', message())
    asyncio.run(service.step('alice', 'req-1'))
    result = service.read('alice', 'req-1')
    assert result.state == 'HOLD' and result.action_admissible is False


def test_timeout_is_unknown_not_retried(tmp_path):
    async def model(*_): raise TimeoutError()
    service, _, calls, _ = fixture(tmp_path, provider=model)
    service.submit('alice', message())
    asyncio.run(service.step('alice', 'req-1'))
    assert service.read('alice', 'req-1').state == 'UNKNOWN'
    asyncio.run(service.step('alice', 'req-1'))
    assert len(calls) == 1


def test_control_only_hands_off_and_stale_facts_are_held(tmp_path):
    async def model(*_): return dict(kind='CONTROL', response='보냈습니다.', evidence_refs=[])
    service, _, _, _ = fixture(tmp_path, provider=model)
    service.submit('alice', message())
    asyncio.run(service.step('alice', 'req-1'))
    row = service.read('alice', 'req-1')
    assert row.state == 'ANSWERED' and '작업 화면' in row.response and '보냈습니다' not in row.response

    async def stale(*_): return [AssistantFact(ref='robot:r1', text='old', observed_at=1.)]
    service.context = stale
    service.submit('alice', message(request_id='req-2'))
    asyncio.run(service.step('alice', 'req-2'))
    assert service.read('alice', 'req-2').state == 'HOLD'


def test_pending_limits_and_authority_change_before_reply(tmp_path):
    service, _, _, _ = fixture(tmp_path)
    service.submit('alice', message())
    with pytest.raises(HTTPException) as failure:
        service.submit('alice', message(request_id='req-2'))
    assert failure.value.status_code == 429
    service.authorized = lambda _: False
    asyncio.run(service.step('alice', 'req-1'))
    assert service.journal.read('alice', 'req-1').state == 'HOLD'


def test_followup_history_never_crosses_conversation_or_reuses_status_facts(tmp_path):
    service, _, calls, _ = fixture(tmp_path)
    service.submit('alice', message())
    asyncio.run(service.step('alice', 'req-1'))
    service.submit('alice', message(request_id='req-2', text='그럼 지금은?'))
    asyncio.run(service.step('alice', 'req-2'))
    assert calls[1].history == []  # Prior observed facts are never model memory.
    service.submit('alice', message(request_id='req-3', conversation_id='conv-2'))
    asyncio.run(service.step('alice', 'req-3'))
    assert calls[2].history == []


def test_chat_cannot_publish_unverified_physical_completion(tmp_path):
    claim = '모든 장비가 정상입니다. 출입구까지 도착했습니다.'
    async def model(*_): return dict(kind='CHAT', response=claim, evidence_refs=[])
    service, _, _, _ = fixture(tmp_path, provider=model)
    service.submit('alice', message(text='안녕'))
    asyncio.run(service.step('alice', 'req-1'))
    result = service.read('alice', 'req-1')
    assert result.state in ('HOLD', 'ANSWERED')
    assert result.response != claim and '도착했습니다' not in (result.response or '')


def test_site_model_calls_are_serialized_across_operators(tmp_path):
    active, peak = [0], [0]
    async def model(*_):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await asyncio.sleep(.01)
        active[0] -= 1
        return dict(kind='CHAT', response='안녕하세요.', evidence_refs=[])
    service, _, _, _ = fixture(tmp_path, provider=model)
    service.submit('alice', message())
    service.submit('bob', message())
    async def exercise():
        await asyncio.gather(service.step('alice', 'req-1'), service.step('bob', 'req-1'))
    asyncio.run(exercise())
    assert peak[0] == 1


def test_cancel_during_durable_claim_leaves_unknown_instead_of_running(tmp_path):
    import threading
    service, journal, calls, _ = fixture(tmp_path)
    service.submit('alice', message())
    claimed, release = threading.Event(), threading.Event()
    original = journal.start
    def slow_claim(*args):
        result = original(*args)
        claimed.set()
        assert release.wait(5)
        return result
    journal.start = slow_claim
    async def exercise():
        task = asyncio.create_task(service.step('alice', 'req-1'))
        assert await asyncio.to_thread(claimed.wait, 5)
        task.cancel(); release.set()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(exercise())
    assert journal.read('alice', 'req-1').state == 'UNKNOWN'
    assert not calls
