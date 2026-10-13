"""Dispatch admitted original steps once through the existing intent owners."""
import asyncio
import json
import math
from dataclasses import replace

from fastapi import HTTPException
from core_common.intent import interpret
from fleet.server.intent_routes import STOP_VERBS
from fleet.server.site_auth import SitePrincipal
from fleet.swarm.dispatch_guard import dispatch_guard
from fleet.swarm.transport import RobotApiError
from fleet.hub.hub import HubError
from .receipts import owner_receipt
from .outcomes.evidence import KINDS, PATHS, epoch
from .outcomes.reconcile import channel_step


_CAPABILITY = {'navigate':'navigation.goal_navigation','home':'navigation.return_home',
               'move':'teleop','follow':'swarm.follow','follow_cancel':'swarm.follow',
               'dock':'docking.supported','undock':'docking.supported'}


class ExecutionWorker:
    def __init__(self,journal,execution):
        self.journal,self.execution=journal,execution
        self._lock=asyncio.Lock()
        self._cursor=''

    def fence(self,rid,index,call):
        self.journal.guard(rid)
        row=self.journal.view(rid)['steps'][index]
        if row['state'] not in {'READY','DISPATCHING','TASK_QUEUED'}:
            raise ValueError('CHANNEL_STEP_ALREADY_SPENT')
        if call.verb not in STOP_VERBS and not self.journal.store.dispatch_generation_is_current(row['generation']):
            raise ValueError('STOP_GENERATION_CHANGED_BEFORE_SEND')
        if call.verb not in STOP_VERBS:
            targets=[call.robot] if call.robot else list(self.execution.console.robot_ids)
            if call.verb=='formation_resume':
                f=self.execution.console.formation_status()
                targets=list(dict.fromkeys([f.get('leader'),*f.get('assignment',{})]))
            if call.verb=='formation_start':targets=[call.body['leader'],*call.body['members']]
            if call.verb=='follow':targets.append(call.body['target_robot_id'])
            for target in targets:
                current=next((r for r in self.journal.environment()['robots'] if r['robot_id']==target),None)
                # Final fresh observer basis supplements the owner's fresh capability/state checks.
                if current is None or current['online'] is not True or current.get('estop',current.get('state',{}).get('safety',{}).get('estop')) is not False:
                    raise ValueError('CURRENT_ROBOT_OBSERVATION_UNKNOWN')
                if row['state']=='DISPATCHING' and target in self.execution.resources(call):
                    claims=self.journal.store.resource_claims(resource_kind='robot',resource_id=target)
                    if not any(c['owner_kind']=='direct_action' and c['owner_id']==row['owner_id']
                               and c['generation']==row['generation'] and c['phase']=='DISPATCHING' for c in claims):
                        raise ValueError('CHANNEL_RESOURCE_OWNERSHIP_CHANGED')

    async def preflight(self,rid,index,call):
        self.fence(rid,index,call)
        console=self.execution.console
        robots=[call.robot] if call.robot else list(console.robot_ids)
        if call.verb in STOP_VERBS:return robots
        if call.verb=='formation_resume':
            formation=console.formation_status()
            robots=list(dict.fromkeys([formation.get('leader'),*formation.get('assignment',{})]))
            if not robots or None in robots:raise ValueError('FORMATION_OWNER_NOT_ACTIVE')
        if call.verb=='formation_start':robots=[call.body['leader'],*call.body['members']]
        for rid_robot in robots:
            row=next((r for r in self.journal.environment()['robots'] if r['robot_id']==rid_robot),None)
            if row is None or row['online'] is not True:raise ValueError('ROBOT_OFFLINE_OR_OBSERVATION_UNKNOWN')
            client=console._client(rid_robot)
            caps=await client.capabilities()
            self.fence(rid,index,call)
            feature=_CAPABILITY.get(call.verb)
            if call.verb in {'formation_start','formation_resume'}:
                leader=call.body.get('leader') if call.verb=='formation_start' else formation['leader']
                feature='swarm.lead' if rid_robot==leader else 'swarm.follow'
            value=caps
            if feature:
                for part in feature.split('.'):value=value.get(part) if isinstance(value,dict) else None
                if value is not True:raise ValueError('CAPABILITY_NOT_ADVERTISED')
            state=await client.state()
            self.fence(rid,index,call)
            if call.verb not in STOP_VERBS:
                modes={'MANUAL'} if call.verb=='move' else {'IDLE','DOCKING'} if call.verb in {'dock','undock'} else {'IDLE','NAVIGATION'}
                if (state.get('safety',{}).get('estop') is not False or state.get('mode') not in modes
                        or state.get('capabilities_degraded') or console.trip_busy(rid_robot)):
                    raise ValueError('CURRENT_SAFETY_OR_OWNER_HOLD')
                if call.verb=='move':
                    nav=caps.get('navigation',{})
                    for field,limit in [('linear','max_linear_velocity'),('angular','max_angular_velocity')]:
                        cap=nav.get(limit)
                        if type(cap) not in (int,float) or not math.isfinite(cap) or cap<=0 or abs(call.body[field])>cap:
                            raise ValueError('MOVE_LIMIT_NOT_ADVERTISED_OR_EXCEEDED')
                if call.verb in {'dock','undock'}:
                    status=await client._get('/api/v1/docking/status')
                    self.fence(rid,index,call)
                    allowed={'DOCKED','CHARGING'} if call.verb=='undock' else {'UNDOCKED','DOCK_FAILED'}
                    if status.get('state') not in allowed:raise ValueError('DOCK_OWNER_STATE_NOT_READY')
                    if call.verb=='dock':
                        docks=await client._get('/api/v1/docking/docks')
                        self.fence(rid,index,call)
                        if not any(d.get('id')==call.body['dock'] for d in docks.get('docks',[])):
                            raise ValueError('DOCK_NOT_REGISTERED')
        if call.verb=='follow':
            target=call.body['target_robot_id']
            caps=await console._client(target).capabilities()
            self.fence(rid,index,call)
            if caps.get('swarm',{}).get('lead') is not True:raise ValueError('FOLLOW_LEADER_NOT_ADVERTISED')
        return robots

    async def step(self,rid,*,allow_dispatch=True):
        async with self._lock:
            try:view=self.journal.view(rid)
            except HTTPException as exc:
                if exc.status_code!=404:raise
                if not allow_dispatch:return
                try:view=self.journal.accept(rid)
                except (ValueError,HTTPException) as exc:
                    self.reject(rid,exc)
                    return
            calls=interpret(view['plan'])
            for index,call in enumerate(calls):
                row=self.journal.view(rid)['steps'][index]
                if row['state'] in {'ACCEPTED','RUNNING','UNKNOWN','TASK_QUEUED'}:
                    if await channel_step(self,rid,index,call,row):
                        if self.journal.view(rid)['steps'][index]['state']=='COMPLETED':continue
                        return
                if view['reason'] is not None:return
                if row['state']=='TASK_QUEUED':
                    task=self.journal.store.get_task(row['task_id'])
                    if task['status'] in {'COMPLETED','FAILED','HOLD','CANCELED','EXPIRED','UNKNOWN'}:
                        self.journal.finish(rid,index,task['status'] if task['status']!='EXPIRED' else 'HOLD',
                                            reason=task['reason'] or task['status'],expected_state='TASK_QUEUED')
                        if task['status']=='COMPLETED':continue
                    return
                if row['state']=='COMPLETED':continue
                if row['state']!='READY':return
                if not allow_dispatch:return
                began=False
                try:
                    robots=await self.preflight(rid,index,call)
                    original=self.journal.guard(rid)
                    principal=SitePrincipal(original['principal_id'],'operator')
                    if call.verb=='navigate':
                        await self.execution.step(call,principal,'discord-natural:'+rid,index,
                            admission=lambda conn,task_id:self.journal.link_task(rid,index,task_id,conn))
                        return
                    native_epoch = {}
                    if call.verb in KINDS:
                        native_epoch = epoch(await self.execution.console._client(call.robot)._get(PATHS[KINDS[call.verb]]))
                        self.fence(rid,index,call)
                    self.journal.begin(rid,index,[('robot',r) for r in self.execution.resources(call)],stopping=call.verb in STOP_VERBS)
                    began=True
                    if call.verb in KINDS:
                        row=self.journal.view(rid)['steps'][index]
                        call=replace(call,body=call.body | native_epoch | {'correlation_id':row['caller_cid']})
                    paths={call.path} if call.scope=='robot' else {'/api/v1/swarm/follow','/api/fleet/formation/resume'} if call.verb.startswith('formation_') else {'/api/v1/safety/stop'}
                    with dispatch_guard(lambda:self.fence(rid,index,call),paths=paths):
                        result=await self.execution.step(call,principal,'discord-natural:'+rid,index,owner_id=row['owner_id'])
                    accepted,receipt=owner_receipt(call,result,self.execution.console.robot_ids)
                    self.journal.finish(rid,index,'ACCEPTED' if accepted is True else 'FAILED' if accepted is False else 'UNKNOWN',
                                        receipt=receipt,reason='OWNER_IDENTITY_OR_ACK_UNKNOWN' if accepted is None else None,expected_state='DISPATCHING')
                    return
                except asyncio.CancelledError:
                    if began:self.journal.finish(rid,index,'UNKNOWN',reason='DISPATCH_CANCELED_RESULT_UNKNOWN',expected_state='DISPATCHING')
                    raise
                except (ValueError,HTTPException,HubError,RobotApiError) as exc:
                    # An owner can have sent some recipients before an exception; preserve ambiguity.
                    self.journal.finish(rid,index,'UNKNOWN' if began else 'HOLD',
                        reason='COMMAND_REJECTED_OR_SCOPE_CHANGED' if began else self.reason(exc),expected_state='DISPATCHING' if began else 'READY')
                    return
                except Exception:
                    self.journal.finish(rid,index,'UNKNOWN' if began else 'HOLD',reason='COMMAND_RESULT_UNKNOWN' if began else 'PREFLIGHT_UNAVAILABLE',expected_state='DISPATCHING' if began else 'READY')
                    return

    @staticmethod
    def reason(exc):
        if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() and str(exc).isascii():return str(exc)[:96]
        return 'CURRENT_AUTHORITY_OR_OBSERVATION_HOLD'

    def reject(self,rid,exc):
        model=self.journal.jobs.peek(rid)
        with self.journal.jobs.journal._connect() as conn,conn:
            try:receipt=self.journal.jobs._receipt(conn,model,active=False)
            except HTTPException:return
            conn.execute('INSERT OR IGNORE INTO fleet_channel_execution VALUES (?,?,?,?,?,?,?,?,?)',
                (rid,model['input_hash'],model['profile_set_hash'],model['input_hash'],model['input_hash'],
                 '{}',model['input_hash'],self.journal.clock(),self.reason(exc)))
            self.journal.jobs.journal.reply_outbox.enqueue(conn,receipt,'EXECUTION:HOLD',
                '실행을 보류했습니다 · '+self.reason(exc)+'\n원문에 대상과 원하는 동작을 명확히 말씀해 주세요. 기기 명령을 보내지 않았습니다.')

    def pending(self):
        with self.journal.store._connect() as conn:
            rows=[r[0] for r in conn.execute('''SELECT j.request_id FROM fleet_channel_conversation_jobs j
                LEFT JOIN fleet_channel_execution e USING(request_id)
                WHERE (e.request_id IS NULL AND j.state='ANSWERED' AND json_extract(j.result_json,'$.answer.kind')='CONTROL')
                OR EXISTS (SELECT 1 FROM fleet_channel_execution_steps s
                    WHERE s.request_id=j.request_id AND (s.state='TASK_QUEUED'
                        OR (s.state IN ('ACCEPTED','RUNNING','UNKNOWN') AND (json_extract(s.receipt_json,'$.operation.run_id') IS NOT NULL
                            OR json_type(s.receipt_json,'$.operations')='array' OR json_type(s.receipt_json,'$.robots')='array'
                            OR (json_extract(s.receipt_json,'$.rpc_acknowledged')=1 AND
                                (json_type(s.receipt_json,'$.navigation')='text' OR json_extract(s.receipt_json,'$.role')='none'))))
                        OR (s.state='READY' AND e.reason IS NULL)))
                ORDER BY (j.request_id>?) DESC,j.request_id LIMIT 10''',(self._cursor,))]
            if rows:self._cursor=rows[-1]
            return rows
