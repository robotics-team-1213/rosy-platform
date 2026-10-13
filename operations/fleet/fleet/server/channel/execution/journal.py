"""Plan/step checkpoints share the Task DB; model history grants no authority."""
from contextlib import closing
import json
import time
from uuid import uuid4

from fastapi import HTTPException
from fleet.hub.hub import HubError
from core_common.intent import interpret
from rosy.decision.conversation.codec import AcceptedContext, ConversationInput, checked_answer, conversation_input, digest
from .instructions import bind_original, catalog_hash
from .outcomes.evidence import exact_operation, safe_proof
from ...dispatch_admission import reserve, release


def native_required(self, task_id):
    """Identify native-required Tasks through the existing channel link."""
    if self.channel_admission is None:
        return False
    with self.store._connect() as conn:
        return conn.execute('SELECT 1 FROM fleet_channel_execution_steps WHERE task_id=?', (task_id,)).fetchone() is not None


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
                receipt_json TEXT, reason TEXT, resources_json TEXT, PRIMARY KEY(request_id,step_index));
                CREATE TABLE IF NOT EXISTS fleet_channel_execution_selection (
                principal_id TEXT NOT NULL, author_id TEXT NOT NULL, guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL, request_id TEXT NOT NULL, task_id TEXT NOT NULL,
                robot_id TEXT NOT NULL, place_id TEXT NOT NULL, catalog_hash TEXT NOT NULL,
                expires_at REAL NOT NULL, PRIMARY KEY(principal_id,author_id,guild_id,channel_id));''')
            if 'resources_json' not in {r['name'] for r in conn.execute('PRAGMA table_info(fleet_channel_execution_steps)')}:
                conn.execute('ALTER TABLE fleet_channel_execution_steps ADD COLUMN resources_json TEXT')
            if 'caller_cid' not in {r['name'] for r in conn.execute('PRAGMA table_info(fleet_channel_execution_steps)')}:
                conn.execute('ALTER TABLE fleet_channel_execution_steps ADD COLUMN caller_cid TEXT')

    def selection(self, question, conn, *, bound=None, visiting=()):
        if bound is None:
            bound = conn.execute('''SELECT * FROM fleet_channel_execution_selection
                WHERE principal_id=? AND author_id=? AND guild_id=? AND channel_id=? AND expires_at>?''',
                (question.principal_id,question.author_id,question.guild_id,question.channel_id,self.clock())).fetchone()
        if bound is None or bound['request_id'] in visiting:return None
        row = conn.execute('''SELECT t.*,s.step_index,e.plan_json,e.catalog_hash,e.expires_at AS grant_expires_at
            FROM fleet_tasks t JOIN fleet_channel_execution_steps s ON s.task_id=t.task_id
            JOIN fleet_channel_execution e ON e.request_id=s.request_id
            WHERE t.task_id=? AND s.request_id=? AND t.status='COMPLETED' ''',
            (bound['task_id'],bound['request_id'])).fetchone()
        if row is None or row['catalog_hash'] != catalog_hash(question.environment):return None
        try:
            self.guard(bound['request_id'],conn,visiting=visiting)
            origin = ConversationInput.model_validate_json(self.jobs._row(conn,bound['request_id'])['problem_json'])
            scope = {k:getattr(origin,k) for k in ('principal_id','author_id','guild_id','channel_id')}
            if any(getattr(question,k) != value for k,value in scope.items()):return None
            if not self.store.dispatch_generation_is_current(row['dispatch_generation']):return None
            receipt = json.loads(row['receipt_json'] or '{}')
            if receipt.get('operation') or receipt.get('native_required'):
                outcome = exact_operation(receipt['outcome'],receipt['operation'])
                if (receipt.get('safe_released') is not True or outcome['result'] != 'SUCCEEDED'
                        or outcome['correlation_id'] != row['attempt_id'] or not safe_proof({
                            'lookup':'FOUND','operation':outcome,'quiescence':receipt.get('quiescence'),
                            'owner':receipt.get('quiescence',{})},outcome)):return None
            call = interpret(json.loads(row['plan_json']))[row['step_index']]
            if call.verb != 'navigate' or call.robot != row['robot_id']:return None
            return AcceptedContext(**scope,request_id=bound['request_id'],task_id=row['task_id'],
                robot_id=call.robot,place_id=call.body['waypoint'],catalog_hash=row['catalog_hash'],
                expires_at=row['grant_expires_at'],evidence_hash=digest(receipt),
                generation=row['dispatch_generation'],boot_id=receipt.get('operation',{}).get('boot_id'),
                run_id=receipt.get('operation',{}).get('run_id'),attempt_id=receipt.get('operation',{}).get('correlation_id'),
                owner_generation=receipt.get('quiescence',{}).get('owner_generation')).model_dump()
        except (ValueError,KeyError,TypeError,HTTPException):return None

    def context_for_task(self, task_id):
        with closing(self.store._connect()) as conn:
            row=conn.execute('SELECT request_id FROM fleet_channel_execution_steps WHERE task_id=?',(task_id,)).fetchone()
            if row is None:return None
            try:self.guard(row['request_id'],conn)
            except (ValueError,HTTPException) as exc:raise HubError('COMMAND_REJECTED','CHANNEL_SELECTED_CONTEXT_CHANGED') from exc
            return ConversationInput.model_validate_json(self.jobs._row(conn,row['request_id'])['problem_json']).accepted_execution_context

    def guard(self, rid, conn=None, *, visiting=()):
        if conn is None:
            with closing(self.store._connect()) as c:
                return self.guard(rid,c,visiting=visiting)
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
        question = ConversationInput.model_validate_json(model['problem_json'])
        context = question.accepted_execution_context
        if context is not None and self.selection(question,conn,bound=context,visiting=(*visiting,rid)) != context:
            raise ValueError('CHANNEL_EXECUTION_SELECTION_CHANGED')
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
                question.history,now=question.observed_at,accepted_execution_context=question.accepted_execution_context):
                raise ValueError('CHANNEL_EXECUTION_ORIGINAL_CHANGED')
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
            context = question.accepted_execution_context
            if context is not None and self.selection(question,conn,bound=context) != context:
                raise ValueError('CHANNEL_EXECUTION_SELECTION_CHANGED')
            plan = bind_original(question,answer.intent,selection=context)
            if catalog_hash(question.environment) != catalog_hash(self.environment()):
                raise ValueError('CHANNEL_EXECUTION_CATALOG_CHANGED')
            conn.execute('INSERT INTO fleet_channel_execution VALUES (?,?,?,?,?,?,?,?,NULL)',
                (rid,question.digest,digest(self.scope),digest(result),catalog_hash(question.environment),
                 json.dumps(plan,ensure_ascii=False),digest(plan),self.clock()+120))
            generation = self.store.dispatch_control()['generation']
            for index,_ in enumerate(interpret(plan)):
                conn.execute('INSERT INTO fleet_channel_execution_steps (request_id,step_index,state,owner_id,generation) VALUES (?,?,?,?,?)',
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
            conn.execute("UPDATE fleet_channel_execution_steps SET state='DISPATCHING',resources_json=?,caller_cid=? WHERE request_id=? AND step_index=?",
                         (json.dumps(resources),str(uuid4()),rid,index))

    def finish(self,rid,index,state,*,reason=None,receipt=None,expected_state=None):
        with closing(self.store._connect()) as conn,conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM fleet_channel_execution_steps WHERE request_id=? AND step_index=?',(rid,index)).fetchone()
            if row is None:raise ValueError('CHANNEL_STEP_NOT_FOUND')
            if expected_state is not None and row['state']!=expected_state:
                # A late owned receipt remains evidence, but cannot reopen an unknown dispatch.
                if receipt is not None and row['state']=='UNKNOWN' and row['receipt_json'] is None:
                    conn.execute('UPDATE fleet_channel_execution_steps SET receipt_json=? WHERE request_id=? AND step_index=?',
                                 (json.dumps(receipt),rid,index))
                return False
            conn.execute('UPDATE fleet_channel_execution_steps SET state=?,reason=?,receipt_json=? WHERE request_id=? AND step_index=?',
                (state,reason,json.dumps(receipt) if receipt is not None else None,rid,index))
            if state in {'UNKNOWN','ACCEPTED','RUNNING'}:
                conn.execute("UPDATE fleet_action_claims SET phase='UNKNOWN' WHERE owner_kind='direct_action' AND owner_id=?",(row['owner_id'],))
                plan=json.loads(conn.execute('SELECT plan_json FROM fleet_channel_execution WHERE request_id=?',(rid,)).fetchone()[0])
                if row['resources_json'] and interpret(plan)[index].verb not in {'cancel','stop','estop','formation_stop','follow_cancel'}:
                    missing=[(k,r) for k,r in json.loads(row['resources_json']) if not conn.execute(
                        'SELECT 1 FROM fleet_action_claims WHERE resource_key=? AND owner_kind=? AND owner_id=? AND generation=?',
                        (k+':'+r,'direct_action',row['owner_id'],row['generation'])).fetchone()]
                    if missing and not reserve(conn,owner_kind='direct_action',owner_id=row['owner_id'],generation=row['generation'],
                                               resources=missing,phase='UNKNOWN'):
                        raise ValueError('UNRESOLVED_CHANNEL_RESOURCE_CONFLICT')
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
            rows=conn.execute("SELECT * FROM fleet_channel_execution_steps WHERE state IN ('DISPATCHING','UNKNOWN','ACCEPTED','RUNNING')").fetchall()
        for row in rows:self.finish(row['request_id'],row['step_index'],'UNKNOWN' if row['state']=='DISPATCHING' else row['state'],
            reason='PROCESS_RESTARTED_AFTER_RESERVATION' if row['state']=='DISPATCHING' else row['reason'],
            receipt=json.loads(row['receipt_json']) if row['receipt_json'] else None,expected_state=row['state'])
