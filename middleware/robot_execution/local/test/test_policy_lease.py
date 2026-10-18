"""SIM lease receipt, conservative clocks, renewal handoff and permanent closure."""
import copy
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'middleware/devices/omx/adapter'),
               str(ROOT/'middleware/robot_execution/local/src')]

from rosy.contracts.skill import AttemptIdentity
from rosy.execution.local.policy_lease import FleetLeaseConsumer, FleetPolicyHttp, LeaseScope


@pytest.fixture
def wire():
    clock = [100.0]
    identity = AttemptIdentity('sim-mission', 'step', 'action', 'attempt', 'cell', 'arm', 'a'*64, 2, 7)
    scope = LeaseScope(identity, 'episode', 'policy-pin', 'owner-session', 'window', 'rig', 'cal', 'sim reach')
    state = dict(workcell_id='cell', now_ns=1_000_000_000_000,
        policies=[dict(policy_revision='policy-pin', rig_revision='rig', calibration_revision='cal', stage='L3')],
        confirmations=[], incidents=[],
        windows=[dict(window_id='window', policy_revision='policy-pin', kind='supervised', scope='sim reach',
            active=True, approved_by='second-sim-admin', closed_ns=None, expires_ns=2_000_000_000_000)])
    calls = []
    response = dict(lease_id='lease', window_id='window', episode_id='episode', owner_session_id='owner-session',
        issued_ns=1_000_075_000_000, expires_ns=1_001_075_000_000, workcell_id='cell',
        policy_revision='policy-pin', clock='fleet_wall_ns', device_delivery='not_connected')
    def request(method, path, body=None):
        calls.append((method, path, body))
        clock[0] += .05
        state['now_ns'] = 1_000_000_000_000+int((clock[0]-100)*1e9)
        return copy.deepcopy(state if method == 'GET' else response)
    consumer = FleetLeaseConsumer(scope, request=request, monotonic=lambda: clock[0])
    return SimpleNamespace(clock=clock, scope=scope, state=state, calls=calls, response=response,
                           request=request, consumer=consumer)


def test_receipt_charges_all_network_time_and_binds_local_identity(wire):
    lease = wire.consumer.acquire()
    assert lease.identity == wire.scope.identity and lease.owner_session_id == 'owner-session'
    assert lease.issued_at_ns == 100_000_000_000 and lease.expires_at_ns == 101_000_000_000
    assert wire.clock[0] > 100.14 and wire.consumer.authority(lease)
    assert [call[0] for call in wire.calls] == ['GET', 'POST', 'GET']
    assert wire.calls[1][2] == dict(episode_id='episode', owner_session_id='owner-session', duration_ms=1000)
    wire.clock[0] = 101.0
    assert not wire.consumer.authority(lease)
    wire.clock[0] = 100.5
    assert not wire.consumer.authority(lease), 'expiry/clock fault must never reopen authority'


@pytest.mark.parametrize('field,value', [('workcell_id','other'), ('window_id','other'),
    ('policy_revision','other'), ('episode_id','other'), ('owner_session_id','other'),
    ('clock','owner_monotonic'), ('issued_ns',True), ('expires_ns',1_002_000_000_001)])
def test_wrong_or_excessive_lease_never_authorizes(wire, field, value):
    wire.response[field] = value
    with pytest.raises(PermissionError): wire.consumer.acquire()


@pytest.mark.parametrize('row,field,value', [('windows','active',False), ('windows','kind','shadow'),
    ('windows','scope','different task'), ('windows','policy_revision','other'),
    ('policies','rig_revision','other'), ('policies','calibration_revision','other'), ('policies','stage','L2')])
def test_approval_and_install_scope_are_not_inferred_from_response(wire, row, field, value):
    wire.state[row][0][field] = value
    with pytest.raises(PermissionError): wire.consumer.acquire()


def test_post_issue_readback_catches_window_closure(wire):
    def request(method, path, body=None):
        result = wire.request(method, path, body)
        if method == 'POST': wire.state['windows'][0]['active'] = False
        return result
    consumer = FleetLeaseConsumer(wire.scope, request=request, monotonic=lambda: wire.clock[0])
    with pytest.raises(PermissionError): consumer.acquire()


def test_late_response_does_not_extend_deadline(wire):
    def request(method, path, body=None):
        wire.clock[0] += .4
        return wire.request(method, path, body)
    consumer = FleetLeaseConsumer(wire.scope, request=request, monotonic=lambda: wire.clock[0])
    with pytest.raises(PermissionError): consumer.acquire()


def test_renewal_cannot_bridge_expired_old_authority_even_if_new_lease_is_live(wire):
    old = wire.consumer.acquire()
    wire.clock[0] = 100.4
    wire.response.update(issued_ns=1_000_750_000_000, expires_ns=1_001_750_000_000)
    def request(*args):
        wire.clock[0] += .18
        return wire.request(*args)
    wire.consumer.request = request
    with pytest.raises(PermissionError): wire.consumer.renew(SimpleNamespace(lease=old))
    assert not wire.consumer.authority(old)
    with pytest.raises(PermissionError): wire.consumer.acquire()


def test_renewal_accepts_old_and_pending_then_commits_new_authority(wire):
    old = wire.consumer.acquire()
    wire.clock[0] = 100.4
    wire.response.update(issued_ns=1_000_475_000_000, expires_ns=1_001_475_000_000)
    class Session:
        lease = old
        def renew(self, new):
            assert wire.consumer.authority(self.lease) and wire.consumer.authority(new)
            self.lease = new
    session = Session()
    new = wire.consumer.renew(session)
    assert session.lease == new and new.lease_id == old.lease_id
    assert new.expires_at_ns == 101_400_000_000
    assert wire.calls[4][2]['lease_id'] == old.lease_id
    assert not wire.consumer.authority(old) and wire.consumer.authority(new)


def test_replayed_renewal_and_network_failure_latch_closed(wire):
    old = wire.consumer.acquire()
    with pytest.raises(PermissionError): wire.consumer.renew(SimpleNamespace(lease=old))
    assert not wire.consumer.authority(old)
    wire.response.update(issued_ns=1_000_475_000_000, expires_ns=1_001_475_000_000)
    with pytest.raises(PermissionError): wire.consumer.acquire()


def test_network_failure_and_close_cannot_be_reopened(wire):
    old = wire.consumer.acquire()
    wire.consumer.request = lambda *args: (_ for _ in ()).throw(OSError('offline'))
    with pytest.raises(PermissionError): wire.consumer.renew(SimpleNamespace(lease=old))
    assert not wire.consumer.authority(old)
    wire.consumer.close()
    with pytest.raises(PermissionError): wire.consumer.acquire()


def test_close_during_transport_rejects_late_success(wire):
    def request(*args):
        result = wire.request(*args)
        wire.consumer.close()
        return result
    wire.consumer.request = request
    with pytest.raises(PermissionError): wire.consumer.acquire()


def test_unissued_identity_alias_is_never_authority(wire):
    lease = wire.consumer.acquire()
    assert not wire.consumer.authority(replace(lease, owner_session_id='another-owner'))


@pytest.mark.parametrize('issued,expires', [(998_000_000_000,999_000_000_000),
    (1_000_500_000_000,1_001_500_000_000)])
def test_expired_or_future_fleet_response_is_not_reanchored(wire, issued, expires):
    wire.response.update(issued_ns=issued, expires_ns=expires)
    with pytest.raises(PermissionError): wire.consumer.acquire()


@pytest.mark.parametrize('key,row', [('confirmations',dict(resolution=None)),
                                     ('incidents',dict(cleared_ns=None))])
def test_post_issue_governance_stop_closes_authority(wire, key, row):
    def request(method, path, body=None):
        result = wire.request(method, path, body)
        if method == 'POST': wire.state[key].append(row)
        return result
    consumer = FleetLeaseConsumer(wire.scope, request=request, monotonic=lambda: wire.clock[0])
    with pytest.raises(PermissionError): consumer.acquire()


def test_fleet_transport_never_uses_environment_proxy(tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    monkeypatch.setenv('http_proxy', 'http://proxy.invalid:8888')
    monkeypatch.setenv('no_proxy', '')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')
    server = HTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    token = tmp_path/'token'
    token.write_text('test-only')
    client = FleetPolicyHttp(f'http://127.0.0.1:{server.server_port}', token, loopback_sim=True)
    try:
        assert client('GET', '/api/fleet/workcells/cell/policy') == {}
    finally:
        server.shutdown()
        worker.join(2)
        server.server_close()


def test_fleet_transport_has_total_deadline_for_dripping_body(tmp_path):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    import time

    stopped = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '22')
            self.end_headers()
            try:
                for part in [b' ']*20+[b'{}']:
                    self.wfile.write(part)
                    self.wfile.flush()
                    if stopped.wait(.04): break
            except (BrokenPipeError, ConnectionResetError): pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    token = tmp_path/'token'
    token.write_text('test-only')
    client = FleetPolicyHttp(f'http://127.0.0.1:{server.server_port}', token, loopback_sim=True)
    try:
        started = time.monotonic()
        with pytest.raises(PermissionError): client('GET', '/api/fleet/workcells/cell/policy')
        assert time.monotonic()-started < .5
    finally:
        stopped.set()
        server.shutdown()
        worker.join(2)
        server.server_close()
