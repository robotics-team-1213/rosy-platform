"""Explicit Console navigation shares the Discord/HTTP Task owner; no devices."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core_common.protocol.assistant import AssistantMessage
from fleet.server.assistant.journal import AssistantJournal
from fleet.server.site_auth import SitePrincipal
from test_channel_natural_execution import fixture


def execution_fixture(tmp_path):
    from fleet.server.assistant.execution import AssistantExecution
    from core_common.protocol.assistant import AssistantNavigation
    f = fixture(tmp_path)
    journal = AssistantJournal(f.store._connect, clock=lambda:f.clock[0])
    journal.submit('op', AssistantMessage(request_id='console-1', conversation_id='c1',
        text='Move rosy_40 to the selected point', selected_robot_id='rosy_40'), admitted=True)
    journal.start('op', 'console-1')
    journal.finish('op', 'console-1', state='ANSWERED', response='Use the work view', kind='CONTROL')
    enabled = [True]
    service = SimpleNamespace(journal=journal, admitted=lambda:True, clock=lambda:f.clock[0])
    adapter = AssistantExecution(service, f.worker.execution, enabled=lambda:enabled[0])
    body = AssistantNavigation(robot_id='rosy_40', x=1., y=2., yaw=0.)
    return f, adapter, body, enabled, journal


def test_console_and_discord_share_one_task_owner_and_separate_keys(tmp_path):
    f, adapter, body, _, _ = execution_fixture(tmp_path)
    owner = f.service.channel_admission
    principal = SitePrincipal('op', 'operator')
    first = asyncio.run(adapter.submit(principal, 'console-1', body, authorized=lambda:True))
    duplicate = asyncio.run(adapter.submit(principal, 'console-1', body, authorized=lambda:True))
    assert first['task']['task_id'] == duplicate['task']['task_id']
    asyncio.run(f.worker.step(f.receipt['request_id']))
    discord = f.journal.view(f.receipt['request_id'])['steps'][0]
    assert discord['task_id'] != first['task']['task_id']
    assert f.service.channel_admission == owner
    assert not f.writes
    assert first['task']['actor_id'] == 'op' and first['task']['source'] == 'operator'


@pytest.mark.parametrize('change', ['disabled', 'unauthorized', 'expired', 'other_robot', 'other_user', 'not_control'])
def test_explicit_navigation_refuses_changed_authority_or_origin(tmp_path, change):
    f, adapter, body, enabled, journal = execution_fixture(tmp_path)
    principal = SitePrincipal('op', 'operator')
    if change == 'disabled': enabled[0] = False
    if change == 'expired': f.clock[0] += 31
    if change == 'other_robot': body = body.model_copy(update={'robot_id':'rosy_41'})
    if change == 'other_user': principal = SitePrincipal('another', 'operator')
    if change == 'not_control':
        with f.store._connect() as conn, conn:
            conn.execute("UPDATE fleet_assistant_requests SET kind='STATUS'")
    with pytest.raises(HTTPException):
        asyncio.run(adapter.submit(principal, 'console-1', body, authorized=lambda:change != 'unauthorized'))
    assert not f.store.queued_task_ids() and not f.writes


def test_changed_coordinates_conflict_and_restart_keeps_original_task(tmp_path):
    f, adapter, body, _, journal = execution_fixture(tmp_path)
    principal = SitePrincipal('op', 'operator')
    first = asyncio.run(adapter.submit(principal, 'console-1', body, authorized=lambda:True))
    from fleet.server.task_store import IdempotencyConflict
    with pytest.raises(IdempotencyConflict):
        asyncio.run(adapter.submit(principal, 'console-1', body.model_copy(update={'x':9.}), authorized=lambda:True))
    from fleet.server.assistant.execution import AssistantExecution
    restarted = AssistantExecution(adapter.service, f.worker.execution, enabled=lambda:True)
    assert asyncio.run(restarted.submit(principal, 'console-1', body, authorized=lambda:True))['task']['task_id'] == first['task']['task_id']
    assert not f.writes


def test_execution_contract_rejects_tools_nonfinite_and_unbounded_coordinates():
    from core_common.protocol.assistant import AssistantNavigation
    from pydantic import ValidationError
    for value in [dict(robot_id='r1', x=float('nan'), y=0.), dict(robot_id='r1', x=100001., y=0.),
                  dict(robot_id='r1', x=0., y=0., tool='shell')]:
        with pytest.raises(ValidationError): AssistantNavigation(**value)


def test_authority_revoked_inside_task_transaction_rolls_back(tmp_path):
    f, adapter, body, _, _ = execution_fixture(tmp_path)
    decisions = iter([True, False])
    with pytest.raises(HTTPException):
        asyncio.run(adapter.submit(SitePrincipal('op', 'operator'), 'console-1', body,
                                   authorized=lambda:next(decisions)))
    assert not f.store.queued_task_ids() and not f.writes
