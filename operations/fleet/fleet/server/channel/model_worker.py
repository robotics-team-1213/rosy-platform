"""One bound read-only model job at a time; CORE intervention remains separate."""
import asyncio
from dataclasses import asdict
import hashlib
import json
import math
import time

from fastapi import HTTPException
from rosy.decision.deliberation import Problem, canonical
from rosy.decision.deliberation.contracts.billing import call_cost_evidence
from rosy.decision.deliberation.judgment import Judgment, judgment
from rosy.decision.deliberation.profiles import BoundProfile, ModelProfile

from .deliberation import status_problem, status_snapshot


class ChannelModelWorker:
    def __init__(self,jobs,snapshot,profiles,providers,*,admission,current_profiles,clock=time.time,observation_guard=None):
        if (type(profiles) is not tuple or len(profiles) not in (1,2)
                or len(providers)!=len(profiles) or any(type(p) is not ModelProfile
                or p.domains!=('fleet_status',) or p.max_calls!=1 for p in profiles)
                or tuple(p.role for p in profiles)!=('primary','reviewer')[:len(profiles)]
                or hashlib.sha256(canonical([asdict(p) for p in profiles]).encode()).hexdigest()!=jobs.profile_set_hash):
            raise ValueError('EXACT_STATUS_PROFILE_SET_REQUIRED')
        self.jobs,self.snapshot,self.profiles,self.providers=jobs,snapshot,profiles,providers
        self.admission,self.current_profiles,self.clock=admission,current_profiles,clock
        self.observation_guard=observation_guard
        self._lock=asyncio.Lock()

    async def _db(self,method,*args,**kwargs):
        task=asyncio.create_task(asyncio.to_thread(getattr(self.jobs,method),*args,**kwargs))
        try:return await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.shield(task)
            raise

    def _ready(self,index):
        return (self.current_profiles()==self.profiles
                and self.admission(self.profiles[index],self.providers[index]) is True)

    async def _current(self,request_id,basis):
        if self.current_profiles()!=self.profiles:return False
        current=await self.snapshot()
        await self._db('guard',request_id)
        return status_snapshot(current)==basis and self.current_profiles()==self.profiles

    async def _finish(self,request_id,state,result,summary,basis=None):
        guard=None if basis is None or self.observation_guard is None else lambda:self.observation_guard(basis)
        try:await self._db('finish',request_id,state=state,result=result,summary=summary,observation_guard=guard)
        except HTTPException as exc:
            if exc.detail=='CHANNEL_OBSERVATION_CHANGED':
                await self._finish(request_id,'HOLD',{'reason':'OBSERVATION_CHANGED','action_admissible':False},
                    f'ROSY 상태 검토 · {request_id}\n관측이 바뀌거나 오래되어 결과 적용을 보류했습니다. 실행 승인 아님.')
            else:await self._db('abandon',request_id,state='SUPERSEDED',reason='OWNER_OR_SCOPE_CHANGED')

    async def step(self,receipt):
        async with self._lock:
            request_id=receipt['request_id']
            try:
                existing=await self._db('peek',request_id)
                if existing['state'] not in ('PENDING','RUNNING'):return
                # An in-flight attempt is not a new model request, even in another process.
                if existing['state']=='RUNNING':return
            except HTTPException as exc:
                if exc.status_code!=404:raise
            try:
                snapshot=await self.snapshot();basis=status_snapshot(snapshot)
                problem=status_problem(receipt,snapshot,now=snapshot.get('observed_at',self.clock()))
            except (ValueError,TypeError,KeyError):
                await self._db('reject',receipt)
                return
            try:
                await self._db('stage',receipt,problem,snapshot)
                stored=await self._db('peek',request_id)
                problem=Problem(**json.loads(stored['problem_json']))
                basis=json.loads(stored['snapshot_json'])
                if not 0 <= self.clock()-problem.observed_at <= 3:
                    await self._finish(request_id,'HOLD',{'reason':'STALE_INPUT','action_admissible':False},
                        f'ROSY 상태 검토 · {request_id}\n관측이 오래되어 보류했습니다. 실행 승인 아님.')
                    return
                if not self._ready(0):
                    await self._finish(request_id,'HOLD',{'reason':'MODEL_NOT_ADMITTED','action_admissible':False},
                        f'ROSY 읽기 전용 판단 · {request_id}\n숙고형 제공자 미수용 · 실행 승인이나 장치 명령을 만들지 않았습니다.')
                    return
                results=[];prior=()
                for index,(profile,provider) in enumerate(zip(self.profiles,self.providers)):
                    if index and not results[-1]['review_required']:break
                    if index and not self._ready(index):
                        await self._finish(request_id,'HOLD',{'models':results,'reason':'REVIEWER_NOT_ADMITTED','action_admissible':False},
                            f'ROSY 상태 검토 · {request_id}\n추가 숙고가 필요하지만 검토 모델이 미수락 상태입니다. 실행 승인 아님.',basis)
                        return
                    if not await self._current(request_id,basis) or not self._ready(index):
                        await self._finish(request_id,'HOLD',{'reason':'SCOPE_CHANGED','action_admissible':False},
                            f'ROSY 읽기 전용 판단 · {request_id}\n관측·설정 변경으로 보류했습니다. 실행 승인 아님.')
                        return
                    attempt=await self._db('reserve',request_id,profile.role)
                    if not await self._current(request_id,basis) or not self._ready(index):
                        await self._finish(request_id,'HOLD',{'reason':'SCOPE_CHANGED','action_admissible':False},
                            f'ROSY 상태 검토 · {request_id}\n관측 또는 권한이 바뀌어 보류했습니다. 실행 승인 아님.')
                        await self._db('abandon',request_id,state='HOLD',reason='SCOPE_CHANGED')
                        return
                    # No await between the final authority guard and provider entry.
                    self.jobs.guard(request_id)
                    if self.observation_guard is not None and not self.observation_guard(basis):
                        await self._db('abandon',request_id,state='HOLD',reason='OBSERVATION_CHANGED')
                        return
                    bound=BoundProfile(profile,problem.digest)
                    try:
                        remaining=min(profile.timeout_s,attempt['deadline']-self.clock())
                        if remaining<=0:raise TimeoutError()
                        raw=await provider(problem,bound,prior,remaining,budget_usd=profile.max_cost_usd,
                                           missing_allowlist=('core_state','network','camera','map'))
                        checked,cost=raw
                        if (type(checked) is not Judgment or type(cost) not in (int,float)
                                or not math.isfinite(cost) or cost<0):raise ValueError('INVALID_MODEL_RECEIPT')
                        checked=judgment(problem,bound,checked.payload,missing_allowlist=('core_state','network','camera','map'))
                        evidence,evidence_error=call_cost_evidence(raw,problem,bound,checked,cost)
                        record={'profile_id':profile.profile_id,'model_id':profile.model_id,
                                'judgment':checked.payload,'action_admissible':False,
                                'cost_evidence':None if evidence is None else evidence.payload}
                        await self._db('record_attempt',request_id,profile.role,state='RESULT',result=record,
                            known_cost_usd=cost,input_hash=attempt['input_hash'],profile_set_hash=attempt['profile_set_hash'])
                        if (evidence_error or cost>profile.max_cost_usd
                                or profile.provider_kind!='local' and evidence is None):
                            raise ValueError('COST_EVIDENCE_UNKNOWN')
                    except asyncio.CancelledError:
                        await self._finish(request_id,'UNKNOWN',{'reason':'CANCELED_DURING_MODEL_CALL','action_admissible':False},
                            f'ROSY 상태 검토 · {request_id}\n모델 결과 불명 · 자동 재호출하지 않습니다. 실행 승인 아님.')
                        await self._db('abandon',request_id,state='UNKNOWN',reason='CANCELED_DURING_MODEL_CALL')
                        raise
                    except Exception:
                        await self._finish(request_id,'UNKNOWN',{'reason':'MODEL_RESULT_UNKNOWN','action_admissible':False},
                            f'ROSY 읽기 전용 판단 · {request_id}\n모델 결과 불명 · 자동 재호출하지 않습니다. 실행 승인 아님.')
                        await self._db('abandon',request_id,state='UNKNOWN',reason='MODEL_RESULT_UNKNOWN')
                        return
                    if not await self._current(request_id,basis):
                        await self._finish(request_id,'HOLD',{'reason':'OBSERVATION_CHANGED','action_admissible':False},
                            f'ROSY 읽기 전용 판단 · {request_id}\n관측이 변경되어 모델 결과를 적용하지 않았습니다. 실행 승인 아님.')
                        return
                    objections=checked.payload['objections']
                    results.append({**record,'review_required':checked.choice is not None
                        and bool({'conflict','insufficient_evidence'} & set(objections))})
                    prior=((bound,checked),) if checked.choice is not None else ()
                lines=[f'ROSY 읽기 전용 상태 검토 · {request_id}']
                for row in basis['robots']:
                    label='상태 미확인' if row['online'] is None else '온라인' if row['online'] else '오프라인'
                    lines.append(f"{row['robot_id']} · {label}")
                lines.append('모델: '+', '.join(r['model_id'] for r in results))
                lines.append('현재 관제 관측에 대한 검토입니다. 실행 승인·장치 성공이 아니며 명령을 보내지 않았습니다.')
                await self._finish(request_id,'ANSWERED',{'models':results,'action_admissible':False},'\n'.join(lines),basis)
            except asyncio.CancelledError:raise
            except HTTPException:
                await self._db('abandon',request_id,state='SUPERSEDED',reason='OWNER_OR_SCOPE_CHANGED')
