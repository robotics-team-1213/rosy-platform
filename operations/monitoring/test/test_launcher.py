"""Run the installed independent service, including cross-process writer exclusion."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx

from browser_harness import free_port, safe_listener


READER = 'r' * 32


def configuration(collector, site, sources=(), sites=None):
    return {'collector_id': collector, 'site_id': site, 'sources': list(sources),
            'readers': [{'principal_id': 'operator', 'token_env': 'READ', 'sites': sites or [site]}]}


def eventually(check, *, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (httpx.HTTPError, KeyError, StopIteration):
            pass
        time.sleep(0.1)
    raise AssertionError('independent monitoring condition did not become true')


@contextmanager
def launch(tmp_path, config, *, state=None, extra_env=None):
    port = free_port()  # The public CLI accepts a port, not a pre-bound socket.
    path = tmp_path / (config['collector_id'] + '.yaml')
    path.write_text(json.dumps(config))
    state = state or tmp_path / (config['collector_id'] + '-state')
    environ = dict(os.environ, READ=READER)
    environ.update(extra_env or {})
    log = tmp_path / (config['collector_id'] + f'-{port}.log')
    with log.open('w+') as stream:
        process = subprocess.Popen([sys.executable, '-m', 'rosy.monitoring', '--config', str(path),
                                    '--state-dir', str(state), '--port', str(port)],
                                   env=environ, stdout=stream, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=2,
                              headers={'Authorization': f'Bearer {READER}'}, trust_env=False) as client:
                def ready():
                    if process.poll() is not None:
                        raise AssertionError('monitoring CLI exited before readiness')
                    return client.get('/health').status_code == 200
                eventually(ready)
                yield client, process, state, path
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def host_report(path, *, errors=()):
    # The owner writes capture time, not the collector's file-read time.
    body = {'time': int(time.time()), 'fixed': [], 'drift': [], 'awaiting_approval': [], 'errors': list(errors)}
    temporary = path.with_suffix('.next')
    temporary.write_text(json.dumps(body))
    temporary.replace(path)


def host(client):
    response = client.get('/api/monitoring/v1/snapshot')
    response.raise_for_status()
    return next(node for node in response.json()['nodes'] if node['kind'] == 'host')


def test_installed_launcher_runs_without_fleet_and_excludes_another_writer(tmp_path):
    report = tmp_path / 'host.json'
    host_report(report, errors=['private owner details'])
    with safe_listener() as refused:
        port = refused.getsockname()[1]  # Bound but not listening: deterministic connection refusal.
        config = configuration('collector-a', 'site-a', [
            {'id': 'host-a', 'site_id': 'site-a', 'kind': 'host_state', 'path': str(report)},
            {'id': 'p001', 'site_id': 'site-a', 'kind': 'core', 'url': f'http://127.0.0.1:{port}'},
        ])
        with launch(tmp_path, config) as (client, first, state, path):
            current = eventually(lambda: (node if (node := host(client))['reported_health'] == 'ERROR' else None))
            assert current['freshness'] == 'fresh'
            snapshot = client.get('/api/monitoring/v1/snapshot')
            assert 'private owner details' not in snapshot.text
            assert eventually(lambda: any(link['failure_stage'] == 'connect'
                              for link in client.get('/api/monitoring/v1/snapshot').json()['links']))
            other = subprocess.run([sys.executable, '-m', 'rosy.monitoring', '--config', str(path),
                                    '--state-dir', str(state), '--port', str(free_port())],
                                   env=dict(os.environ, READ=READER), capture_output=True, text=True, timeout=20)
            assert other.returncode == 1 and 'MONITORING_STARTUP_FAILED' in other.stderr
            assert first.poll() is None and host(client)['reported_health'] == 'ERROR'
        with launch(tmp_path, config, state=state) as (restarted, _, _, _):
            restored = eventually(lambda: host(restarted))
            assert restored['sampled_at'] == current['sampled_at']
            assert restored['age_s'] >= current['age_s']
            assert restored['remaining_s'] <= current['remaining_s']


def test_central_disconnect_does_not_stop_site_collection(tmp_path):
    report = tmp_path / 'host.json'
    host_report(report)
    site = configuration('collector-a', 'site-a', [
        {'id': 'host-a', 'site_id': 'site-a', 'kind': 'host_state', 'path': str(report)},
    ])
    with launch(tmp_path, site) as (local, _, _, _):
        eventually(lambda: host(local)['reported_health'] == 'OK')
        central = configuration('central', 'central-site', [
            {'id': 'collector-a', 'site_id': 'central-site', 'kind': 'peer',
             'url': str(local.base_url), 'token_env': 'PEER', 'peer_sites': ['site-a']},
        ], sites=['central-site', 'site-a'])
        with launch(tmp_path, central, extra_env={'READ': 'c' * 32, 'PEER': READER}) as (aggregate, _, _, _):
            aggregate.headers['Authorization'] = 'Bearer ' + 'c' * 32
            eventually(lambda: host(aggregate)['reported_health'] == 'OK')
        time.sleep(1.1)  # The owner's existing status format has whole-second capture times.
        host_report(report, errors=['not copied into monitoring'])
        updated = eventually(lambda: (node if (node := host(local))['reported_health'] == 'ERROR' else None))
        assert updated['freshness'] == 'fresh'


def test_central_can_collect_registered_site_directly_without_site_peer(tmp_path):
    report = tmp_path / 'host.json'
    host_report(report)
    config = configuration('central', 'central-site', [
        {'id': 'host-a', 'site_id': 'site-a', 'kind': 'host_state', 'path': str(report)},
    ], sites=['central-site', 'site-a'])
    with launch(tmp_path, config) as (client, _, _, _):
        assert eventually(lambda: host(client)['reported_health'] == 'OK')
        assert client.get('/api/monitoring/v1/snapshot').json()['scope_sites'] == ['central-site', 'site-a']


def test_bad_startup_never_echoes_config_or_creates_state(tmp_path):
    config = tmp_path / 'invalid.yaml'
    config.write_text('private-marker: do-not-echo\n')
    state = tmp_path / 'not-created'
    result = subprocess.run([sys.executable, '-m', 'rosy.monitoring', '--config', str(config),
                             '--state-dir', str(state)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 1 and 'MONITORING_STARTUP_FAILED' in result.stderr
    assert 'do-not-echo' not in result.stdout + result.stderr and not state.exists()


def test_platform_without_posix_permissions_is_rejected_before_creating_state(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from rosy.monitoring import __main__ as cli
    path = tmp_path / 'site.yaml'
    path.write_text(json.dumps(configuration('collector-a', 'site-a')))
    state = tmp_path / 'not-created'
    calls = []
    monkeypatch.setattr(cli, 'os', SimpleNamespace(name='nt', environ={'READ': READER}))
    monkeypatch.setattr(cli.uvicorn, 'run', lambda *args, **kwargs: calls.append(True))
    result = cli.main(['--config', str(path), '--state-dir', str(state)])
    assert result == 1 and 'MONITORING_STARTUP_FAILED' in capsys.readouterr().err
    assert not calls and not state.exists()


def test_existing_shared_state_directory_is_rejected(tmp_path, monkeypatch, capsys):
    from rosy.monitoring import __main__ as cli
    path = tmp_path / 'site.yaml'
    path.write_text(json.dumps(configuration('collector-a', 'site-a')))
    state = tmp_path / 'shared'
    state.mkdir()
    state.chmod(0o755)
    calls = []
    monkeypatch.setenv('READ', READER)
    monkeypatch.setattr(cli.uvicorn, 'run', lambda *args, **kwargs: calls.append(True))
    assert cli.main(['--config', str(path), '--state-dir', str(state)]) == 1
    assert 'MONITORING_STARTUP_FAILED' in capsys.readouterr().err
    assert not calls and not (state / 'monitoring.sqlite3').exists()


def test_listen_address_defaults_to_loopback_and_accepts_only_ip_literals(tmp_path, monkeypatch):
    from rosy.monitoring import __main__ as cli
    path = tmp_path / 'site.yaml'
    path.write_text(json.dumps(configuration('collector-a', 'site-a')))
    hosts = []
    monkeypatch.setenv('READ', READER)
    monkeypatch.setattr(cli.uvicorn, 'run', lambda *args, **kwargs: hosts.append(kwargs['host']))
    assert cli.main(['--config', str(path), '--state-dir', str(tmp_path / 'a')]) == 0
    assert cli.main(['--config', str(path), '--state-dir', str(tmp_path / 'b'), '--host', '0.0.0.0']) == 0
    assert hosts == ['127.0.0.1', '0.0.0.0']
    try:
        cli.main(['--config', str(path), '--state-dir', str(tmp_path / 'c'), '--host', 'fleet'])
    except SystemExit as exit:
        assert exit.code == 2
    else:
        raise AssertionError('a hostname listen address was accepted')
    assert not (tmp_path / 'c').exists()
