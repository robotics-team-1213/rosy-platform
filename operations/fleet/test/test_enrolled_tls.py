"""Existing encrypted enrollment must select authenticated transport, not another roster."""
import asyncio

import httpx
import pytest
import json
import hashlib
import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from enrollment_fakes import CODE, NAME, PINNED, FakeCore, build, scan_row
from fleet.server.enrollment import EnrollmentService
from fleet.swarm.robots import RobotEndpoint
from fleet.server.enrollment_tls import EnrolledTlsBindings, EnrollmentTlsError
from fleet.server.enrollment import EnrolledRobotClient, RobotGate, EnrollmentError
from core_common.discover import DiscoveredDevice
from fleet.server.console import FleetConsole
from fleet.server.roster import SiteRoster


def approved(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Fixture CA')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1))
            .not_valid_after(now+timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), True)
            .sign(key, hashes.SHA256()))
    ca = tmp_path/'ca.pem'
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    digest = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    row = dict(robot_id='rosy_09', hostname=NAME+'.local', port=8080,
               tls_ca_file=str(ca.resolve()), tls_ca_sha256=digest)
    file = tmp_path/'bindings.json'
    file.write_text(json.dumps(dict(version='rosy.enrolled-tls/1', robots=[row])))
    spki = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    identity = dict(receiver_id='rosy_09', receiver_public_key=base64.b64encode(spki).decode(),
                    receiver_key_sha256=hashlib.sha256(spki).hexdigest(), tls_hostname=NAME+'.local',
                    tls_ca_pem=ca.read_text(), tls_ca_sha256=digest)
    return EnrolledTlsBindings(file), row, identity, file


def discovered(monkeypatch, rows):
    record = DiscoveredDevice(NAME, '_rosy._tcp', NAME+'.local', 8080, addresses=('192.168.1.203',),
                              txt=(('product', 'rosy'), ('role', 'robot'), ('proto', 'core-v1'), ('tls', 'required')))
    rows.append(record)
    monkeypatch.setattr('fleet.swarm.discovery_transport.get_shared_cache',
                        lambda: SimpleNamespace(wait=lambda *a, **kw: list(rows)))


@pytest.mark.parametrize('manual', [False, True])
def test_secure_manual_and_list_code_never_downgrade(tmp_path, manual):
    service, network, _, discovery, _, _ = build(tmp_path, {PINNED: FakeCore()})
    discovery.replace_scan([{**scan_row(), 'transport': 'https'}])
    with pytest.raises(EnrollmentError, match='HTTPS'):
        asyncio.run(service.enroll(code=CODE, principal_id='alice',
                                   **({'address': PINNED} if manual else {'discovery_name': NAME})))
    assert network.requests == []


def test_ca_digest_is_der_and_config_cannot_register_or_change_identity(tmp_path):
    bindings, row, _, file = approved(tmp_path)
    assert bindings.binding('rosy_09').context().check_hostname
    with pytest.raises(EnrollmentTlsError, match='already enrolled'):
        bindings.validate([])
    with pytest.raises(EnrollmentTlsError, match='hostname'):
        bindings.validate([dict(robot_id='rosy_09', hostname='other')])
    file.write_text(json.dumps(dict(version='rosy.enrolled-tls/1', robots=[])))
    with pytest.raises(EnrollmentTlsError, match='changed'):
        bindings.binding('rosy_09')


@pytest.mark.parametrize('fault', ['missing', 'hash', 'pem', 'duplicate', 'extra', 'hostname'])
def test_bad_public_binding_fails_closed(tmp_path, fault):
    bindings, row, _, file = approved(tmp_path)
    if fault == 'missing':
        (tmp_path/'ca.pem').unlink()
    elif fault == 'hash':
        row['tls_ca_sha256'] = '0'*64
    elif fault == 'pem':
        (tmp_path/'ca.pem').write_text('not a certificate')
    elif fault == 'extra':
        row['credential'] = 'not-allowed'
    elif fault == 'hostname':
        row['hostname'] = '192.168.1.203'
    if fault == 'duplicate':
        file.write_text('{"version":"rosy.enrolled-tls/1","version":"other","robots":[]}')
    else:
        file.write_text(json.dumps(dict(version='rosy.enrolled-tls/1', robots=[row])))
    with pytest.raises(EnrollmentTlsError):
        EnrolledTlsBindings(file)


def test_dhcp_rest_bearer_follows_only_verified_receiver(tmp_path, monkeypatch):
    bindings, _, identity, _ = approved(tmp_path)
    rows = []
    discovered(monkeypatch, rows)
    endpoint = bindings.endpoint(dict(robot_id='rosy_09', address=PINNED), 'runtime-fixture')
    calls = []

    def receive(request):
        calls.append(request)
        if request.url.path.endswith('/identity'):
            assert 'Authorization' not in request.headers
            return httpx.Response(200, json=identity)
        assert request.extensions['sni_hostname'] == NAME+'.local'
        assert request.url.host == '192.168.1.203'
        return httpx.Response(200, json={'robot_id': 'rosy_09'})
    client = EnrolledRobotClient(endpoint, RobotGate(), tls_bindings=bindings,
                                 transport=httpx.MockTransport(receive))

    async def scenario():
        assert (await client.state())['robot_id'] == 'rosy_09'
        calls.clear()
        identity['receiver_id'] = 'rosy_other'
        with pytest.raises(EnrollmentTlsError):
            await client.state()
        assert len(calls) == 1 and 'Authorization' not in calls[0].headers
        calls.clear()
        rows.clear()
        with pytest.raises(ValueError, match='not_discovered'):
            await client.state()
        assert not calls
        await client.aclose()
    asyncio.run(scenario())


def test_wss_identity_admission_precedes_actual_auth_frame(tmp_path, monkeypatch):
    bindings, binding, identity, _ = approved(tmp_path)
    rows = []
    discovered(monkeypatch, rows)
    endpoint = bindings.endpoint(dict(robot_id='rosy_09', address=PINNED), 'runtime-fixture')
    order = []

    def receive(request):
        order.append('identity')
        assert 'Authorization' not in request.headers
        return httpx.Response(200, json=identity)

    class Socket:
        async def send(self, data): order.append(json.loads(data)['type'])
        async def close(self): pass

    async def connect(url, **options):
        order.append('connect')
        assert url.startswith('wss://'+NAME+'.local')
        assert options['host'] == '192.168.1.203' and options['server_hostname'] == NAME+'.local'
        assert options['ssl'].check_hostname and options['proxy'] is None
        assert [hashlib.sha256(ca).hexdigest() for ca in options['ssl'].get_ca_certs(binary_form=True)] == [
            binding['tls_ca_sha256']]
        return Socket()
    monkeypatch.setattr('websockets.connect', connect)
    client = EnrolledRobotClient(endpoint, RobotGate(), tls_bindings=bindings, transport=httpx.MockTransport(receive))

    async def scenario():
        await client._open_socket(client.events_url(['mode.changed']))
        assert order == ['identity', 'connect', 'auth']
        order.clear()
        identity['receiver_id'] = 'rosy_other'
        with pytest.raises(EnrollmentTlsError):
            await client._open_socket(client.events_url([]))
        assert order == ['identity']
        await client.aclose()
    asyncio.run(scenario())


def test_load_probe_logout_and_dhcp_leave_sealed_record_untouched(tmp_path, monkeypatch):
    old, _, _, discovery, store, _ = build(tmp_path, {PINNED: FakeCore()})
    discovery.replace_scan([scan_row()])
    asyncio.run(old.enroll(code=CODE, principal_id='alice', discovery_name=NAME))
    original = store.get('rosy_09')
    ciphertext = store.ciphertext('rosy_09')
    bindings, _, identity, _ = approved(tmp_path)
    rows = []
    discovered(monkeypatch, rows)
    core = FakeCore()
    calls = []

    def receive(request):
        calls.append(request)
        if request.url.path.endswith('/identity'):
            assert 'Authorization' not in request.headers
            return httpx.Response(200, json=identity)
        return core.handle(request)
    roster = SiteRoster(FleetConsole([], []))
    service = EnrollmentService(store, roster, key=old._key, clock=old._clock, tls_bindings=bindings,
                                transport=httpx.MockTransport(receive), discovery=discovery)
    service.load()
    assert roster.robot_ids == ['rosy_09'] and store.ciphertext('rosy_09') == ciphertext

    async def scenario():
        await service.on_discovery([scan_row('192.168.1.203:8080')])
        assert store.get('rosy_09') == original and service._gates['rosy_09'].held is None
        assert await service._still_at_pinned(original)
        assert calls[-1].url.scheme == 'https' and calls[-1].url.host == '192.168.1.203'
        with pytest.raises(EnrollmentError, match='reconnects'):
            await service.move_address('rosy_09', code=CODE, principal_id='alice')
        assert store.ciphertext('rosy_09') == ciphertext
        assert (await service.unenroll('rosy_09', principal_id='alice'))['state'] == 'removed'
        assert store.get('rosy_09') is None and roster.robot_ids == []
        assert calls[-1].url.path == '/api/v1/auth/logout' and calls[-1].url.scheme == 'https'
        assert all(r.url.scheme == 'https' for r in calls)
    asyncio.run(scenario())


def test_pending_logout_uses_same_tls_admission_and_expiry_closes_sockets(tmp_path, monkeypatch):
    old, _, _, discovery, store, _ = build(tmp_path, {PINNED: FakeCore()})
    discovery.replace_scan([scan_row()])
    asyncio.run(old.enroll(code=CODE, principal_id='alice', discovery_name=NAME))
    bindings, _, identity, _ = approved(tmp_path)
    rows = []
    discovered(monkeypatch, rows)
    calls = []

    def receive(request):
        calls.append(request)
        return httpx.Response(200, json=identity) if request.url.path.endswith('/identity') else httpx.Response(204)
    service = EnrollmentService(store, SiteRoster(FleetConsole([], [])), key=old._key, tls_bindings=bindings,
                                transport=httpx.MockTransport(receive), clock=old._clock)
    store.update('rosy_09', state='pending_logout')
    asyncio.run(service.on_discovery([scan_row('192.168.1.203:8080')]))
    assert [r.url.path for r in calls] == ['/api/v1/auth/peer-pairing/identity', '/api/v1/auth/logout']
    assert 'Authorization' not in calls[0].headers and calls[1].url.scheme == 'https'
    client = EnrolledRobotClient(RobotEndpoint('rosy_09', 'http://192.168.1.202:8080', 'fixture'),
                                 RobotGate(expires_at=1), clock=lambda: 2)
    with pytest.raises(Exception, match='sockets stay closed'):
        client._refuse_socket()
    asyncio.run(client.aclose())


def test_cli_dedicated_environment_and_both_compose_profiles(monkeypatch):
    from pathlib import Path
    import yaml
    from fleet.cli import parse_args
    monkeypatch.setenv('ROSY_ENROLLED_TLS_BINDINGS_FILE', '/run/rosy-config/enrolled-tls-bindings.json')
    assert parse_args(['console']).enrolled_tls_bindings_file.as_posix(
    ) == '/run/rosy-config/enrolled-tls-bindings.json'
    assert parse_args(['console', '--enrolled-tls-bindings-file', '/explicit.json']
                      ).enrolled_tls_bindings_file.as_posix() == '/explicit.json'
    root = Path(__file__).resolve().parents[3]
    for name in ['compose.yaml', 'compose.pairing.yaml']:
        env = yaml.safe_load((root/'deploy/site'/name).read_text())['services']['fleet']['environment']
        assert env['ROSY_ENROLLED_TLS_BINDINGS_FILE'] == '${ROSY_SITE_ENROLLED_TLS_BINDINGS_FILE:-}'


def test_symlink_binding_and_ca_do_not_open(tmp_path):
    bindings, _, _, file = approved(tmp_path)
    link = tmp_path/'link.json'
    try:
        link.symlink_to(file)
    except OSError:
        # Windows accounts may lack symlink creation privilege; production Linux has its own run.
        pytest.skip('Windows account cannot create symlink; Linux deployment guard remains required')
    with pytest.raises(EnrollmentTlsError):
        EnrolledTlsBindings(link)


def test_restart_without_config_never_returns_to_http(tmp_path):
    original, network, _, discovery, store, _ = build(tmp_path, {PINNED: FakeCore()})
    discovery.replace_scan([scan_row()])
    asyncio.run(original.enroll(code=CODE, principal_id='alice', discovery_name=NAME))
    record = store.get('rosy_09')
    cipher = store.ciphertext('rosy_09')
    bindings, _, _, _ = approved(tmp_path)
    first = EnrollmentService(store, SiteRoster(FleetConsole([], [])), key=original._key, tls_bindings=bindings,
                              transport=httpx.MockTransport(network), clock=original._clock)
    first.load()
    network.clear()
    # A restarted service with empty environment still knows this credential was TLS-bound.
    second = EnrollmentService(store, SiteRoster(FleetConsole([], [])), key=original._key,
                               transport=httpx.MockTransport(network), clock=original._clock)
    with pytest.raises(EnrollmentTlsError, match='HTTP refused'):
        second.load()
    with pytest.raises(EnrollmentTlsError, match='HTTP refused'):
        second._http(PINNED)
    assert not network.requests and store.get('rosy_09') == record and store.ciphertext('rosy_09') == cipher
    assert store.tls_markers()['rosy_09']['origin'] == 'https://'+NAME+'.local:8080'


def test_changed_ca_and_hold_do_not_replace_transport_marker(tmp_path):
    original, _, _, discovery, store, _ = build(tmp_path, {PINNED: FakeCore()})
    discovery.replace_scan([scan_row()])
    asyncio.run(original.enroll(code=CODE, principal_id='alice', discovery_name=NAME))
    bindings, _, _, _ = approved(tmp_path)
    first = EnrollmentService(store, SiteRoster(FleetConsole([], [])), key=original._key, tls_bindings=bindings,
                              clock=original._clock)
    first.load()
    saved = store.tls_markers()
    cipher = store.ciphertext('rosy_09')
    different, _, _, _ = approved(tmp_path)  # new real CA, valid new public hash, same hostname
    second = EnrollmentService(store, SiteRoster(FleetConsole([], [])), key=original._key, tls_bindings=different)
    with pytest.raises(EnrollmentTlsError, match='changed'):
        second.load()
    assert store.tls_markers() == saved and store.ciphertext('rosy_09') == cipher
    store.update('rosy_09', state='needs_new_code')
    assert store.tls_markers() == saved
    store.update('rosy_09', state='pending_logout')
    assert store.tls_markers() == saved
    store.delete('rosy_09')
    assert store.tls_markers() == {} and store.get('rosy_09') is None


def test_public_marker_transaction_is_all_or_nothing(tmp_path):
    old, _, _, discovery, store, _ = build(tmp_path, {PINNED: FakeCore()})
    discovery.replace_scan([scan_row()])
    asyncio.run(old.enroll(code=CODE, principal_id='alice', discovery_name=NAME))
    before = store.get('rosy_09')
    cipher = store.ciphertext('rosy_09')
    first = dict(robot_id='rosy_09', origin='https://'+NAME+'.local:8080', ca_sha256='0'*64)
    with pytest.raises(ValueError, match='conflicts'):
        store.remember_tls([first, {**first, 'robot_id': 'unknown'}])
    assert store.tls_markers() == {} and store.get('rosy_09') == before and store.ciphertext('rosy_09') == cipher


def test_bound_reload_preserves_ciphertext_and_uses_tls_transport(tmp_path):
    service, _, console, discovery, store, _ = build(tmp_path, {PINNED: FakeCore()})
    discovery.replace_scan([scan_row()])
    asyncio.run(service.enroll(code=CODE, principal_id='alice', discovery_name=NAME))
    ciphertext = store.ciphertext('rosy_09')
    row = store.get('rosy_09')

    class ApprovedBinding:
        def endpoint(self, row, access_token):
            return RobotEndpoint(row['robot_id'], 'https://'+NAME+'.local:8080', access_token,
                                 tls_ca_file='configured-ca.pem', discovery=True)

        def validate(self, rows):
            assert [r['robot_id'] for r in rows] == ['rosy_09']

    bound = EnrollmentService(store, service._roster, key=service._key, tls_bindings=ApprovedBinding())
    endpoint = bound._endpoint(row, service._tokens['rosy_09'])
    assert endpoint.base_url.startswith('https://') and endpoint.discovery
    assert store.ciphertext('rosy_09') == ciphertext and store.get('rosy_09') == row


def test_secure_scan_never_posts_screen_code_over_http(tmp_path):
    service, network, _, discovery, _, _ = build(tmp_path, {PINNED: FakeCore()})
    discovery.replace_scan([{**scan_row(), 'transport': 'https'}])
    with pytest.raises(Exception):
        asyncio.run(service.enroll(code=CODE, principal_id='alice', discovery_name=NAME))
    assert network.requests == []


def test_gate_held_during_identity_cannot_send_bearer(tmp_path, monkeypatch):
    bindings, _, identity, _ = approved(tmp_path)
    rows = []
    discovered(monkeypatch, rows)
    gate = RobotGate()
    calls = []

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def receive(request):
            calls.append(request)
            if request.url.path.endswith('/identity'):
                entered.set()
                await release.wait()
                return httpx.Response(200, json=identity)
            return httpx.Response(200, json={})

        endpoint = bindings.endpoint(dict(robot_id='rosy_09', address=PINNED), 'runtime-fixture')
        client = EnrolledRobotClient(endpoint, gate, tls_bindings=bindings,
                                     transport=httpx.MockTransport(receive))
        pending = asyncio.create_task(client.state())
        await entered.wait()
        gate.held = 'needs_new_code'
        release.set()
        with pytest.raises(Exception, match='only stop requests'):
            await pending
        assert len(calls) == 1 and 'Authorization' not in calls[0].headers
        await client.aclose()

    asyncio.run(scenario())


def test_gate_held_during_socket_connect_closes_before_auth(tmp_path, monkeypatch):
    bindings, _, identity, _ = approved(tmp_path)
    rows = []
    discovered(monkeypatch, rows)
    gate, order = RobotGate(), []

    class Socket:
        async def send(self, data):
            order.append('auth')

        async def close(self):
            order.append('close')

    async def connect(*args, **kwargs):
        gate.held = 'needs_new_code'
        return Socket()

    monkeypatch.setattr('websockets.connect', connect)
    endpoint = bindings.endpoint(dict(robot_id='rosy_09', address=PINNED), 'runtime-fixture')
    client = EnrolledRobotClient(endpoint, gate, tls_bindings=bindings,
                                 transport=httpx.MockTransport(lambda r: httpx.Response(200, json=identity)))

    async def scenario():
        with pytest.raises(Exception, match='sockets stay closed'):
            await client._open_socket(client.events_url([]))
        assert order == ['close']
        await client.aclose()

    asyncio.run(scenario())


def test_tls_config_without_enrollment_cannot_be_ignored(monkeypatch):
    from fleet.cli import parse_args, run_console
    monkeypatch.setenv('ROSY_ENROLLED_TLS_BINDINGS_FILE', '/run/rosy-config/bindings.json')
    with pytest.raises(SystemExit, match='bindings.*credential-key'):
        run_console(parse_args(['console']))


def test_logout_identity_failure_retains_pending_marker(tmp_path, monkeypatch):
    old, _, _, discovery, store, _ = build(tmp_path, {PINNED: FakeCore()})
    discovery.replace_scan([scan_row()])
    asyncio.run(old.enroll(code=CODE, principal_id='alice', discovery_name=NAME))
    bindings, _, identity, _ = approved(tmp_path)
    rows, calls = [], []
    discovered(monkeypatch, rows)

    def receive(request):
        calls.append(request)
        return httpx.Response(200, json=identity) if request.url.path.endswith('/identity') else httpx.Response(204)

    service = EnrollmentService(store, SiteRoster(FleetConsole([], [])), key=old._key,
                                tls_bindings=bindings, clock=old._clock, transport=httpx.MockTransport(receive))
    service.load()
    marker, cipher = store.tls_markers(), store.ciphertext('rosy_09')
    identity['receiver_id'] = 'different'

    async def scenario():
        result = await service.unenroll('rosy_09', principal_id='alice')
        assert result['state'] == 'pending_logout'
        assert store.get('rosy_09')['state'] == 'pending_logout'
        assert store.tls_markers() == marker and store.ciphertext('rosy_09') == cipher
        assert len(calls) == 1 and 'Authorization' not in calls[0].headers
        identity['receiver_id'] = 'rosy_09'
        await service.on_discovery([scan_row('192.168.1.203:8080')])
        assert store.get('rosy_09') is None and not store.tls_markers()
        assert calls[-1].url.path == '/api/v1/auth/logout' and calls[-1].url.scheme == 'https'

    asyncio.run(scenario())
