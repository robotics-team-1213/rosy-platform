"""Opt-in isolated native proxy acceptance; never install a service or trust anchor."""

from hashlib import sha256
from io import BytesIO
import os
import platform
import shutil
import ssl
import subprocess
import tarfile
import time
from urllib.request import urlopen

import httpx
import pytest

from browser_harness import free_port
from test_monitoring_browser import KEY_A, ROOT, monitoring_backend  # noqa: F401


pytestmark = pytest.mark.skipif(os.environ.get('ROSY_MONITORING_TLS_TEST') != '1',
                                reason='opt-in native proxy acceptance downloads a pinned test tool')


def caddy_binary(directory):
    # Official v2.10.2 release asset digest; this pins the test tool, not production deployment.
    url = 'https://github.com/caddyserver/caddy/releases/download/v2.10.2/caddy_2.10.2_linux_amd64.tar.gz'
    expected = '5c218bc34c9197369263da7e9317a83acdbd80ef45d94dca5eff76e727c67cdd'
    with urlopen(url, timeout=60) as response:
        data = response.read(20 * 1024 * 1024 + 1)
    assert len(data) == 15875694 and sha256(data).hexdigest() == expected
    with tarfile.open(fileobj=BytesIO(data), mode='r:gz') as archive:
        member = archive.getmember('caddy')
        assert member.isfile() and member.size <= 64 * 1024 * 1024
        executable = directory / 'caddy'
        executable.write_bytes(archive.extractfile(member).read())
    executable.chmod(0o700)
    return executable


@pytest.mark.parametrize('monitoring_backend', ['web'], indirect=True)
def test_native_caddy_tls_routes_auth_scopes_and_backend_outage(tmp_path, monitoring_backend):
    assert platform.system() == 'Linux' and platform.machine() in {'x86_64', 'AMD64'}
    assert shutil.which('openssl'), 'native certificate tool required'
    binary = caddy_binary(tmp_path)
    cert, key = tmp_path / 'test.crt', tmp_path / 'test.key'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                    '-keyout', str(key), '-out', str(cert), '-days', '1', '-subj', '/CN=localhost',
                    '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'],
                   check=True, capture_output=True, timeout=30)
    port = free_port()
    source = (ROOT / 'operations/monitoring/deploy/Caddyfile.example').read_text(encoding='utf-8')
    backend = monitoring_backend.origin.removeprefix('http://')
    text = source.replace('monitoring.example.invalid {',
                          f'localhost:{port} {{\n    bind 127.0.0.1\n    tls {cert} {key}')
    text = text.replace('127.0.0.1:8786', backend)
    config = tmp_path / 'Caddyfile'
    config.write_text('{\n    admin off\n    auto_https disable_redirects\n}\n' + text, encoding='utf-8')
    environ = {**os.environ, 'HOME': str(tmp_path), 'XDG_DATA_HOME': str(tmp_path / 'data'),
               'XDG_CONFIG_HOME': str(tmp_path / 'config')}
    subprocess.run([str(binary), 'validate', '--adapter', 'caddyfile', '--config', str(config)],
                   env=environ, check=True, capture_output=True, text=True, timeout=30)
    log = tmp_path / 'proxy.log'
    with log.open('w+') as stream:
        process = subprocess.Popen([str(binary), 'run', '--adapter', 'caddyfile', '--config', str(config)],
                                   env=environ, stdout=stream, stderr=subprocess.STDOUT)
        try:
            context = ssl.create_default_context(cafile=str(cert))
            with httpx.Client(base_url=f'https://localhost:{port}', verify=context,
                              timeout=2, trust_env=False) as client:
                until = time.monotonic() + 20
                while True:
                    assert process.poll() is None, log.read_text()
                    try:
                        if client.get('/monitoring-health').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    assert time.monotonic() < until, log.read_text()
                    time.sleep(0.1)
                assert client.get('/monitoring').status_code == 308
                assert 'ROSY Monitoring' in client.get('/monitoring/').text
                assert client.get('/monitoring/common/ui.js').content == (ROOT / 'shared/web/ui.js').read_bytes()
                path = '/api/monitoring/v1/snapshot'
                assert client.get(path).status_code == 401
                headers = {'Authorization': f'Bearer {KEY_A}'}
                snapshot = client.get(path, headers=headers)
                assert snapshot.status_code == 200 and snapshot.json()['scope_sites'] == ['site-a']
                assert snapshot.headers['cache-control'] == 'no-store'
                assert client.get(path + '?site_id=site-b', headers=headers).status_code == 403
                with httpx.Client(trust_env=False, timeout=2) as untrusted:
                    with pytest.raises(httpx.ConnectError, match='CERTIFICATE_VERIFY_FAILED'):
                        untrusted.get(f'https://localhost:{port}/monitoring-health')
                monitoring_backend.server.should_exit = True
                monitoring_backend.worker.join(timeout=10)
                assert not monitoring_backend.worker.is_alive()
                assert client.get('/monitoring-health').status_code == 502
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
