"""Opt-in, read-only incident model loop consuming existing immutable polls."""
import asyncio
from dataclasses import asdict
import hashlib
import json
import time
import uuid

from core_common.protocol.schemas import FleetJudgmentReceipt
from rosy.decision.deliberation import Problem, canonical
from rosy.decision.deliberation.judgment import Judgment, judgment
from rosy.decision.deliberation.profiles import ModelProfile, bind_profile, incident_profiles
from rosy_situation.assessment import Assessment, AssessmentInput, EvidenceRef
from rosy_situation.snapshot_assessment import POLICY
from fleet.server.incident_deliberation import FleetBaseline
from ..closure import observe_closure
from ..contract import CaseBudget, CaseScope, micros
from ..ledger.receipt import model_receipt
from rosy.decision.deliberation.contracts.billing import call_cost_evidence, RejectedJudgment
from rosy.decision.deliberation.calibration_selection import select_calibrated
from ..recovery_candidates import RecoveryCandidates, observed_recovery


class IncidentCaseWorker:
    def __init__(self, store, observation, board, *, profiles, providers, admission,
                 current_profiles, human_owned, budget, final_handoff, clock=time.time,
                 enabled=False, baseline=None, calibration_artifacts=None, approved_artifacts=None,
                 new_case_admission=None, routed=False, recovery_enabled=False, recovery_submit=None):
        profiles = incident_profiles(profiles)
        if (type(enabled) is not bool or len(providers) != len(profiles)
                or any(not callable(port) for port in (admission, current_profiles, human_owned, budget, final_handoff))
                or any(getattr(provider, 'profile', None) != profile for provider, profile in zip(providers, profiles))):
            raise ValueError('EXPLICIT_INCIDENT_WORKER_CONTRACT_REQUIRED')
        if ((calibration_artifacts is None) != (approved_artifacts is None)
                or calibration_artifacts is not None and not all(callable(p) for p in (calibration_artifacts, approved_artifacts))):
            raise ValueError('EXPLICIT_CALIBRATION_PORTS_REQUIRED')
        self.store, self.observation, self.board = store, observation, board
        self.profiles, self.providers, self.admission = profiles, tuple(providers), admission
        self.current_profiles, self.human_owned, self.budget = current_profiles, human_owned, budget
        self.final_handoff, self.clock, self.enabled, self.baseline = final_handoff, clock, enabled, baseline
        self.calibration_artifacts, self.approved_artifacts = calibration_artifacts, approved_artifacts
        if type(recovery_enabled) is not bool:
            raise ValueError('EXPLICIT_RECOVERY_MODE_REQUIRED')
        self.recovery_candidates = RecoveryCandidates(store) if recovery_enabled else None
        if recovery_submit is not None and (not recovery_enabled or not callable(recovery_submit)):
            raise ValueError('EXPLICIT_RECOVERY_SUBMISSION_PORT_REQUIRED')
        self.recovery_submit = recovery_submit
        if type(routed) is not bool: raise ValueError('EXPLICIT_ROUTING_MODE_REQUIRED')
        self.routed = routed
        if new_case_admission is not None and not callable(new_case_admission):
            raise ValueError('EXPLICIT_NEW_CASE_ADMISSION_REQUIRED')
        self.new_case_admission = new_case_admission
        self.profile_sha256 = hashlib.sha256(canonical([asdict(p) for p in profiles]).encode()).hexdigest()
        self._snapshot, self._task, self._waiting = None, None, {}
        self._latest_snapshot = None
        self._worker_id, self._closed = uuid.uuid4().hex, False
        self._submitted, self._shutdown_task = set(), None

    @property
    def idle(self):
        return self._task is None or self._task.done()

    def _admitted(self):
        return (self.enabled and not self._closed and self.current_profiles() == self.profiles
                and all(self.admission(p, provider) is True for p, provider in zip(self.profiles, self.providers)))

    def _problem(self, assessment):
        if (not isinstance(assessment, Assessment) or assessment.necessity != 'INTERVENE'
                or not assessment.applies_to(assessment.request, now=self.clock(), policy_revision=POLICY.revision)
                or assessment.request.condition != 'blocked' or assessment.request.owner != 'core'
                or not assessment.request.case_id or not assessment.request.evidence
                or any(e.source != 'core_state' for e in assessment.request.evidence)):
            raise ValueError('INCIDENT_NOT_ADMITTED')
        request = assessment.request
        if self.human_owned(request.subject_id, request.case_id) is not False:
            raise ValueError('INCIDENT_HUMAN_OWNED')
        baseline = self.baseline(assessment) if self.baseline is not None else None
        if baseline is not None and (type(baseline) is not FleetBaseline
                or baseline.request != request or baseline.policy_revision != assessment.policy_revision):
            raise ValueError('FLEET_BASELINE_CHANGED')
        context = observed_recovery(self._latest_snapshot, request.subject_id, request.case_id, request.revision) if self.recovery_candidates else None
        choices = ('reobserve', 'human', 'back_and_retry') if context else ('reobserve', 'human')
        facts = canonical(dict(state='blocked', recovery=context)) if context else '{"state":"blocked"}'
        return Problem(request.subject_id, request.case_id, request.revision, 'line_follow',
            min(e.observed_at for e in request.evidence), tuple(e.reference for e in request.evidence),
            choices, 'INTERVENE', facts_json=facts,
            fleet_choice=baseline.choice if baseline is not None else None)

    def prepare_receipt(self, connection, receipt):
        """Called by the outbox in its existing transaction, before any OPEN enqueue."""
        try:
            if not self._admitted(): return False
            checked = FleetJudgmentReceipt.model_validate(receipt).model_dump(mode='json')
            checked.pop('action_admissible')
            checked.pop('shadow')
            request = checked.pop('request')
            request['evidence'] = tuple(EvidenceRef(**e) for e in request['evidence'])
            problem = self._problem(Assessment(request=AssessmentInput(**request), **checked))
            scope = self._scope(problem)
            existing = connection.execute('SELECT budget_json FROM fleet_incident_v2_cases WHERE subject_id=? AND case_id=?',
                                          (scope.subject_id, scope.case_id)).fetchone()
            if existing is None and not self._new_case_allowed(scope): return False
            budget = CaseBudget(**json.loads(existing[0])) if existing else self.budget(scope)
            self._check_budget(budget)
            case = self.store.begin_case(scope, budget, connection=connection,
                                         initial_revision=problem.generation, worker_id=self._worker_id, routed=self.routed)
            return case['state'] == 'ACTIVE' and self.clock() < case['deadline']
        except (ValueError, TypeError, KeyError):
            return False

    def _scope(self, problem):
        return CaseScope(problem.subject_id, problem.case_id, 'core', self.profile_sha256, POLICY.revision)

    def _owns_scope(self, scope):
        return scope.owner_id == 'core' and scope.profile_sha256 == self.profile_sha256

    def _new_case_allowed(self, scope):
        # shortcut: this local fence needs transactional assignment before profile rollover.
        if self.new_case_admission is None: return True
        try: return self.new_case_admission(scope) is True
        except Exception: return False

    def _check_budget(self, budget):
        if (type(budget) is not CaseBudget or dict(budget.role_limits) != {p.role: p.max_calls for p in self.profiles}
                or budget.max_calls > sum(p.max_calls for p in self.profiles)):
            raise ValueError('EXPLICIT_PROFILE_ROLE_BUDGET_REQUIRED')

    def feed(self, snapshot):
        if not self.enabled or self._closed: return
        # Copy public CORE state only; no image, credential or transport data is retained.
        rows = snapshot.get('robots') if type(snapshot) is dict else None
        if type(rows) is not list or len(rows) > 64: raise ValueError('INCIDENT_MAILBOX_LIMIT')
        clean = []
        for row in rows:
            state = row.get('state') or {}
            clean.append(dict(robot_id=row.get('robot_id'), online=row.get('online'),
                state={key: state.get(key) for key in ('seq', 'timestamp', 'line_follow')}))
        self._snapshot = json.loads(canonical({'robots': clean}))
        self._latest_snapshot = self._snapshot
        if self.idle: self._task = asyncio.create_task(self._drain())

    async def _db(self, method, *args, **kwargs):
        port = method if callable(method) else getattr(self.store, method)
        task = asyncio.create_task(asyncio.to_thread(port, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.shield(task)
            raise

    async def _drain(self):
        while self._snapshot is not None and not self._closed:
            snapshot, self._snapshot = self._snapshot, None
            for scope in await self._db('pending_handoffs'):
                if not self._owns_scope(scope): continue
                current = self.board.intervention_assessment(scope.subject_id)
                if (isinstance(current, Assessment) and current.request.case_id == scope.case_id
                        and current.request.owner == scope.owner_id
                        and current.applies_to(current.request, now=self.clock(), policy_revision=POLICY.revision)
                        and self.human_owned(scope.subject_id, scope.case_id) is False):
                    await self._finish(scope, (await self._db('case', scope))['reason'])
            scopes = tuple(scope for scope in await self._db('active_scopes') if self._owns_scope(scope))
            for scope in scopes:
                await self._process(scope, snapshot)
            for row in snapshot['robots']:
                assessment = self.board.intervention_assessment(row['robot_id'])
                try:
                    if not self._admitted(): continue
                    problem = self._problem(assessment)
                    scope = self._scope(problem)
                    if scope in scopes: continue
                    try: case = await self._db('case', scope)
                    except ValueError:
                        if not self._new_case_allowed(scope): continue
                        selected = self.budget(scope)
                        self._check_budget(selected)
                        case = await self._db('begin_case', scope, selected,
                                              initial_revision=problem.generation, worker_id=self._worker_id, routed=self.routed)
                    if case['state'] != 'ACTIVE': continue
                    await self._process(scope, snapshot)
                except (ValueError, TypeError, KeyError):
                    continue

    async def _finish(self, scope, reason):
        if not self._owns_scope(scope): return
        case = await self._db('case', scope)
        if case['state'] == 'ACTIVE': case = await self._db('close_case', scope, state='HOLD', reason=reason)
        summary = await self._db('final_summary', scope)
        try:
            if await self.final_handoff(scope, summary) is True: await self._db('handoff_queued', scope)
        except (ValueError, OSError): pass

    def _fresh(self, problem):
        try:
            return self._admitted() and self._problem(self.board.intervention_assessment(problem.subject_id)) == problem
        except (ValueError, TypeError, KeyError): return False

    def _review_needed(self, problem, bound, checked):
        if checked is None: return True
        data = checked.payload
        if 'unsafe' in data['objections']: return False
        if (data['objections'] or data['missing_evidence']
                or problem.fleet_choice is not None and checked.choice != problem.fleet_choice): return True
        if self.calibration_artifacts is None: return False
        try:
            quality = select_calibrated(problem, bound, checked, self.calibration_artifacts(bound.profile),
                approved_artifacts=self.approved_artifacts(), current_profile=bound.profile)
            return quality['eligible'] is not True
        except Exception: return True

    async def _process(self, scope, snapshot):
        if not self._owns_scope(scope): return
        case = await self._db('case', scope)
        if scope.policy_revision != POLICY.revision or scope.owner_id != 'core':
            await self._finish(scope, 'POLICY_CHANGED'); return
        if self.current_profiles() != self.profiles or scope.profile_sha256 != self.profile_sha256:
            await self._finish(scope, 'PROFILE_CHANGED'); return
        if self.human_owned(scope.subject_id, scope.case_id) is not False:
            await self._db('close_case', scope, state='HOLD', reason='INCIDENT_HUMAN_OWNED'); return
        try:
            proof = observe_closure(scope, requested_at=case['started_at'], board=self.board, snapshot=snapshot,
                                    human_owned=self.human_owned, now=self.clock())
            await self._db('observed_closure', scope, proof); return
        except (ValueError, KeyError, TypeError): pass
        if await self._db('requires_resume_admission', scope, self._worker_id):
            await self._finish(scope, 'READ_CONTINUATION_NOT_ADMITTED'); return
        if self.clock() >= case['deadline']:
            await self._finish(scope, 'CASE_DEADLINE_EXHAUSTED'); return
        try: problem = self._problem(self.board.intervention_assessment(scope.subject_id))
        except (ValueError, TypeError, KeyError): return
        if (problem.subject_id, problem.case_id) != (scope.subject_id, scope.case_id):
            await self._finish(scope, 'INCIDENT_CHANGED'); return
        waiting = self._waiting.get(scope)
        if waiting and waiting[0] == problem.generation: return
        try:
            if waiting:
                attempt = await self._reserve(scope, problem, 'observation', 'read', 0)
                try:
                    if not self._fresh(problem): raise ValueError('INCIDENT_SCOPE_CHANGED')
                    self.observation.read(problem, {**waiting[1], 'evidence_ids': list(problem.evidence_ids)}, snapshot=snapshot)
                except (ValueError, TypeError, KeyError):
                    await self._db('complete', scope, attempt, worker_id=self._worker_id, state='REJECTED',
                                   actual_cost_usd=0, summary={'reason': 'OBSERVATION_REJECTED'})
                    raise
                await self._db('complete', scope, attempt, worker_id=self._worker_id, state='COMPLETED',
                               actual_cost_usd=0, summary={'reason': 'NEW_CORE_OBSERVATION', 'observation_revision': problem.generation})
            primary = await self._call(scope, problem, 0, ())
            if primary is None: return
            checked, bound = primary
            remaining = (await self._db('case', scope))['deadline'] - self.clock()
            try:
                async with asyncio.timeout(max(0, remaining)):
                    review = await asyncio.to_thread(self._review_needed, problem, bound, checked)
            except TimeoutError:
                await self._finish(scope, 'CASE_BUDGET_EXHAUSTED'); return
            if self.human_owned(scope.subject_id, scope.case_id) is not False:
                await self._db('close_case', scope, state='HOLD', reason='INCIDENT_HUMAN_OWNED'); return
            if not self._fresh(problem): return
            if review:
                if len(self.profiles) == 1: await self._finish(scope, 'REVIEW_PROVIDER_NOT_CONFIGURED'); return
                prior = ((bound, checked),) if checked is not None and (problem.fleet_choice is not None or self.calibration_artifacts is not None) else ()
                secondary = await self._call(scope, problem, 1, prior)
                if secondary is None: return
                if secondary[0] is not None: checked, bound = secondary
            step = checked.payload['next_step'] if checked is not None else None
            if step and step['tool_name'] == 'get_incident_status':
                self._waiting[scope] = (problem.generation, step)
            elif step and step['tool_name'] == 'propose_lane_back' and self.recovery_candidates is not None:
                if not self._fresh(problem): return
                attempt = hashlib.sha256(canonical([problem.digest, 'model', bound.profile.profile_id]).encode()).hexdigest()
                await self._db(self.recovery_candidates.propose, scope, attempt, worker_id=self._worker_id)
                if self.recovery_submit is not None:
                    if await self.recovery_submit(scope, attempt, problem, self) is not True:
                        await self._finish(scope, 'RECOVERY_SUBMISSION_NOT_CONFIRMED'); return
                self._waiting[scope] = (problem.generation, dict(tool_name='get_incident_status', arguments={},
                                                              evidence_ids=list(problem.evidence_ids)))
            else: await self._finish(scope, 'NO_ADMITTED_READ_OR_REVIEW')
        except ValueError as error:
            if str(error) in {'ATTEMPT_ALREADY_RESERVED', 'CASE_ATTEMPT_INFLIGHT'}: return
            await self._finish(scope, str(error) if str(error) in {'CASE_BUDGET_EXHAUSTED', 'CASE_ROLE_BUDGET_EXHAUSTED'} else 'READ_OR_PROVIDER_UNAVAILABLE')

    async def _reserve(self, scope, problem, kind, role, cost):
        if not self._fresh(problem): raise ValueError('INCIDENT_SCOPE_CHANGED')
        attempt = hashlib.sha256(canonical([problem.digest, kind, role]).encode()).hexdigest()
        await self._db('reserve', scope, attempt_id=attempt, input_hash=problem.digest,
                       observation_revision=problem.generation, kind=kind, max_cost_usd=cost, worker_id=self._worker_id,
                       role=next(p.role for p in self.profiles if p.profile_id == role) if kind == 'model' else None)
        if not self._fresh(problem):
            await self._db('mark_submitting', scope, attempt, worker_id=self._worker_id)
            await self._db('complete', scope, attempt, worker_id=self._worker_id,
                           state='REJECTED', actual_cost_usd=0, summary={'reason': 'INCIDENT_SCOPE_CHANGED'})
            raise ValueError('INCIDENT_SCOPE_CHANGED')
        await self._db('mark_submitting', scope, attempt, worker_id=self._worker_id)
        return attempt

    async def _call(self, scope, problem, index, prior):
        profile, provider = self.profiles[index], self.providers[index]
        bound = bind_profile(problem, profile, provider.adapter, required_modalities=('text',))
        attempt = await self._reserve(scope, problem, 'model', profile.profile_id, profile.max_cost_usd)
        case = await self._db('case', scope)
        remaining = min(profile.timeout_s, case['deadline'] - self.clock())
        cost, checked, state = None, None, 'UNKNOWN'
        cost_evidence, evidence_error, rejected_unsafe = None, False, False
        try:
            if remaining <= 0 or not self._fresh(problem): raise ValueError('INCIDENT_SCOPE_CHANGED')
            async with asyncio.timeout(remaining):
                self._submitted.add(attempt)
                invocation = await provider(problem, bound, prior, remaining, budget_usd=profile.max_cost_usd)
                result, cost = invocation
            micros(cost)
            state = 'REJECTED'
            checked = judgment(problem, bound, result.payload if type(result) is Judgment else result)
            cost_evidence, evidence_error = call_cost_evidence(invocation, problem, bound, checked, cost)
            if self._fresh(problem) and not evidence_error: state = 'COMPLETED'
        except asyncio.CancelledError:
            await asyncio.shield(self._db('complete', scope, attempt, worker_id=self._worker_id,
                state='UNKNOWN', actual_cost_usd=cost, summary={'reason': 'WORKER_CANCELLED'}))
            await asyncio.shield(self._finish(scope, 'WORKER_CANCELLED'))
            raise
        except RejectedJudgment as error:
            try:
                if (type(error) is not RejectedJudgment or error.bound != bound
                        or type(error.unsafe) is not bool or micros(error.cost_usd) > micros(profile.max_cost_usd)):
                    raise ValueError('REJECTED_CALL_CONTEXT_CHANGED')
                error.bound.validate(problem, profile)
                cost, state, rejected_unsafe = error.cost_usd, 'REJECTED', error.unsafe
            except (ValueError, TypeError): cost, state = None, 'UNKNOWN'
        except Exception:
            if cost is not None:
                try: micros(cost)
                except ValueError: cost, state = None, 'UNKNOWN'
        summary = {'reason': 'MODEL_CHECKED' if state == 'COMPLETED' else 'MODEL_RESULT_REJECTED',
                   'observation_revision': problem.generation}
        if evidence_error: summary['reason'] = 'COST_EVIDENCE_REJECTED'
        if state == 'COMPLETED' and checked is not None:
            summary.update(verdict=checked.payload['verdict'], choice=checked.choice,
                           receipt_sha256=hashlib.sha256(checked.payload_json.encode()).hexdigest())
        trace = None
        if checked is not None and state != 'UNKNOWN' and not evidence_error:
            try: trace = model_receipt(scope, problem, bound, checked, profiles=self.profiles, cost_evidence=cost_evidence)
            except (ValueError, TypeError):
                state, summary = 'REJECTED', {'reason': 'MODEL_TRACE_REJECTED'}
        completed = await self._db('complete', scope, attempt, worker_id=self._worker_id, state=state,
                                  actual_cost_usd=cost, summary=summary, model_receipt=trace)
        updated = await self._db('case', scope)
        if updated['state'] != 'ACTIVE':
            await self._finish(scope, updated['reason']); return None
        if rejected_unsafe:
            await self._finish(scope, 'MODEL_UNSAFE_REJECTION'); return None
        if completed['state'] != 'COMPLETED' and checked is not None:
            if self._fresh(problem): await self._finish(scope, 'COST_EVIDENCE_REJECTED' if evidence_error else 'MODEL_TRACE_REJECTED')
            return None
        if self.human_owned(scope.subject_id, scope.case_id) is not False:
            await self._db('close_case', scope, state='HOLD', reason='INCIDENT_HUMAN_OWNED'); return None
        if not self._fresh(problem): return None
        return checked, bound

    async def aclose(self):
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(self._shutdown())
        cancelled = False
        while not self._shutdown_task.done():
            try: await asyncio.shield(self._shutdown_task)
            except asyncio.CancelledError: cancelled = True
        self._shutdown_task.result()
        if cancelled: raise asyncio.CancelledError

    async def _shutdown(self):
        self._closed, self._snapshot = True, None
        self._latest_snapshot = None
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        for scope in await self._db('cancel_owned', self._worker_id, submitted_attempt_ids=self._submitted):
            await self._finish(scope, 'WORKER_CANCELLED')
