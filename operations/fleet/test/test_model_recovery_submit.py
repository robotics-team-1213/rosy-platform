"""Existing Fleet writer with real SQLite and HTTP; fixtures are not field acceptance."""
import asyncio
import threading
from dataclasses import replace

import httpx
import pytest

from fleet.stuck.loop import StuckResolverLoop
from fleet.stuck.board import LineStuckBoard
from fleet.stuck.resolver import StuckResolver, ResolverConfig, Answer
from fleet.swarm.transport import HttpRobotClient
from fleet.swarm.robots import RobotEndpoint
from test_operational_case_claim import opened, signed
from test_model_recovery_candidates import recovery_problem, recovery_context
from test_incident_case_worker import make_incident_worker


@pytest.mark.parametrize('change', ['none', 'hold', 'human', 'client', 'unsupported', 'disconnect', 'cancel',
    'crosswalk', 'missing_crosswalk', 'rear', 'fact', 'budget', 'retired', 'peer_unknown', 'map_lost',
    'deadline', 'uncertain', 'exhausted', 'prior_refusal'])
def test_actual_loop_model_writer_checks_final_context_and_never_repeats(tmp_path, change):
    now, store, log, scope, state, proof, _ = opened(tmp_path, generation='core:1:stamp')
    state.apply('line-back', signed(proof, 0))
    board = LineStuckBoard(log=log, clock=lambda: now[0], wall=lambda: now[0])
    resolver = StuckResolver(ResolverConfig())
    resolver.autonomous_robots = frozenset({scope.subject_id})
    calls, clients = [], {}
    row = dict(robot_id=scope.subject_id, online=True, state=dict(seq=1, timestamp='stamp',
        line_follow={'crosswalk': None, 'stuck': dict(recovery_context(), stuck_id=scope.case_id)}))
    resolver.step(now[0], [row])
    peers = []
    async def snapshot(): return {'robots': [row, *peers]}
    loop = StuckResolverLoop(snapshot, board, resolver, clients=lambda: clients, clock=lambda: now[0])
    loop.operating_state, loop.operating_grant = state, 'line-back'
    (tmp_path / 'worker').mkdir()
    _, _, _, _, _, _, worker, _, _ = make_incident_worker(tmp_path / 'worker')
    worker.store = store
    worker._fresh = lambda _: True
    problem = replace(recovery_problem(), observed_at=100, generation='core:1:stamp')
    def handler(request):
        calls.append(request.method)
        if request.method == 'GET':
            if change == 'hold': proof['report']['state'] = 'HOLD'
            if change == 'human': resolver.claim(scope.subject_id, scope.case_id)
            if change == 'client': clients.clear()
            if change == 'crosswalk': row['state']['line_follow']['crosswalk'] = {'state': 'unknown'}
            if change == 'missing_crosswalk': row['state']['line_follow'].pop('crosswalk')
            if change == 'rear': row['state']['line_follow']['stuck']['rear_state'] = 'blocked'
            if change == 'fact': row['ai_facts'] = [{'kind': 'person'}]
            if change == 'budget': resolver._chains[scope.subject_id].rule_answers = resolver.config.rule_budget
            if change == 'retired': resolver._chains[scope.subject_id].retired.add('ai')
            if change == 'peer_unknown': peers.append({'robot_id': 'peer', 'online': True, 'state': {}})
            if change == 'map_lost': row['map_pose'] = {'state': 'LOST', 'sourced': True, 'age_s': .1}
            if change == 'deadline': resolver._chains[scope.subject_id].started_at = now[0] - 61
            if change == 'uncertain': resolver._uncertain.add((scope.subject_id, 'older-case'))
            if change == 'exhausted': resolver._chains[scope.subject_id].observing = 'ai_exhausted'
            if change == 'prior_refusal':
                prior = Answer(scope.subject_id, 'older-case', 'BACK_AND_RETRY', 'model_v2')
                resolver.sent(prior, now[0])
                resolver.result(prior, code='STUCK_DECISION_REFUSED')
            return httpx.Response(200, json={'stuck': {'conditional_back': change != 'unsupported'}})
        assert state.submission(scope.subject_id, scope.case_id)['state'] == 'SUBMITTING'
        if change == 'disconnect': raise httpx.ReadError('source fixture disconnect')
        if change == 'cancel': raise asyncio.CancelledError
        return httpx.Response(200, json={'outcome': 'back'})
    async def run():
        async with httpx.AsyncClient(base_url='http://source-fixture', transport=httpx.MockTransport(handler)) as http:
            clients[scope.subject_id] = HttpRobotClient(RobotEndpoint(scope.subject_id, 'http://source-fixture', 'fake'), http=http)
            operation = loop._model_answer(scope, 'model-1', problem, worker)
            if change == 'cancel':
                with pytest.raises(asyncio.CancelledError): await operation
            else: await operation
            record = state.submission(scope.subject_id, scope.case_id)
            if change == 'none':
                assert record['state'] == 'ACK'
                assert resolver._chains[scope.subject_id].rule_answers == 1
            elif change in {'disconnect', 'cancel'}: assert record['state'] == 'UNKNOWN'
            else: assert record is None
            first = list(calls)
            await loop._model_answer(scope, 'model-1', problem, worker)
            assert 'POST' not in calls[len(first):]
        await worker.aclose()
    asyncio.run(run())


def test_fake_client_swallowing_guard_cannot_dispatch(tmp_path):
    _, store, log, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    class Fake:
        async def line_stuck_decision(self, *args, **kwargs): raise AssertionError('must not dispatch')
    async def snapshot(): return {'robots': []}
    loop = StuckResolverLoop(snapshot, LineStuckBoard(log=log), StuckResolver(ResolverConfig()), clients=lambda: {scope.subject_id: Fake()})
    loop.operating_state, loop.operating_grant = state, 'line-back'
    (tmp_path / 'worker').mkdir()
    _, _, _, _, _, _, worker, _, _ = make_incident_worker(tmp_path / 'worker')
    worker.store = store
    asyncio.run(loop._model_answer(scope, 'model-1', recovery_problem(), worker))
    assert state.submission(scope.subject_id, scope.case_id) is None


def test_model_recovery_budget_survives_restuck_in_same_chain():
    from fleet.stuck.lane_lost import ai_proposal_invalid
    resolver = StuckResolver(ResolverConfig())
    resolver.autonomous_robots = frozenset({'pinky'})
    row = dict(robot_id='pinky', online=True, state={'line_follow': {
        'crosswalk': None, 'stuck': dict(recovery_context(), stuck_id='case-0')}})
    for index in range(3):
        sid = f'case-{index}'
        row['state']['line_follow']['stuck']['stuck_id'] = sid
        resolver.step(index, [row])
        chain = resolver._chains['pinky']
        floor = ai_proposal_invalid({'decision': 'BACK_AND_RETRY'}, row,
            row['state']['line_follow']['stuck'], [row], chain, resolver.config, None)
        if index == 2:
            assert floor is not None and chain.rule_answers == resolver.config.rule_budget
            break
        assert floor is None
        action = Answer('pinky', sid, 'BACK_AND_RETRY', 'model_v2')
        resolver.sent(action, index)
        assert resolver.result(action, code=None) is None


@pytest.mark.parametrize('stop', [None, 'WAIT', 'ABORT', 'MANUAL'])
def test_real_rule_writer_shares_model_slot_and_keeps_stops_outside_it(tmp_path, stop):
    now, store, log, scope, operating, proof, _ = opened(tmp_path, generation='core:1:stamp')
    operating.apply('line-back', signed(proof, 0))
    board = LineStuckBoard(log=log, clock=lambda: now[0], wall=lambda: now[0])
    row = dict(robot_id=scope.subject_id, online=True, state=dict(seq=1, timestamp='stamp',
        line_follow=dict(mode='CAMERA_LINE', crosswalk=None, stuck=dict(recovery_context(), stuck_id=scope.case_id))))
    board.observe([row]); board.flush()
    async def snapshot(): return {'robots': [row]}
    clients, requests = {}, []
    loop = StuckResolverLoop(snapshot, board, StuckResolver(ResolverConfig()), clients=lambda: clients, clock=lambda: now[0])
    loop.operating_state, loop.operating_grant = operating, 'line-back'
    loop._resolver.autonomous_robots = frozenset({scope.subject_id})
    loop._resolver.step(now[0], [row])
    (tmp_path / 'worker').mkdir()
    _, _, _, _, _, _, worker, _, _ = make_incident_worker(tmp_path / 'worker')
    worker.store, worker._fresh = store, lambda _: True
    p = replace(recovery_problem(), generation='core:1:stamp', observed_at=100)
    async def handler(request):
        if request.method == 'GET':
            await asyncio.sleep(0)
            return httpx.Response(200, json={'stuck': {'conditional_back': True}})
        requests.append(request)
        return httpx.Response(200, json={'outcome': 'back' if stop is None else {'WAIT': 'wait', 'ABORT': 'idle', 'MANUAL': 'manual'}[stop]})
    async def run():
        async with httpx.AsyncClient(base_url='http://source-fixture', transport=httpx.MockTransport(handler)) as http:
            clients[scope.subject_id] = HttpRobotClient(RobotEndpoint(scope.subject_id, 'http://source-fixture', 'fake'), http=http)
            if stop is None:
                await asyncio.gather(loop._model_answer(scope, 'model-1', p, worker),
                    loop._answer(Answer(scope.subject_id, scope.case_id, 'BACK_AND_RETRY', 'R2'), now[0]))
                assert len(requests) == 1
                assert operating.submission(scope.subject_id, scope.case_id)['state'] == 'ACK'
            else:
                operating.claim_model(scope, 'line-back', 'model-1', expected_epoch=1, generation=p.generation, guard=lambda _: True)
                await loop._answer(Answer(scope.subject_id, scope.case_id, stop, 'R5'), now[0])
                assert len(requests) == 1
                assert operating.submission(scope.subject_id, scope.case_id)['actor'] == 'model'
        await worker.aclose()
    asyncio.run(run())


def test_owned_write_waits_through_repeated_cancellation(tmp_path):
    from fleet.stuck.submission.owned import owned
    entered, release = threading.Event(), threading.Event()
    committed = []
    def write():
        entered.set()
        if not release.wait(5): raise AssertionError('source fixture write not released')
        committed.append(True)
    async def run():
        task = asyncio.create_task(owned(write))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel(); await asyncio.sleep(.01)
            task.cancel(); await asyncio.sleep(.01)
            assert not task.done()
        finally: release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert committed == [True]
    asyncio.run(run())


@pytest.mark.parametrize('reply_kind', ['ack', 'unknown', 'revoked'])
def test_worker_real_model_writer_audit_readback_and_final_handoff(tmp_path, reply_kind):
    from dataclasses import asdict
    from fleet.incidents.automation.worker import IncidentCaseWorker
    from fleet.incidents.automation.operating.state import OperationalState
    from rosy.contracts.learning.incident_operation import REVOKE
    from test_judgment_profiles import adapter
    from test_model_recovery_candidates import recovery_payload
    from test_operational_case_claim import digest, TRUST
    from test_incident_case_worker import settled
    async def run():
        now, seen, handoffs, log, board, store, old, poll, current = make_incident_worker(tmp_path)
        await old.aclose()
        profiles = tuple(replace(p, calibration_revision='cal-1') for p in old.profiles)
        current[0] = profiles
        providers = []
        for selected in profiles:
            async def provider(p, b, *args, **kwargs): return recovery_payload(p), 0
            provider.profile, provider.adapter = selected, adapter()
            providers.append(provider)
        snapshot = poll()
        snapshot['robots'][0]['state']['line_follow']['stuck'].update(recovery_context())
        snapshot['robots'][0]['state']['line_follow']['crosswalk'] = None
        board.observe(snapshot['robots']); board.flush()
        async def gather(): return snapshot
        clients, posts = {}, []
        resolver = StuckResolver(ResolverConfig()); resolver.autonomous_robots = frozenset({'pinky'})
        resolver.step(now[0], snapshot['robots'])
        loop = StuckResolverLoop(gather, board, resolver, clients=lambda: clients, clock=lambda: now[0])
        report = dict(schema='rosy.incident.operational_acceptance/1', state='PASS_FOR_OPERATION',
            missing=[], field_accepted=True, truth_admitted=True)
        binding = dict(profile_set_sha256=digest([asdict(p) for p in profiles]), full_profile_sha256=digest(asdict(profiles[0])),
            model_revision=profiles[0].model_revision, calibration_sha256='c'*64, domain='line_follow', action='BACK_AND_RETRY',
            action_contract='rosy.line_stuck.conditional_back/1', policy_revision=old._scope(old._problem(board.intervention_assessment('pinky'))).policy_revision,
            installation_sha256='d'*64, evaluation_sha256=digest(report), coverage_sha256='f'*64,
            limits_sha256='1'*64, truth_sha256='2'*64, evaluation_state='REVIEWED_FOR_OPERATION')
        proof = dict(binding=binding, report=report, profiles=[asdict(p) for p in profiles], profile=asdict(profiles[0]),
            approved_calibrations={'cal-1':'c'*64})
        operating = OperationalState(store, trusted=lambda: TRUST, evidence=lambda _: proof)
        operating.apply('line-back', signed(proof, 0))
        loop.operating_state, loop.operating_grant = operating, 'line-back'
        worker = IncidentCaseWorker(store, old.observation, board, profiles=profiles, providers=tuple(providers),
            admission=old.admission, current_profiles=lambda: profiles, human_owned=old.human_owned,
            budget=old.budget, final_handoff=old.final_handoff, clock=lambda: now[0], enabled=True,
            recovery_enabled=True, recovery_submit=loop._model_answer)
        def handler(request):
            if request.method == 'GET': return httpx.Response(200, json={'stuck': {'conditional_back':True}})
            posts.append(True)
            if reply_kind == 'unknown': raise httpx.ReadError('synthetic lost reply')
            if reply_kind == 'revoked': operating.apply('line-back', signed(proof, 1, REVOKE))
            return httpx.Response(200, json={'outcome':'back'})
        async with httpx.AsyncClient(base_url='http://source-fixture', transport=httpx.MockTransport(handler)) as http:
            clients['pinky'] = HttpRobotClient(RobotEndpoint('pinky', 'http://source-fixture', 'fake'), http=http)
            worker.feed(snapshot); await settled(worker)
            scope = worker._scope(worker._problem(board.intervention_assessment('pinky')))
            assert posts == [True]
            assert any(a.get('rule') == 'model_v2' for a in board.answers())
            if reply_kind == 'ack':
                assert operating.submission('pinky', 'lane-1')['state'] == 'ACK' and not handoffs
                now[0] = 103
                snapshot = poll(2, normal=True)
                worker.feed(snapshot); await settled(worker)
                assert store.case(scope)['reason'] == 'RESOLVED_OBSERVED'
                closure = store.observed_closure(scope)
                assert closure['action_credit'] == 'UNVERIFIED'
                assert log.reports(1)[0]['closure']['status'] == 'CLEARANCE_OBSERVED'
            else:
                assert operating.submission('pinky', 'lane-1')['state'] == 'UNKNOWN'
                assert len(handoffs) == 1 and store.case(scope)['reason'] == 'RECOVERY_SUBMISSION_NOT_CONFIRMED'
                assert ('pinky', 'lane-1') in log.uncertain_motion()
            worker.feed(snapshot); await settled(worker)
            assert posts == [True]
        await worker.aclose()
    asyncio.run(run())
