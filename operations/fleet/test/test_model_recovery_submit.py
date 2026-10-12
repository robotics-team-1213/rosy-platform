"""Existing Fleet writer with real SQLite and HTTP; fixtures are not field acceptance."""
import asyncio
from dataclasses import replace

import httpx
import pytest

from fleet.stuck.loop import StuckResolverLoop
from fleet.stuck.board import LineStuckBoard
from fleet.stuck.resolver import StuckResolver, ResolverConfig
from fleet.swarm.transport import HttpRobotClient
from fleet.swarm.robots import RobotEndpoint
from test_operational_case_claim import opened, signed
from test_model_recovery_candidates import recovery_problem, recovery_context
from test_incident_case_worker import make_incident_worker


@pytest.mark.parametrize('change', ['none', 'hold', 'human', 'client', 'unsupported', 'disconnect', 'cancel'])
def test_actual_loop_model_writer_checks_final_context_and_never_repeats(tmp_path, change):
    now, store, log, scope, state, proof, _ = opened(tmp_path, generation='core:1:stamp')
    state.apply('line-back', signed(proof, 0))
    board = LineStuckBoard(log=log, clock=lambda: now[0], wall=lambda: now[0])
    resolver = StuckResolver(ResolverConfig(), autonomous_robots={scope.subject_id})
    calls, clients = [], {}
    row = dict(robot_id=scope.subject_id, online=True, state=dict(seq=1, timestamp='stamp',
        line_follow={'stuck': dict(recovery_context(), stuck_id=scope.case_id)}))
    async def snapshot(): return {'robots': [row]}
    loop = StuckResolverLoop(snapshot, board, resolver, clients=lambda: clients, clock=lambda: now[0])
    loop.operating_state, loop.operating_grant = state, 'line-back'
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
            if change == 'none': assert record['state'] == 'ACK'
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
    _, _, _, _, _, _, worker, _, _ = make_incident_worker(tmp_path / 'worker')
    worker.store = store
    asyncio.run(loop._model_answer(scope, 'model-1', recovery_problem(), worker))
    assert state.submission(scope.subject_id, scope.case_id) is None
