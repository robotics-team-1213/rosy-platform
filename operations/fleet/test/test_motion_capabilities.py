"""Fleet consumes live CORE capabilities before goal and formation dispatch."""
import asyncio

import httpx
import pytest

from fakes import FakeClock, FakeRobot, FakeRelay
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.session import FormationSession, FormationSpec, ArmingFailed
from fleet.formation.geometry import Formation
from fleet.swarm.transport import HttpRobotClient, RobotApiError


class CapRobot(FakeRobot):
    def __init__(self, robot_id):
        super().__init__(robot_id)
        self.caps = {'navigation': {'goal_navigation': True},
                     'swarm': {'lead': True, 'follow': True}}
        self.cap_reads = 0
        self.cap_error = None
        self.cap_gate = None

    async def capabilities(self):
        self.cap_reads += 1
        caps = self.caps
        if self.cap_gate is not None:
            await self.cap_gate.wait()
        if self.cap_error:
            raise self.cap_error
        return caps


def console(robot, clock=None):
    return FleetConsole([RobotEndpoint(robot.robot_id, 'http://robot', 'operator')],
                        [robot], clock=clock or FakeClock())


def test_capabilities_uses_authenticated_core_contract():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.headers['authorization']))
        return httpx.Response(200, json={'teleop': True})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='http://robot') as http:
            client = HttpRobotClient(RobotEndpoint('one', 'http://robot', 'operator'), http=http)
            assert await client.capabilities() == {'teleop': True}
    asyncio.run(exercise())
    assert seen == [('GET', '/api/v1/system/capabilities', 'Bearer operator')]


def test_snapshot_reports_capabilities_without_calling_motion():
    robot = CapRobot('one')
    robot.caps['navigation']['goal_navigation'] = False
    snapshot = asyncio.run(console(robot).snapshot())
    assert snapshot['robots'][0]['capabilities']['navigation']['goal_navigation'] is False
    assert not any(c[0] in ('navigation_goal', 'follow') for c in robot.calls)


def test_capability_failure_does_not_hide_online_telemetry():
    robot = CapRobot('one')
    robot.cap_error = ConnectionError('capability request failed')
    snapshot = asyncio.run(console(robot).snapshot())
    assert snapshot['robots'][0]['online'] is True
    assert snapshot['robots'][0]['capabilities'] is None


def test_slow_capability_read_does_not_delay_state_and_is_shared():
    async def exercise():
        robot = CapRobot('one')
        robot.cap_gate = asyncio.Event()
        fleet = console(robot)
        try:
            snapshots = await asyncio.wait_for(
                asyncio.gather(fleet.snapshot(), fleet.snapshot()), timeout=0.2)
            assert all(s['robots'][0]['online'] for s in snapshots)
            assert all(s['robots'][0]['capabilities'] is None for s in snapshots)
            assert robot.cap_reads == 1
            robot.cap_gate.set()
            await asyncio.sleep(0)
            assert (await fleet.snapshot())['robots'][0]['capabilities'] == robot.caps
        finally:
            await fleet.aclose()
    asyncio.run(exercise())


def test_expired_display_keeps_the_last_value_while_refreshing_and_close_cancels_it():
    # Field check 2026-10-10: an expired cache whose refresh missed the 0.05 s wait read as
    # unknown, so "수동 주행만 지원" and "주행 기능 확인 불가" swapped on every poll.
    async def exercise():
        robot, clock = CapRobot('one'), FakeClock()
        fleet = console(robot, clock)
        assert (await fleet.snapshot())['robots'][0]['capabilities'] == robot.caps
        clock.advance(6)
        robot.cap_gate = asyncio.Event()
        for _ in range(3):
            assert (await fleet.snapshot())['robots'][0]['capabilities'] == robot.caps
        assert fleet._capability_display.age('one') == 6.0
        pending = list(fleet._capability_display.pending.values())
        assert len(pending) == 1 and robot.cap_reads == 2
        await fleet.aclose()
        assert pending[0].cancelled()
        assert not fleet._capability_display.pending
    asyncio.run(exercise())


def test_a_timed_out_refresh_keeps_capabilities_and_a_robot_refusal_clears_them():
    async def exercise():
        robot, clock = CapRobot('one'), FakeClock()
        fleet = console(robot, clock)
        try:
            assert await fleet._shown_capabilities('one') == robot.caps
            clock.advance(6)
            robot.cap_error = httpx.ReadTimeout('slow robot')
            await fleet._shown_capabilities('one')
            await asyncio.sleep(0)
            assert await fleet._shown_capabilities('one') == robot.caps
            clock.advance(6)
            robot.cap_error = RobotApiError('one', 404, 'NOT_FOUND', 'older image')
            await fleet._shown_capabilities('one')
            await asyncio.sleep(0)
            assert await fleet._shown_capabilities('one') is None
        finally:
            await fleet.aclose()
    asyncio.run(exercise())


def test_cached_display_is_not_permission_to_dispatch_after_runtime_change():
    robot = CapRobot('one')
    fleet = console(robot)
    asyncio.run(fleet.snapshot())
    robot.caps = {'navigation': {'goal_navigation': False}}
    with pytest.raises(RobotApiError) as caught:
        asyncio.run(fleet.goal('one', 0.1, 0.0))
    assert caught.value.code == 'NOT_SUPPORTED'
    assert not any(c[0] == 'navigation_goal' for c in robot.calls)
    assert robot.cap_reads >= 2


def test_supported_goal_still_dispatches():
    robot = CapRobot('one')
    assert asyncio.run(console(robot).goal('one', 0.1, 0.0))['accepted'] is True
    assert any(c[0] == 'navigation_goal' for c in robot.calls)


def test_formation_membership_is_rechecked_after_capability_await():
    async def exercise():
        robot = CapRobot('one')
        robot.cap_gate = asyncio.Event()
        fleet = console(robot)
        task = asyncio.create_task(fleet.goal('one', 0.1, 0.0))
        await asyncio.sleep(0)
        fleet._formation_members = lambda: {'one'}
        robot.cap_gate.set()
        from fleet.hub.hub import HubError
        with pytest.raises(HubError) as caught:
            await task
        assert caught.value.code == 'FORMATION_ACTIVE'
        assert not any(c[0] == 'navigation_goal' for c in robot.calls)
    asyncio.run(exercise())


def test_replaced_client_cannot_repopulate_capability_cache():
    async def exercise():
        old, new = CapRobot('one'), CapRobot('one')
        old.cap_gate = asyncio.Event()
        fleet = console(old)
        task = asyncio.create_task(fleet._shown_capabilities('one'))
        await asyncio.sleep(0)
        fleet._replace_client(RobotEndpoint('one', 'http://replacement', 'operator'), new)
        old.cap_gate.set()
        assert await task is None
        assert 'one' not in fleet._capability_cache
    asyncio.run(exercise())


def test_pending_formation_follower_cannot_receive_an_individual_goal():
    from fleet.hub.hub import HubError
    from fleet.swarm.session import SessionState

    leader, follower = CapRobot('leader'), CapRobot('follower')
    fleet = console(follower)
    session = FormationSession(leader, [follower], FormationSpec(Formation.COLUMN), relay_factory=FakeRelay)
    session.state = SessionState.ARMING
    fleet._formation = session
    assert not session.assignment
    with pytest.raises(HubError) as caught:
        asyncio.run(fleet.goal('follower', 0.1, 0.0))
    assert caught.value.code == 'FORMATION_ACTIVE'
    assert not any(c[0] == 'navigation_goal' for c in follower.calls)


def test_bay_movement_refusal_keeps_existing_mission():
    robot = CapRobot('one')
    robot.caps['navigation']['goal_navigation'] = False
    fleet = console(robot)
    fleet._goals['one'] = {'x': 1.0, 'y': 0.0, 'yaw': 0.0}
    with pytest.raises(RobotApiError):
        asyncio.run(fleet._send_to_bay('one', (0.0, 0.1), 'other'))
    assert fleet._goals['one']['x'] == 1.0
    assert not fleet._yielding
    assert not any(c[0] == 'navigation_goal' for c in robot.calls)


@pytest.mark.parametrize('member,flag', [('leader', 'lead'), ('follower', 'follow')])
def test_formation_refuses_unsupported_member_before_any_stream_opens(member, flag):
    leader, follower = CapRobot('leader'), CapRobot('follower')
    {'leader': leader, 'follower': follower}[member].caps['swarm'][flag] = False
    session = FormationSession(leader, [follower], FormationSpec(Formation.COLUMN), relay_factory=FakeRelay)
    with pytest.raises(ArmingFailed) as caught:
        asyncio.run(session.start())
    assert caught.value.code == 'NOT_SUPPORTED'
    assert not leader.pose_opens and not follower.sinks
    assert not any(c[0] == 'follow' for c in follower.calls)
