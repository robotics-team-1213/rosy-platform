"""Only exact completed work retires Console projections before the next charge return."""
import copy
import importlib
import inspect

import pytest

from fakes import run
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint
from test_task_navigation_handover import fixture


def configured(tmp_path, change=None):
    service, task, client, value, sent = fixture(tmp_path)
    robot = task['robot_id']
    console = FleetConsole([RobotEndpoint(robot, 'http://core', 'robot-secret')], [client])
    console._goals[robot] = dict(x=1., y=0., yaw=0.)
    console._claims[robot] = [(0., 0.), (1., 0.)]
    console.trip_goal_sent_at = {robot: 99.}
    console.goal_leases[robot] = dict(state='leased', source='dispatch', task_id=task['task_id'],
        correlation_id=task['attempt_id'], ttl_s=1.)
    original = client.navigation_handover
    async def handover(**body):
        result = await original(**body)
        if change is not None:
            changed = change(console, robot)
            if inspect.isawaitable(changed):
                await changed
        return result
    client.navigation_handover = handover
    owner = importlib.import_module('fleet.server.charge_work_handover').CompletedWorkHandover(service, console)
    return owner, console, client, robot, task, sent


def test_exact_task_handover_retires_only_its_console_goal_and_route(tmp_path):
    owner, console, client, robot, task, sent = configured(tmp_path)
    console._seen[robot] = {'navigation': 'NAVIGATING'}
    assert run(owner.complete(robot, client=client, admission=lambda: None))
    assert sent and robot not in console._goals and robot not in console._claims
    assert robot not in console.goal_leases and robot not in console.trip_goal_sent_at
    assert console._seen[robot]['navigation'] == 'NAVIGATING', 'projection cleanup must not invent device state'
    assert owner.tasks.store.get_task(task['task_id'])['receipt']['safe_released'] is True


@pytest.mark.parametrize('fault', ['goal', 'goal_mutated', 'claim', 'claim_mutated', 'lease', 'lease_mutated',
    'stop', 'pending', 'busy', 'held', 'queued', 'yielding', 'formation', 'leader', 'client', 'manager', 'submission'])
def test_concurrent_owner_changes_preserve_every_projection(tmp_path, fault):
    def change(console, robot):
        if fault == 'goal': console._goals[robot] = dict(x=2., y=0., yaw=0.)
        elif fault == 'goal_mutated': console._goals[robot]['x'] = 2.
        elif fault == 'claim': console._claims[robot] = [(2., 0.)]
        elif fault == 'claim_mutated': console._claims[robot].append((2., 0.))
        elif fault == 'lease': console.goal_leases[robot] = dict(state='unbounded')
        elif fault == 'lease_mutated': console.goal_leases[robot]['task_id'] = 'new-task'
        elif fault == 'stop': console.goal_leases._stop_generation[robot] = 1
        elif fault == 'pending': console.goal_leases.pending[robot] = 1
        elif fault == 'busy': console._goal_busy.add(robot)
        elif fault == 'held': console._held[robot] = 'address_unverified'
        elif fault == 'queued': console._queued[robot] = {'x': 2.}
        elif fault == 'yielding': console._yielding[robot] = {'x': 2.}
        elif fault == 'formation': console._formation_members = lambda: [robot]
        elif fault == 'leader':
            console._formation_members = lambda: ['other-robot']
            console._formation_leader = robot
        elif fault == 'client': console._clients[robot] = object()
        elif fault == 'manager':
            from fleet.server.goal_lease import GoalLeases
            console.goal_leases = GoalLeases(0., console._clients)
        else:
            # A new submission can finish with unknown POST outcome and no remembered goal/lease.
            console.goal_leases._submission_generation[robot] = 1
    owner, console, client, robot, _, _ = configured(tmp_path, change)
    assert not run(owner.complete(robot, client=client, admission=lambda: None))
    assert robot in console._goals and robot in console._claims and robot in console.trip_goal_sent_at


@pytest.mark.parametrize('fault', ['held', 'formation', 'pending', 'lease_scope', 'dispatch_closed'])
def test_foreign_or_unreleased_work_cannot_reach_projection_cleanup(tmp_path, fault):
    owner, console, client, robot, task, sent = configured(tmp_path)
    if fault == 'held': console._held[robot] = 'address_unverified'
    elif fault == 'formation': console._formation_members = lambda: [robot]
    elif fault == 'pending': console.goal_leases.pending[robot] = 1
    elif fault == 'lease_scope': console.goal_leases[robot]['correlation_id'] = 'another-attempt'
    else:
        owner.tasks.store.close_dispatch_for_startup()
    old_goal, old_claim = copy.deepcopy(console._goals[robot]), copy.deepcopy(console._claims[robot])
    assert not run(owner.complete(robot, client=client, admission=lambda: None))
    assert console._goals[robot] == old_goal and console._claims[robot] == old_claim


def test_unknown_new_post_with_leases_disabled_still_fences_old_projection_cleanup(tmp_path):
    async def change(console, robot):
        from types import SimpleNamespace
        async def lost(*args, **kwargs):
            raise OSError('reply lost after possible send')
        with pytest.raises(OSError):
            await console.goal_leases.send(robot, SimpleNamespace(navigation_goal=lost), None,
                2., 0., 0., None, 'operator')
        assert robot not in console.goal_leases and robot not in console.goal_leases.pending
    owner, console, client, robot, _, _ = configured(tmp_path, change)
    console.goal_leases.pop(robot)
    assert not run(owner.complete(robot, client=client, admission=lambda: None))
    assert robot in console._goals and robot in console._claims
