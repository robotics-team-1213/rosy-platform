"""Plan/step checkpoints share the Task DB; model history grants no authority."""
from contextlib import closing
import json
import time

from fastapi import HTTPException
from core_common.intent import interpret
from rosy.decision.conversation.codec import ConversationInput, checked_answer, conversation_input, digest
from .instructions import bind_original, catalog_hash
from ...dispatch_admission import reserve, release


class ExecutionJournal:
    def __init__(self, jobs, task_store, *, producer_scope, admitted, environment, clock=time.time):
        if jobs.journal.path.resolve() != task_store.path.resolve():
            raise ValueError('ONE_CHANNEL_TASK_DATABASE_REQUIRED')
        self.jobs, self.store, self.clock = jobs, task_store, clock
        self.scope, self.admitted, self.environment = producer_scope, admitted, environment
        with closing(self.store._connect()) as conn, conn:
            conn.executescript('''CREATE TABLE IF NOT EXISTS fleet_channel_execution (
                request_id TEXT PRIMARY KEY, input_hash TEXT NOT NULL, producer_hash TEXT NOT NULL,
                model_result_hash TEXT NOT NULL, catalog_hash TEXT NOT NULL, plan_json TEXT NOT NULL,
                plan_hash TEXT NOT NULL, expires_at REAL NOT NULL, reason TEXT);
                CREATE TABLE IF NOT EXISTS fleet_channel_execution_steps (
                request_id TEXT NOT NULL, step_index INTEGER NOT NULL, state TEXT NOT NULL,
                owner_id TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL, task_id TEXT UNIQUE,
                receipt_json TEXT, reason TEXT, PRIMARY KEY(request_id,step_index));
                CREATE TABLE IF NOT EXISTS fleet_channel_execution_selection (
                principal_id TEXT NOT NULL, author_id TEXT NOT NULL, guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL, request_id TEXT NOT NULL, task_id TEXT NOT NULL,
                robot_id TEXT NOT NULL, place_id TEXT NOT NULL, catalog_hash TEXT NOT NULL,
                expires_at REAL NOT NULL, PRIMARY KEY(principal_id,author_id,guild_id,channel_id));''')

    def selection(self, question, conn):
        row = conn.execute('''SELECT s.* FROM fleet_channel_execution_selection s
            JOIN fleet_tasks t ON t.task_id=s.task_id WHERE principal_id=? AND author_id=?
            AND guild_id=? AND channel_id=? AND s.expires_at>? AND t.status='COMPLETED' ''',
            (question.principal_id,question.author_id,question.guild_id,question.channel_id,self.clock())).fetchone()
        if row is None or row['catalog_hash'] != catalog_hash(question.environment):
            return None
        try:self.guard(row['request_id'],conn)
        except (ValueError,HTTPException):return None
        return dict(row)

    def guard(self, rid, conn=None):
        if conn is None:
            with closing(self.store._connect()) as c:
                return self.guard(rid,c)
        row = conn.execute('SELECT * FROM fleet_channel_execution WHERE request_id=?',(rid,)).fetchone()
        if row is None or row['reason'] is not None or not 0 < row['expires_at']-self.clock() <= 120:
            raise ValueError('CHANNEL_EXECUTION_GRANT_EXPIRED_OR_HELD')
        model = self.jobs._row(conn,rid)
        receipt = self.jobs._receipt(conn,model,active=False)
        if (self.admitted() is not True or model['state'] != 'ANSWERED'
                or model['input_hash'] != row['input_hash'] or model['profile_set_hash'] != digest(self.scope)
                or digest(json.loads(model['result_json'])) != row['model_result_hash']
                or row['producer_hash'] != digest(self.scope) or digest(json.loads(row['plan_json'])) != row['plan_hash']
                or row['catalog_hash'] != catalog_hash(self.environment())):
            raise ValueError('CHANNEL_EXECUTION_ORIGIN_CHANGED')
        return receipt

    def accept(self, rid):
        with closing(self.store._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            old = conn.execute('SELECT 1 FROM fleet_channel_execution WHERE request_id=?',(rid,)).fetchone()
            if old:
                return self.view(rid,conn)
            model = self.jobs._row(conn,rid)
            receipt = self.jobs._receipt(conn,model,active=False)
            question = ConversationInput.model_validate_json(model['problem_json'])
            if question != conversation_input(receipt,question.environment,self.jobs.journal.config.bot_id,
                question.history,now=question.observed_at):raise ValueError('CHANNEL_EXECUTION_ORIGINAL_CHANGED')
            result = json.loads(model['result_json'])
            attempt=conn.execute("SELECT state,result_json,known_cost_usd FROM fleet_channel_conversation_attempts WHERE request_id=? AND role='primary'",(rid,)).fetchone()
            if (model['state'] != 'ANSWERED' or self.admitted() is not True or self.scope is None
                    or attempt is None or attempt['state']!='RESULT' or attempt['known_cost_usd']!=0
                    or json.loads(attempt['result_json'])!=result
                    or model['profile_set_hash'] != digest(self.scope)
                    or result.get('producer_scope') != self.scope or result.get('profile_set_hash') != digest(self.scope)
                    or result.get('input_hash') != question.digest or model['input_hash'] != question.digest
                    or result.get('profile') != self.scope['profile']
                    or not 0 <= self.clock()-question.observed_at <= 60):
                raise ValueError('CHANNEL_EXECUTION_PRODUCER_NOT_ADMITTED')
            answer = checked_answer(result['answer'],question)
            if answer.kind != 'CONTROL' or answer.review_required:
                raise ValueError('CHANNEL_CONTROL_PROPOSAL_REQUIRED')
            plan = bind_original(question,answer.intent,selection=self.selection(question,conn))
            if catalog_hash(question.environment) != catalog_hash(self.environment()):
                raise ValueError('CHANNEL_EXECUTION_CATALOG_CHANGED')
            conn.execute('INSERT INTO fleet_channel_execution VALUES (?,?,?,?,?,?,?,?,NULL)',
                (rid,question.digest,digest(self.scope),digest(result),catalog_hash(question.environment),
                 json.dumps(plan,ensure_ascii=False),digest(plan),self.clock()+120))
            generation = self.store.dispatch_control()['generation']
            for index,_ in enumerate(interpret(plan)):
                conn.execute('INSERT INTO fleet_channel_execution_steps VALUES (?,?,?,?,?,NULL,NULL,NULL)',
                    (rid,index,'READY',f'channel:{rid}:{index}',generation))
            self.jobs.journal.reply_outbox.enqueue(conn,receipt,'EXECUTION:VALIDATED',
                '원문 지시와 현재 대상·지도·권한을 검증했습니다. 기존 실행 경로에 연결합니다. 동작 완료는 아직 확인 전입니다.')
            return self.view(rid,conn)

    def view(self,rid,conn=None):
        if conn is None:
            with closing(self.store._connect()) as c:
                return self.view(rid,c)
        row=conn.execute('SELECT * FROM fleet_channel_execution WHERE request_id=?',(rid,)).fetchone()
        if row is None:raise HTTPException(404,detail='CHANNEL_EXECUTION_NOT_FOUND')
        return dict(row)|{'plan':json.loads(row['plan_json']), 'steps':[dict(r) for r in conn.execute(
            'SELECT * FROM fleet_channel_execution_steps WHERE request_id=? ORDER BY step_index',(rid,))]}

    def link_task(self,rid,index,task_id,conn):
        receipt=self.guard(rid,conn)
        row=conn.execute('SELECT * FROM fleet_channel_execution_steps WHERE request_id=? AND step_index=?',
                         (rid,index)).fetchone()
        if row['task_id']==task_id and row['state']=='TASK_QUEUED':return
        if row['state'] != 'READY':raise ValueError('CHANNEL_STEP_ALREADY_SPENT')
        conn.execute("UPDATE fleet_channel_execution_steps SET state='TASK_QUEUED',task_id=? WHERE request_id=? AND step_index=?",
                     (task_id,rid,index))
        question=ConversationInput.model_validate_json(self.jobs._row(conn,rid)['problem_json'])
        call=interpret(self.view(rid,conn)['plan'])[index]
        conn.execute('INSERT OR REPLACE INTO fleet_channel_execution_selection VALUES (?,?,?,?,?,?,?,?,?,?)',
            (question.principal_id,question.author_id,question.guild_id,question.channel_id,rid,task_id,
             call.robot,call.body['waypoint'],catalog_hash(question.environment),self.clock()+120))
        self.jobs.journal.reply_outbox.enqueue(conn,receipt,f'EXECUTION:{index}:TASK',
            f"이동 작업 {task_id}에 연결했습니다. 관제 큐·안전 검증 후 실행하며 완료는 별도 확인합니다.")

    def task_reason(self,task_id):
        with closing(self.store._connect()) as conn:
            row=conn.execute('SELECT request_id FROM fleet_channel_execution_steps WHERE task_id=?',(task_id,)).fetchone()
            if row is None:return None
            try:self.guard(row['request_id'],conn)
            except (ValueError,HTTPException):return 'CHANNEL_EXECUTION_ORIGIN_CHANGED'
            task=self.store.get_task(task_id)
            current=next((r for r in self.environment()['robots'] if r['robot_id']==task['robot_id']),None)
            if current is None or current['online'] is not True or current.get('estop',current.get('state',{}).get('safety',{}).get('estop')) is not False:
                return 'CHANNEL_EXECUTION_OBSERVATION_UNKNOWN'
        return None

    def begin(self,rid,index,resources,*,stopping=False):
        with closing(self.store._connect()) as conn,conn:
            conn.execute('BEGIN IMMEDIATE')
            self.guard(rid,conn)
            row=conn.execute('SELECT * FROM fleet_channel_execution_steps WHERE request_id=? AND step_index=?',(rid,index)).fetchone()
            if row['state'] != 'READY':raise ValueError('CHANNEL_STEP_ALREADY_SPENT')
            if not stopping and (not self.store.dispatch_generation_is_current(row['generation']) or
                    not reserve(conn,owner_kind='direct_action',owner_id=row['owner_id'],generation=row['generation'],
                                resources=resources,phase='DISPATCHING')):
                raise ValueError('DISPATCH_CLOSED_OR_RESOURCE_BUSY')
            conn.execute("UPDATE fleet_channel_execution_steps SET state='DISPATCHING' WHERE request_id=? AND step_index=?",(rid,index))

    def finish(self,rid,index,state,*,reason=None,receipt=None):
        with closing(self.store._connect()) as conn,conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM fleet_channel_execution_steps WHERE request_id=? AND step_index=?',(rid,index)).fetchone()
            if row is None:raise ValueError('CHANNEL_STEP_NOT_FOUND')
            conn.execute('UPDATE fleet_channel_execution_steps SET state=?,reason=?,receipt_json=? WHERE request_id=? AND step_index=?',
                (state,reason,json.dumps(receipt) if receipt is not None else None,rid,index))
            if state in {'UNKNOWN','ACCEPTED'}:
                conn.execute("UPDATE fleet_action_claims SET phase='UNKNOWN' WHERE owner_kind='direct_action' AND owner_id=?",(row['owner_id'],))
            elif state in {'HOLD','FAILED','COMPLETED','CANCELED'}:
                release(conn,owner_kind='direct_action',owner_id=row['owner_id'],generation=row['generation'])
            if state == 'HOLD':conn.execute('UPDATE fleet_channel_execution SET reason=? WHERE request_id=?',(reason,rid))
            model=self.jobs._row(conn,rid)
            try:original=self.jobs._receipt(conn,model,active=False)
            except HTTPException:return
            note='결과 불명 · 자동 재실행하지 않습니다.' if state=='UNKNOWN' else '실행 수용 응답이며 물리 완료는 확인 전입니다.' if state=='ACCEPTED' else reason or state
            self.jobs.journal.reply_outbox.enqueue(conn,original,f'EXECUTION:{index}:{state}',
                f'요청 단계 {index+1} · {state}\n{note}')

    def recover(self):
        with closing(self.store._connect()) as conn:
            rows=conn.execute("SELECT request_id,step_index FROM fleet_channel_execution_steps WHERE state='DISPATCHING'").fetchall()
        for row in rows:self.finish(row['request_id'],row['step_index'],'UNKNOWN',reason='PROCESS_RESTARTED_AFTER_RESERVATION')
