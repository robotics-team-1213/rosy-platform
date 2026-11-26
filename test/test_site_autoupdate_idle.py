"""Site auto-update and maintenance IDLE-only gates (D-441 / D-991)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from deploy.site import rosy_site_autoupdate as upd
from test_site_autoupdate import (  # noqa: F401 - host is a pytest fixture
    NEW, OLD, FakeHost, FakeHttp, _symlinks_supported, _tag, _updater, _world, host,
)


@pytest.mark.parametrize('endpoint,payload', [
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'state': {'mode': 'NAVIGATION'}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'state': {'mode': 'MANUAL'}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_42', 'state': {'mode': 'EMERGENCY', 'safety': {
        'estop': True, 'source': 'operator', 'releases_when_charged': False}}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_42', 'state': {'mode': 'EMERGENCY', 'safety': {
        'estop': True, 'source': 'battery_policy', 'releases_when_charged': True},
        'velocity': {'linear': 0.05, 'angular': 0.0}}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'state': {'mode': 'IDLE', 'navigation': 'NAVIGATING'}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'state': {'mode': 'IDLE', 'trip_lease': {'lease_id': 'L1'}}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'goal': {'target': 'bay_1'}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_45', 'goal': {'x': 0.45, 'y': 0.22}, 'state': {'mode': 'IDLE', 'navigation': 'IDLE'}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_45', 'goal': {'x': 0.45, 'y': 0.22}, 'state': {'mode': 'IDLE', 'navigation': 'CANCELED'}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_45', 'goal': {'x': 0.45, 'y': 0.22}, 'goal_in_flight': True, 'state': {'mode': 'IDLE', 'navigation': 'CANCELED'}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_45', 'goal': {'x': 0.45, 'y': 0.22, 'goal_lease': 'leased'}, 'goal_in_flight': False, 'state': {'mode': 'IDLE', 'navigation': 'CANCELED'}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_45', 'goal': {'x': 0.45, 'y': 0.22}, 'goal_in_flight': False, 'state': {'mode': 'IDLE', 'navigation': 'IDLE'}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_45', 'goal': {'x': 0.45, 'y': 0.22}, 'goal_in_flight': False, 'state': {'mode': 'NAVIGATION', 'navigation': 'CANCELED'}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'state': {'mode': 'IDLE', 'docking': {'state': 'DOCKING'}}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'state': {'mode': 'IDLE', 'docking': {'state': 'UNDOCKING'}}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'state': {'mode': 'IDLE', 'docking': {'state': 'UNKNOWN_NEW'}}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'state': {'mode': 'DOCKING', 'docking': {'state': 'DOCK_FAILED'}}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'state': {'line_follow': {'mode': 'CAMERA_LINE', 'state': 'TRACKING'}}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'state': {'velocity': {'linear': 0.05, 'angular': 0.0}}}]}),
    ('/api/fleet/state', {'robots': [{'robot_id': 'rosy_46', 'online': True, 'state': None}]}),
    ('/api/fleet/trips', {'open': [{'trip_id': 't1'}], 'running': [], 'trips': []}),
    ('/api/fleet/trips', {'open': [], 'running': {'trip_id': 't1'}, 'trips': []}),
    ('/api/fleet/trips', {'open': [], 'running': {}, 'trips': []}),
    ('/api/fleet/trips', {'open': [], 'trips': []}),
    ('/api/fleet/trips', {'open': [], 'running': 'bad', 'trips': []}),
    ('/api/fleet/dispatch-control', {'queued_tasks': 1, 'unresolved_actions': 0}),
    ('/api/fleet/dispatch-control', {'queued_tasks': 0, 'unresolved_actions': 1}),
    ('/api/fleet/formation', {'active': True, 'state': 'RUNNING'}),
    ('/api/fleet/state', 'malformed'),
    ('/api/fleet/trips', upd.Transient('fleet down')),
], ids=lambda v: str(v)[:36])
def test_site_autoupdate_defers_before_staging_when_busy_or_unreadable(host, capsys, endpoint, payload):
    rows, blobs = _world((NEW, '2026-10-04T02:00:00Z'))
    token = host.root / 'etc/rosy/site-secrets/site-update-viewer.token'
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text('viewer-secret', encoding='utf-8')
    http, fake = FakeHttp(rows, blobs), FakeHost(host.paths)
    base_functional = http.functional

    def functional(url, ca, tok):
        if url.endswith(endpoint):
            if isinstance(payload, Exception):
                raise payload
            return payload
        return base_functional(url, ca, tok)

    http.functional = functional
    assert _updater(host, http, fake).run() == upd.EXIT_OK
    assert fake.running == OLD
    assert not http.downloads
    assert not any(call[:2] == ['systemctl', 'restart'] for call in fake.calls)
    assert not any(call[:3] == ['docker', 'image', 'load'] for call in fake.calls)
    state = json.loads(host.paths.state.read_text(encoding='utf-8'))
    assert _tag(NEW) not in state['failed']
    assert state['last_run']['result'] == 'deferred-busy'
    assert 'deferred-busy' in capsys.readouterr().out


def test_site_autoupdate_defers_before_switch_if_work_begins_during_staging(host):
    rows, blobs = _world((NEW, '2026-10-04T02:00:00Z'))
    token = host.root / 'etc/rosy/site-secrets/site-update-viewer.token'
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text('viewer-secret', encoding='utf-8')
    http, fake = FakeHttp(rows, blobs), FakeHost(host.paths)
    base_functional = http.functional
    trips_calls = [0]

    def functional(url, ca, tok):
        if url.endswith('/api/fleet/trips'):
            trips_calls[0] += 1
            return {'open': [{'trip_id': 't-mid'}] if trips_calls[0] >= 2 else [], 'running': [], 'trips': []}
        return base_functional(url, ca, tok)

    http.functional = functional
    assert _updater(host, http, fake).run() == upd.EXIT_OK
    assert fake.running == OLD
    assert any(call[:3] == ['docker', 'image', 'load'] for call in fake.calls)
    assert not any(call[:2] == ['systemctl', 'restart'] for call in fake.calls)
    state = json.loads(host.paths.state.read_text(encoding='utf-8'))
    assert state['last_run']['result'] == 'deferred-busy' and _tag(NEW) not in state['failed']


def test_site_check_idle_cli_and_maintenance_units(host, monkeypatch, capsys):
    token = host.root / 'etc/rosy/site-secrets/site-update-viewer.token'
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text('viewer-secret', encoding='utf-8')
    cfg = {k: str(v) if isinstance(v, Path) else v for k, v in host.config.items()}
    monkeypatch.setattr(upd, 'Paths', lambda: host.paths)
    monkeypatch.setattr(upd, 'load_config', lambda _: cfg)
    http = FakeHttp([], {})
    monkeypatch.setattr(upd, 'Http', lambda: http)
    assert upd.main(['check-idle']) == upd.EXIT_OK
    assert json.loads(capsys.readouterr().out)['idle'] is True

    base_functional = http.functional
    http.functional = lambda u, c, t: ({'open': [], 'running': [], 'trips': []}
                                       if u.endswith('/api/fleet/trips') else base_functional(u, c, t))
    assert upd.main(['check-idle']) == upd.EXIT_OK
    assert json.loads(capsys.readouterr().out)['idle'] is True

    http.functional = lambda u, c, t: ({'open': [{'trip_id': 't1'}], 'running': [], 'trips': []}
                                       if u.endswith('/api/fleet/trips') else base_functional(u, c, t))
    assert upd.main(['check-idle']) == upd.EXIT_LOCKED
    assert json.loads(capsys.readouterr().out)['idle'] is False

    site_dir = Path(__file__).resolve().parents[1] / 'deploy/site'
    docker_unit = (site_dir / 'host-state/rosy-docker-upgrade.service').read_text(encoding='utf-8')
    assert 'ExecCondition=/usr/local/sbin/rosy-host-control nightly-gate' in docker_unit
    cell_unit = (site_dir.parent / 'cell_pc/host-state/rosy-nightly-reboot.service').read_text(encoding='utf-8')
    assert '/usr/local/sbin/rosy-host-control nightly-gate' in cell_unit
    helper_text = (site_dir / 'rosy-host-control').read_text(encoding='utf-8')
    assert helper_text.count('site_fleet_busy') >= 4


def test_site_autoupdate_fails_closed_when_viewer_token_is_symlink(host):
    if not _symlinks_supported():
        pytest.skip('needs symlinks')
    rows, blobs = _world((NEW, '2026-10-04T02:00:00Z'))
    token = host.root / 'etc/rosy/site-secrets/site-update-viewer.token'
    token.parent.mkdir(parents=True, exist_ok=True)
    secret_target = host.root / 'etc/rosy/site-secrets/real.token'
    secret_target.write_text('viewer-secret', encoding='utf-8')
    os.symlink(secret_target, token)
    http, fake = FakeHttp(rows, blobs), FakeHost(host.paths)
    assert _updater(host, http, fake).run() == upd.EXIT_OK
    assert fake.running == OLD and not http.downloads
    state = json.loads(host.paths.state.read_text(encoding='utf-8'))
    assert state['last_run']['result'] == 'deferred-busy'


@pytest.mark.parametrize('nav_state', ['ARRIVED', 'CANCELED', 'FAILED'])
def test_site_check_idle_allows_retained_terminal_goal_and_dock_failed(host, monkeypatch, capsys, nav_state):
    token = host.root / 'etc/rosy/site-secrets/site-update-viewer.token'
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text('viewer-secret', encoding='utf-8')
    cfg = {k: str(v) if isinstance(v, Path) else v for k, v in host.config.items()}
    monkeypatch.setattr(upd, 'Paths', lambda: host.paths)
    monkeypatch.setattr(upd, 'load_config', lambda _: cfg)
    http = FakeHttp([], {})
    base_functional = http.functional

    def functional(url, ca, tok):
        if url.endswith('/api/fleet/state'):
            return {'robots': [
                {
                    'robot_id': 'rosy_45',
                    'online': True,
                    'goal': {'x': 0.4501, 'y': 0.2205, 'yaw': 0.0117},
                    'goal_in_flight': False,
                    'state': {
                        'mode': 'IDLE',
                        'navigation': nav_state,
                        'docking': {'state': 'UNDOCKED'},
                        'velocity': {'linear': 0.0, 'angular': 0.0},
                    },
                },
                {   # parked by the battery policy until charged: not work an update would interrupt
                    'robot_id': 'rosy_42',
                    'online': True,
                    'goal': None,
                    'state': {
                        'mode': 'EMERGENCY',
                        'navigation': 'IDLE',
                        'safety': {'estop': True, 'source': 'battery_policy', 'releases_when_charged': True},
                        'velocity': {'linear': 0.0, 'angular': 0.0},
                    },
                },
                {
                    'robot_id': 'rosy_46',
                    'online': True,
                    'goal': None,
                    'state': {
                        'mode': 'IDLE',
                        'navigation': 'CANCELED',
                        'docking': {'state': 'DOCK_FAILED', 'error': 'obstacle ahead'},
                        'velocity': {'linear': 0.0, 'angular': 0.0},
                    },
                },
            ]}
        return base_functional(url, ca, tok)

    http.functional = functional
    monkeypatch.setattr(upd, 'Http', lambda: http)
    assert upd.main(['check-idle']) == upd.EXIT_OK
    assert json.loads(capsys.readouterr().out) == {'idle': True, 'reasons': []}
