"""One read-only conversation operation behind a small interface."""
import asyncio
import logging
import time

from core_common.protocol.assistant import AssistantFact
from rosy.decision.conversation.operator import OperatorInput, OperatorScope, checked_operator_answer


class AssistantService:
    def __init__(self, journal, *, context, provider, admitted, authorized, clock=time.time):
        self.journal, self.context, self.provider = journal, context, provider
        self.admitted, self.authorized, self.clock = admitted, authorized, clock

    def submit(self, principal, message):
        return self.journal.submit(principal, message, admitted=self.admitted())

    def read(self, principal, request_id):
        return self.journal.read(principal, request_id)

    def valid_facts(self, facts):
        result = [AssistantFact.model_validate(f) for f in facts]
        if len(result) > 64 or any(not 0 <= self.clock()-f.observed_at <= 5 for f in result):
            raise ValueError('ASSISTANT_STALE_CONTEXT')
        return result

    async def db(self, operation, *args, **kwargs):
        pending = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            await asyncio.shield(pending)
            raise

    async def step(self, principal, request_id, *, reauthorize=None):
        if not await self.db(self.journal.start, principal, request_id):
            return
        authorized = reauthorize or (lambda: self.authorized(principal))
        invoked = False
        try:
            if not authorized() or not self.admitted():
                raise ValueError('ASSISTANT_AUTHORITY_CHANGED')
            message = await self.db(self.journal.message, principal, request_id)
            row = await self.db(self.read, principal, request_id)
            if self.clock()-row.created_at > 30:
                raise ValueError('ASSISTANT_REQUEST_EXPIRED')
            async with asyncio.timeout(30):
                facts = self.valid_facts(await self.context(principal, message.selected_robot_id))
                question = OperatorInput(scope=OperatorScope(principal_id=principal, conversation_id=message.conversation_id),
                    request_id=request_id, question=message.text, selected_robot_id=message.selected_robot_id,
                    observed_at=self.clock(), facts=facts, history=await self.db(self.journal.turns, principal, message))
                invoked = True
                raw = await self.provider(question, 30)
                answer = checked_operator_answer(raw, question)
                if not authorized() or not self.admitted():
                    raise ValueError('ASSISTANT_AUTHORITY_CHANGED')
                current = self.valid_facts(await self.context(principal, message.selected_robot_id))
                if [(f.ref, f.text) for f in current] != [(f.ref, f.text) for f in facts]:
                    raise ValueError('ASSISTANT_CONTEXT_CHANGED')
                selected = [f for f in current if f.ref in answer.evidence_refs]
                if answer.kind == 'STATUS':
                    selected = selected or current
                    response = '관제에서 확인한 상태입니다.\n'+'\n'.join(f.text for f in selected) if selected else '조회할 관제 상태가 없습니다.'
                elif answer.kind == 'CAUSE':
                    selected = [f for f in selected if f.ref.startswith('incident:')]
                    response = '기록된 사건 근거입니다.\n'+'\n'.join(f.text for f in selected) if selected else '기록된 정지 원인을 확인하지 못했습니다. 사건 기록을 확인해 주세요.'
                else:
                    response = {'CHAT':'안녕하세요. 로봇 상태 조회와 사건 근거 확인을 도와드릴 수 있습니다. 확인할 로봇과 내용을 알려주세요.',
                        'CONTROL':'이 대화는 조회 전용입니다. 실행 요청은 작업 화면에서 진행해 주세요.',
                        'CLARIFY':'대상을 확정할 수 없습니다. 로봇 이름과 확인할 내용을 구체적으로 알려주세요.',
                        'REFUSE':'권한이나 안전 규칙을 우회하는 요청은 처리할 수 없습니다.'}[answer.kind]
                    selected = []
                await self.db(self.journal.finish, principal, request_id, state='ANSWERED', response=response,
                              facts=selected, kind=answer.kind)
        except asyncio.CancelledError:
            await self.db(self.journal.finish, principal, request_id, state='UNKNOWN', reason='ASSISTANT_INTERRUPTED')
            raise
        except (TimeoutError, OSError):
            await self.db(self.journal.finish, principal, request_id, state='UNKNOWN' if invoked else 'HOLD',
                          reason='ASSISTANT_RESULT_UNKNOWN' if invoked else 'ASSISTANT_CONTEXT_UNAVAILABLE')
        except (ValueError, TypeError, KeyError):
            await self.db(self.journal.finish, principal, request_id, state='HOLD', reason='ASSISTANT_VALIDATION_FAILED',
                          response='현재 권한·관측 또는 AI 답변을 검증하지 못해 보류했습니다.')
        except Exception:
            logging.getLogger(__name__).warning('Assistant processing failed; request is not replayed', exc_info=False)
            await self.db(self.journal.finish, principal, request_id, state='UNKNOWN' if invoked else 'HOLD',
                          reason='ASSISTANT_PROCESSING_FAILED')
