"""Station activation is explicit and uses CORE's existing final publisher and parking owner."""
from types import SimpleNamespace

import pytest

from core.bridge import docking_mode
from core_api_web.api.deps import Mode
from test_docking_parking_wiring import OPERATOR, sim_overrides
from test_cmd_vel_cycle import run


def station_config():
    config = sim_overrides()
    config['docking']['seed'] = dict(
        dock_types=[dict(name='station', detector='station_observation', staging=False,
                        approach='pose', settle='pose', tag_offset_m=0.15, pose_tolerance_rad=0.05)],
        docks=[dict(id='charger-1', type='station', map_id='floor')])
    return config


def test_station_type_without_profile_cannot_start_through_legacy_api(core_client):
    client, services = core_client(config_overrides=station_config())
    response = client.post('/api/v1/docking/dock', json={'dock': 'charger-1'}, headers=OPERATOR)
    assert response.status_code == 409
    assert services.docking.native.current is None
    assert services.modes.mode is Mode.IDLE


def test_station_hardware_activation_has_no_implicit_acceptance(core_client):
    config = station_config()
    config['runtime']['mode'] = 'hardware'
    config['docking']['station'] = {'enabled': True}
    with pytest.raises(ValueError, match='DEVICE_ACCEPTANCE'):
        core_client(config_overrides=config)


def test_missing_profile_refuses_explicit_sim_activation(core_client):
    config = station_config()
    config['docking']['station'] = {'enabled': True}
    with pytest.raises(ValueError, match='PROFILE'):
        core_client(config_overrides=config)


def test_final_gate_preserves_power_and_manual_takeover_and_holds_other_motion():
    power = SimpleNamespace(motion_ready=lambda: True)
    owner = SimpleNamespace(session=object(), motion_ready=lambda mode: False)
    svc = SimpleNamespace(power=power, station_docking=owner, modes=SimpleNamespace(mode=Mode.NAVIGATION))
    assert hasattr(docking_mode, 'motion_ready'), 'final station output guard is not wired'
    assert run(motion_ready=lambda: docking_mode.motion_ready(svc)).sent == [(0., 0.)]
    svc.modes.mode = Mode.MANUAL
    assert run(motion_ready=lambda: docking_mode.motion_ready(svc)).sent == [(0.2, 0.)]
    power.motion_ready = lambda: False
    assert run(motion_ready=lambda: docking_mode.motion_ready(svc)).sent == [(0., 0.)]


def test_bridge_ticks_station_owner_instead_of_legacy_post_dock_heuristics():
    calls = []
    docking = SimpleNamespace(on_navigation_state=lambda value: None, set_manual_active=lambda value: None,
                              tick=lambda: calls.append('legacy'), status=lambda: 'status')
    svc = SimpleNamespace(docking=docking, nav=SimpleNamespace(nav_state='IDLE'),
                          command=SimpleNamespace(manual_active=False),
                          state=SimpleNamespace(set_docking=lambda value: calls.append(value)))
    owner = SimpleNamespace(session=object(), tick=lambda: calls.append('station'))
    docking_mode.tick(svc, lambda message: pytest.fail(message), station=owner)
    assert calls == ['station', 'status']


def configured_station(core_client, **station_options):
    config = station_config()
    config['docking']['station'] = dict(enabled=True, map_revision='map-1', profile=dict(
        battery_id='pack-1', station_id='charger-1', source_id='station-camera',
        source_epoch='camera-boot', calibration_revision='mount-1', marker_offset_m=0.15,
        max_age_s=0.25, max_uncertainty_m=0.01, max_uncertainty_rad=0.02,
        position_tolerance_m=0.012, heading_tolerance_rad=0.05,
        linear_limit_m_s=0.003, angular_limit_rad_s=0.01, still_s=0.4, debounce_s=0.3,
        sample_max_age_s=0.25, min_full_voltage_v=8.1, max_voltage_v=8.5,
        pack_max_age_s=0.25, charge_confirm_s=0.3))
    config['docking']['station'].update(station_options)
    _, svc = core_client(config_overrides=config)
    assert hasattr(svc, 'station_docking') and svc.station_docking is not None
    return svc


def test_explicit_sim_profile_builds_owner_and_state_capture_never_waits(core_client):
    svc = configured_station(core_client)
    assert svc.station_docking.state == 'UNBOUND'
    svc.state.set_map_id('floor')
    svc.state.set_odom_pose(0., 0., 0.)
    scope = svc.station_docking.local_scope_nowait()
    assert scope['map_id'] == 'floor' and scope['odom_fresh'] is False
    assert hasattr(svc.station_docking, 'sensors') and svc.station_docking.sensors is not None
    assert svc.station_docking.sensors.motion_sample() is None
    svc.state.set_velocity(0.03, 0.01)
    assert svc.station_docking.sensors.motion_sample() is None
    from core.bridge.odometry import receive_odom
    bridge = SimpleNamespace(_svc=svc, _frame_prefix='', _bounded_trial_guard=None,
        _line_clock=svc.docking.now, _node=SimpleNamespace(
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=100_100_000_000))))
    message = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=100, nanosec=0), frame_id='odom'),
        child_frame_id='base_link', pose=SimpleNamespace(pose=SimpleNamespace(
            position=SimpleNamespace(x=0., y=0., z=0.),
            orientation=SimpleNamespace(x=0., y=0., z=0., w=1.))),
        twist=SimpleNamespace(twist=SimpleNamespace(linear=SimpleNamespace(x=.03, y=0., z=0.),
            angular=SimpleNamespace(x=0., y=0., z=.01))))
    receive_odom(bridge, message, station=svc.station_docking)
    assert svc.station_docking.local_scope_nowait()['odom_fresh'] is True
    measured = svc.station_docking.sensors.motion_sample()
    assert measured['measured_linear_m_s'] == 0.03
    assert measured['measured_angular_rad_s'] == 0.01
    assert measured['odom_epoch'] == scope['odom_epoch']
    svc.state._lock.acquire()
    try:
        assert svc.station_docking.local_scope_nowait() is None
    finally:
        svc.state._lock.release()


def test_station_cleanup_failure_does_not_skip_legacy_mode_exit_cleanup(core_client):
    from core_features.docking.database import DockInstance, DockType
    svc = configured_station(core_client)
    svc.docking.database.add_type(DockType(name='legacy', detector='observation'))
    svc.docking.database.add(DockInstance(id='legacy', type='legacy'))
    svc.docking.dock('legacy', correlation_id='legacy-run')
    assert svc.docking.active
    svc.station_docking.session = object()

    def broken_invalidate(reason):
        raise RuntimeError('station cleanup failed')

    svc.station_docking.invalidate = broken_invalidate
    clears = []
    clear = svc.command.clear_docking

    def clear_docking():
        clears.append(True)
        clear()

    svc.command.clear_docking = clear_docking
    assert svc.modes.transition(Mode.MANUAL)[0]
    assert not svc.docking.active
    assert clears
