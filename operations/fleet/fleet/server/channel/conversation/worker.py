"""Natural dialogue closes one durable model attempt, never dispatches a device."""
import asyncio
import time

from fastapi import HTTPException

from rosy.decision.conversation.codec import Answer, ConversationInput, checked_answer, digest, reply
from rosy.decision.conversation.preprocessing import DISCORD_REVISION
from ..execution.instructions import selected_readback


class ConversationWorker:
    def __init__(self, jobs, snapshot, profile, provider, *, admission, observation_guard, clock=time.time,
                 producer_scope=None, context_reader=None):
        expected = digest(profile.model_dump()) if producer_scope is None else digest(producer_scope)
        if expected != jobs.profile_set_hash:raise ValueError('CONVERSATION_PROFILE_CHANGED')
        self.jobs, self.snapshot, self.profile, self.provider = jobs, snapshot, profile, provider
        self.admission, self.observation_guard, self.clock = admission, observation_guard, clock
        self.producer_scope = producer_scope
        self.context_reader, self._live_context = context_reader, None
        self._lock = asyncio.Lock()

    async def refresh_context(self, question):
        context=question.accepted_execution_context
        if context is None or context.get('boot_id') is None:return True
        self._live_context=None
        if self.context_reader is None:return False
        started=time.monotonic()
        try:value=await asyncio.wait_for(self.context_reader(context),2)
        except Exception:return False
        if not selected_readback(context,value) or time.monotonic()-started>2:return False
        self._live_context=(digest(context),started)
        return True

    async def db(self, method, *args, **kwargs):
        task = asyncio.create_task(asyncio.to_thread(getattr(self.jobs, method), *args, **kwargs))
        try:return await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.shield(task)
            raise

    async def current(self, request_id, question):
        try:await self.snapshot()
        except (ValueError, TypeError, KeyError):return False
        await self.db('guard', request_id)
        return await self.refresh_context(question) and self.observed(question)

    def observed(self, question):
        context=question.accepted_execution_context
        if context is not None and context.get('boot_id') is not None and (
                self._live_context is None or self._live_context[0]!=digest(context)
                or not 0<=time.monotonic()-self._live_context[1]<=2):return False
        try:return (self.admission() is True and self.observation_guard(question.environment) is True
                    and self.jobs.context_current(question))
        except (ValueError, TypeError, KeyError, HTTPException):return False

    async def finish(self, request_id, state, result, summary, question=None):
        try:
            await self.db('finish', request_id, state=state, result={**result, 'action_admissible': False},
                summary=summary, observation_guard=None if question is None else
                lambda:self.observed(question))
        except HTTPException as exc:
            if exc.detail == 'CHANNEL_OBSERVATION_CHANGED':
                await self.finish(request_id, 'HOLD', {'reason':'OBSERVATION_CHANGED'},
                    '관제 관측·지도·설정이 바뀌어 답변 적용을 보류했습니다. 새 상태로 다시 말씀해 주세요.')
            else:await self.db('abandon', request_id, state='SUPERSEDED', reason='OWNER_OR_SCOPE_CHANGED')

    async def step(self, receipt):
        async with self._lock:
            rid = receipt['request_id']
            try:
                try:
                    existing = await self.db('peek', rid)
                    if existing['state'] != 'PENDING':return
                except HTTPException as exc:
                    if exc.status_code != 404:raise
                    try:
                        snapshot = await self.snapshot()
                        question = await self.db('build_input', receipt, snapshot, snapshot['observed_at'])
                        if not await self.refresh_context(question):raise ValueError('CONVERSATION_SELECTED_RUN_CHANGED')
                        await self.db('stage', receipt, question, snapshot)
                    except (ValueError, TypeError, KeyError):
                        await self.db('reject', receipt)
                        return
                    existing = await self.db('peek', rid)
                question = ConversationInput.model_validate_json(existing['problem_json'])
                if not 0 <= self.clock()-question.observed_at <= 3 or not await self.current(rid, question):
                    await self.finish(rid, 'HOLD', {'reason':'INPUT_NOT_CURRENT_OR_MODEL_NOT_ADMITTED'},
                        '현재 관측이나 대화 모델 수용을 확인할 수 없어 보류했습니다. 기기 명령을 보내지 않았습니다.')
                    return
                attempt = await self.db('reserve', rid, 'primary')
                if not await self.current(rid, question):
                    await self.finish(rid, 'HOLD', {'reason':'SCOPE_CHANGED'},
                        '관제 관측·지도·모델 수용이 바뀌어 요청을 보류했습니다. 기기 명령을 보내지 않았습니다.')
                    return
                self.jobs.guard(rid)
                if not self.observed(question):
                    await self.finish(rid, 'HOLD', {'reason':'SCOPE_CHANGED'},
                        '관제 관측·지도·모델 수용이 바뀌어 요청을 보류했습니다. 기기 명령을 보내지 않았습니다.')
                    return
                try:
                    remaining = min(self.profile.timeout_s, attempt['deadline']-self.clock())
                    if remaining <= 0:raise TimeoutError()
                    raw = await self.provider(question, self.profile, remaining)
                    answer = checked_answer(raw, question, preprocessing=self.profile.revision == DISCORD_REVISION)
                    record = {'profile':self.profile.model_dump(), 'input_hash':question.digest,
                              'producer_scope':self.producer_scope, 'profile_set_hash':self.jobs.profile_set_hash,
                              'models':[{'model_id':self.profile.model_id, 'profile_id':self.profile.profile_id}],
                              'answer':answer.model_dump(), 'action_admissible':False}
                    await self.db('record_attempt', rid, 'primary', state='RESULT', result=record,
                        known_cost_usd=0, input_hash=attempt['input_hash'], profile_set_hash=attempt['profile_set_hash'])
                except asyncio.CancelledError:
                    await self.finish(rid, 'UNKNOWN', {'reason':'MODEL_CANCELED'},
                        '응답 결과가 불명확하여 자동으로 재호출하지 않습니다. 기기 명령을 보내지 않았습니다.')
                    await self.db('abandon', rid, state='UNKNOWN', reason='MODEL_CANCELED')
                    raise
                except Exception:
                    await self.finish(rid, 'UNKNOWN', {'reason':'MODEL_RESULT_UNKNOWN'},
                        '모델 응답을 확인할 수 없습니다. 자동 재호출이나 기기 명령은 하지 않았습니다.')
                    await self.db('abandon', rid, state='UNKNOWN', reason='MODEL_RESULT_UNKNOWN')
                    return
                if not await self.current(rid, question):
                    await self.finish(rid, 'HOLD', {'reason':'OBSERVATION_CHANGED'},
                        '답변 중 관측·지도·권한이 바뀌어 보류했습니다. 기기 명령을 보내지 않았습니다.')
                    return
                if answer.review_required:
                    # D-720's protected status codec cannot admit a conversation review.
                    held = Answer(kind='CLARIFY', response='추가 숙고가 필요하지만 대화 검토 모델이 수용되지 않았습니다. '
                        '대상과 원하는 동작을 구체적으로 말씀해 주세요.', intent=None, evidence_refs=[], review_required=False,
                        reason='CONFLICT')
                    await self.finish(rid, 'HOLD', {**record, 'answer':held.model_dump(),
                        'primary_proposal':answer.model_dump(), 'reason':'CONVERSATION_REVIEWER_NOT_ADMITTED'}, held.response, question)
                    return
                await self.finish(rid, 'ANSWERED', record,
                    reply(answer, question, preprocessing=self.profile.revision == DISCORD_REVISION), question)
            except asyncio.CancelledError:raise
            except HTTPException:
                await self.db('abandon', rid, state='SUPERSEDED', reason='OWNER_OR_SCOPE_CHANGED')
