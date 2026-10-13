"""Conversation owner uses independent tables and immutable same-actor context."""
import json
from contextlib import closing
from fastapi import HTTPException

from rosy.decision.conversation.codec import ConversationInput, History, bounded_environment, conversation_input, digest
from ..model_journal import ModelJobsJournal


class ConversationJobs(ModelJobsJournal):
    tables = ('fleet_channel_conversation_jobs', 'fleet_channel_conversation_attempts',
              'fleet_channel_conversation_activation')
    reply_kind = 'CONVERSATION'
    invalid_reply = '현재 관측·지도 또는 대화 입력을 검증하지 못해 보류했습니다. 기기 명령을 보내지 않았습니다.'

    def read(self,request_id,principal):
        value=super().read(request_id,principal)
        execution=getattr(self,'execution',None)
        if execution is not None and value['result'] is not None:
            try:state=execution.view(request_id)
            except HTTPException as exc:
                if exc.status_code!=404:raise
            else:value['result']['execution']={k:state[k] for k in ('plan_hash','expires_at','reason','steps')}
        return value

    def history(self, receipt, environment, now):
        with closing(self.journal._connect()) as conn:
            rows = conn.execute('''SELECT j.problem_json,j.result_json,j.completed_at
                FROM fleet_channel_conversation_jobs j
                WHERE j.state='ANSWERED' AND j.completed_at BETWEEN ? AND ? AND j.profile_set_hash=?
                AND json_extract(j.problem_json,'$.principal_id')=?
                AND json_extract(j.problem_json,'$.author_id')=?
                AND json_extract(j.problem_json,'$.guild_id')=?
                AND json_extract(j.problem_json,'$.channel_id')=?
                ORDER BY j.completed_at DESC LIMIT 4''', (now-120, now, self.profile_set_hash, receipt['principal_id'],
                    receipt['author_id'], receipt['guild_id'], receipt['channel_id'])).fetchall()
        selected = []
        for raw, result, at in reversed(rows):
            question = ConversationInput.model_validate_json(raw)
            value = json.loads(result)
            if digest(question.environment) != digest(environment) or 'answer' not in value:continue
            answer = value['answer']
            selected.append(History(**{k:getattr(question, k) for k in ('request_id', 'principal_id',
                'author_id', 'guild_id', 'channel_id', 'question', 'content_hash')}, answered_at=at,
                environment_hash=digest(environment), kind=answer['kind'], intent=answer['intent'],
                response=answer['response'] if answer['kind']=='CHAT' else None))
        return selected

    def build_input(self, receipt, snapshot, now):
        environment = bounded_environment(snapshot)
        question = conversation_input(receipt, snapshot, self.journal.config.bot_id,
                                      self.history(receipt, environment, now), now=now)
        execution = getattr(self, 'execution', None)
        if execution is not None:
            with closing(execution.store._connect()) as conn:
                context = execution.selection(question, conn)
            question = ConversationInput.model_validate(question.model_dump() | {'accepted_execution_context':context})
        return question

    def context_current(self, question):
        context = question.accepted_execution_context
        if context is None:return True
        execution = getattr(self, 'execution', None)
        if execution is None:return False
        with closing(execution.store._connect()) as conn:
            return execution.selection(question, conn, bound=context) == context

    def validate_input(self, receipt, problem, snapshot):
        if (type(problem) is not ConversationInput or problem != conversation_input(receipt, snapshot,
                self.journal.config.bot_id, problem.history, now=problem.observed_at,
                accepted_execution_context=problem.accepted_execution_context) or not self.context_current(problem)):
            raise ValueError('CONVERSATION_INPUT_REQUIRED')

    @staticmethod
    def serialize_input(problem):return problem.model_dump_json()

    @staticmethod
    def input_basis(snapshot):return bounded_environment(snapshot)
