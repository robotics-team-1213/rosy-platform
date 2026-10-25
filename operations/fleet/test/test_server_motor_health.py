"""Read-only motor evidence keeps source age, including transport and Fleet cache time."""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import FakeClock, FakeRobot, fresh_reads
from fleet.server.app import create_app
from fleet.server.console_view import CapabilityDisplay
from test_server_gather_source import _console, _state_rows


def body(status='active'):
    return {'schema_version': 'rosy.motor-health.v1',
            'evidence': 'fresh' if status == 'active' else 'disconnected', 'status': status,
            'owner_id': 'omx_cell_01', 'session_id': '11111111-1111-4111-8111-111111111111',
            'sample_age_s': .25, 'stale_after_s': 2., 'support_reason': None,
            'stop_reasons': ['shoulder overload risk'] if status == 'fault' else [],
            'motors': [{'group': 'arm_a', 'joint': 'shoulder_lift', 'id': 12, 'sample_age_s': .25,
                        'command_raw': 700, 'present_raw': 725, 'error_deg': 2.2,
                        'pwm': -391, 'pwm_limit': 400, 'pwm_utilization': .9775,
                        'temperature_c': 43, 'temperature_limit_c': 72,
                        'voltage_v': 11.6, 'min_voltage_v': 6., 'max_voltage_v': 14.,
                        'warnings': ['high_pwm']}]}


def test_fleet_motor_evidence_is_separate_per_robot_and_does_not_hide_failures():
    clock = FakeClock()
    good, missing = FakeRobot('rosy_01'), FakeRobot('rosy_02')
    good.motor_health_value = body()
    missing.motor_health_error = httpx.ReadTimeout('old CORE')
    client = TestClient(create_app(_console(good, missing, clock=clock), console_token='viewer',
                                   start_task_dispatcher=False))
    rows = _state_rows(client)
    assert rows[0]['motor_health']['motors'][0]['id'] == 12
    assert rows[0]['motor_health']['sample_age_s'] == .25
    assert rows[0]['motor_health_age_s'] == 0.
    assert rows[1]['motor_health'] is None
    assert good.calls.count(('motor_health',)) == 1
    assert not any(call[0] in ('estop', 'navigation_goal', 'follow') for call in good.calls)


def test_fleet_keeps_last_fault_as_aged_evidence_on_transport_timeout():
    clock, robot = FakeClock(), FakeRobot('rosy_01')
    robot.motor_health_value = body('fault')
    client = TestClient(create_app(_console(robot, clock=clock), console_token='viewer',
                                   start_task_dispatcher=False))
    assert _state_rows(client)[0]['motor_health']['status'] == 'fault'
    robot.motor_health_error = httpx.ReadTimeout('link lost')
    clock.advance(3)
    client.app.state.fleet_gather.max_age_s = 0.
    row = _state_rows(client)[0]
    assert row['motor_health']['status'] == 'fault'
    assert row['motor_health_age_s'] == 3.
    assert row['motor_health']['sample_age_s'] == .25


def test_replacement_robot_or_invalid_motor_body_cannot_reuse_previous_evidence():
    clock, first = FakeClock(), FakeRobot('rosy_01')
    first.motor_health_value = body()
    console = _console(first, clock=clock)
    client = TestClient(create_app(console, console_token='viewer', start_task_dispatcher=False))
    assert _state_rows(client)[0]['motor_health'] is not None
    replacement = FakeRobot('rosy_01')
    replacement.motor_health_value = {'motors': [{'id': 12, 'temperature_c': float('nan')}]}
    from fleet.swarm.robots import RobotEndpoint
    console._replace_client(RobotEndpoint('rosy_01', 'http://127.0.0.1:9090', 't'), replacement)
    clock.advance(1)
    fresh_reads(client.app)
    row = _state_rows(client)[0]
    assert row['motor_health'] is None and row['motor_health_age_s'] is None


def test_motor_cache_age_includes_time_spent_waiting_for_the_read():
    async def exercise():
        clock = FakeClock()
        class Slow:
            async def motor_health(self):
                clock.advance(3)
                return body()
        display = CapabilityDisplay({'one': Slow()}, clock, read_method='motor_health',
                                    age_from_request=True)
        assert (await display.shown('one', wait_s=.5))['sample_age_s'] == .25
        assert display.age('one') == 3
        await display.aclose()
    asyncio.run(exercise())
