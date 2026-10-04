"""Model discovery advertises a real LAN SSH listener, never a made-up port."""
import importlib.util
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'deploy/site/model-mdns.py'
spec = importlib.util.spec_from_file_location('model_mdns', SCRIPT)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


@pytest.mark.parametrize('banner,ready', [(b'SSH-2.0-fixture\r\n', True),
                                         (b'HTTP/1.1 200 OK\r\n', False), (b'', False)])
def test_real_socket_banner_is_required_after_lan_listener_check(banner, ready):
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen()
    port = server.getsockname()[1]
    def serve():
        with server:
            conn, _ = server.accept()
            with conn:
                if banner:
                    conn.sendall(banner)
    worker = threading.Thread(target=serve)
    worker.start()
    def listeners(argv, **kw):
        assert argv == ['ss', '-H', '-ltn', f'sport = :{port}']
        return subprocess.CompletedProcess(argv, 0, f'LISTEN 0 128 0.0.0.0:{port} 0.0.0.0:*\n', '')
    try:
        assert model.ssh_ready(port, runner=listeners) is ready
    finally:
        worker.join(timeout=3)
        assert not worker.is_alive()


def test_loopback_only_or_failed_listener_probe_cannot_advertise():
    def connector(*a, **kw):
        pytest.fail('loopback-only listener must not be probed as LAN capable')
    for result in [subprocess.CompletedProcess([], 0, 'LISTEN 0 128 127.0.0.1:22 0.0.0.0:*\n', ''),
                   subprocess.CompletedProcess([], 1, '', 'denied')]:
        assert not model.ssh_ready(22, runner=lambda *a, **kw: result, connector=connector)


def test_owned_publisher_withdraws_on_listener_loss_and_exit():
    class Child:
        done = None
        stopped = 0
        def poll(self): return self.done
        def terminate(self): self.stopped += 1; self.done = 0
        def wait(self, timeout): return self.done
        def kill(self): pytest.fail('graceful fixture must not require kill')
    children, commands = [], []
    def spawn(argv, **kw):
        commands.append(argv)
        child = Child()
        children.append(child)
        return child
    pub = model.Publisher(22, 'approved-model', spawn=spawn, which=lambda _: '/fixture/avahi-publish-service')
    pub.update(False)
    assert children == []
    pub.update(True)
    pub.update(True)
    assert len(children) == 1
    assert commands[0][:4] == ['avahi-publish-service', 'ROSY Model approved-model', '_rosy-model._tcp', '22']
    assert set(commands[0][4:]) == {'product=rosy', 'role=model-host', 'proto=ssh/2', 'tls=none', 'transport=ssh'}
    pub.update(False)
    assert children[0].stopped == 1
    pub.update(True)
    assert len(children) == 2
    pub.close()
    assert children[1].stopped == 1


def test_install_and_service_preserve_operator_keys_and_run_outside_job_lock():
    install = (ROOT / 'deploy/site/install-model-code.sh').read_text('utf-8')
    unit = (ROOT / 'deploy/site/rosy-model-advertise.service').read_text('utf-8')
    assert 'model-mdns.py' in install and 'discovery_txt.py' in install
    assert 'rosy-model-advertise.service' in install
    assert '-I %h/.local/lib/rosy-model-code/model-mdns.py' in unit
    assert 'rosy_model_code.py' not in unit  # Long-running advert never acquires model job lock.
    assert 'KillMode=control-group' in unit
    assert 'PrivateNetwork=yes' not in unit
    assert 'enrolled key differs' in install and 'cmp -s' in install


def test_installed_isolated_loader_uses_exact_sibling_policy(tmp_path):
    import shutil
    shutil.copyfile(SCRIPT, tmp_path / SCRIPT.name)
    canonical = ROOT / 'contracts/foundation/core_common/protocol/discovery_txt.py'
    shutil.copyfile(canonical, tmp_path / canonical.name)
    code = "import runpy,sys; p=runpy.run_path(sys.argv[1])['policy'](); assert p.MODEL == '_rosy-model._tcp'; assert p.REQUIRED[p.MODEL]['transport']=='ssh'"
    subprocess.run([sys.executable, '-I', '-c', code, str(tmp_path / SCRIPT.name)], check=True, timeout=5)


def test_real_owned_process_is_reaped_on_close():
    children = []
    def spawn(_argv, **kw):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kw)
        children.append(child)
        return child
    pub = model.Publisher(22, 'approved-model', spawn=spawn, which=lambda _: '/fixture/avahi-publish-service')
    try:
        pub.update(True)
        assert children[0].poll() is None
        pub.close()
        assert children[0].poll() is not None
    finally:
        pub.close()

class FakeDBus:
    Int32 = staticmethod(lambda value: ('i', value))
    UInt32 = staticmethod(lambda value: ('u', value))
    UInt16 = staticmethod(lambda value: ('q', value))
    ByteArray = staticmethod(lambda value: ('ay', value))
    Array = staticmethod(lambda value, signature: ('a'+signature, value))

    def __init__(self, fail=None):
        self.calls, self.connections = [], []
        self.fail, self.group_state = fail, 2
        self.host = 'approved-model'

    def SystemBus(self, private):
        assert private is True
        if self.fail == 'SystemBus': raise RuntimeError('fixture private bus unavailable')
        owner = self
        class Bus:
            closed = False
            def get_object(self, name, path, introspect):
                assert name == 'org.freedesktop.Avahi' and introspect is False
                return path
            def close(self): self.closed = True; owner.calls.append(('close',))
            def set_exit_on_disconnect(self, value): assert value is False
            def call_blocking(self, dest, path, interface, method, signature, args, timeout):
                assert timeout == 2
                if method == 'GetNameOwner':
                    owner.calls.append((method,args))
                    if owner.fail == method: raise RuntimeError('fixture owner unavailable')
                    return ':1.7'
                assert dest == ':1.7'
                return getattr(owner.Interface(path, interface), method)(*args, timeout=timeout)
        bus = Bus(); self.connections.append(bus)
        return bus

    def Interface(self, proxy, dbus_interface):
        owner = self
        class Proxy:
            def __getattr__(self, method):
                def call(*args, timeout):
                    assert timeout == 2
                    owner.calls.append((method, args))
                    if owner.fail == method: raise RuntimeError('fixture Avahi method failure')
                    if method == 'EntryGroupNew': return '/Client1/EntryGroup1'
                    if method == 'GetState': return owner.group_state
                    if method == 'GetHostName': return owner.host
                return call
        assert dbus_interface in ('org.freedesktop.Avahi.Server', 'org.freedesktop.Avahi.EntryGroup')
        return Proxy()


def fallback(db):
    return model.Publisher(22, 'approved-model', which=lambda _: None, dbus_loader=lambda: db)


def test_dbus_listener_gate_and_dedicated_typed_registration():
    db = FakeDBus(); pub = fallback(db)
    pub.update(False)
    assert not db.connections
    pub.update(True); pub.update(True)
    assert len(db.connections) == 1 and not db.connections[0].closed
    assert [c[0] for c in db.calls].count('EntryGroupNew') == 1
    args = next(c[1] for c in db.calls if c[0] == 'AddService')
    assert args[:3] == (('i', -1), ('i', -1), ('u', 0))
    assert args[3:8] == ('ROSY Model approved-model', '_rosy-model._tcp', '', '', ('q', 22))
    assert args[8][0] == 'aay'
    assert {v[1] for v in args[8][1]} == {b'product=rosy', b'role=model-host', b'proto=ssh/2', b'tls=none', b'transport=ssh'}
    pub.update(False)
    assert db.connections[0].closed
    assert [c[0] for c in db.calls].count('Free') == 1
    pub.update(True)
    assert len(db.connections) == 2
    pub.close(); pub.close()
    assert db.connections[1].closed


@pytest.mark.parametrize('method', ['GetNameOwner', 'EntryGroupNew', 'AddService', 'Commit', 'GetState', 'GetHostName'])
def test_dbus_failure_closes_only_private_owner_and_never_retries_inline(method):
    db = FakeDBus(method); pub = fallback(db)
    with pytest.raises(RuntimeError): pub.update(True)
    assert all(b.closed for b in db.connections)
    count = len(db.connections)
    pub.close()
    assert len(db.connections) == count


def test_dbus_free_failure_still_closes_owner():
    db = FakeDBus(); pub = fallback(db); pub.update(True)
    db.fail = 'Free'; pub.close()
    assert db.connections[0].closed


@pytest.mark.parametrize('state', [0, 3, 4, 99])
def test_avahi_collision_failure_unknown_withdraws_and_exits_for_service_restart(state):
    db = FakeDBus(); pub = fallback(db); pub.update(True); db.group_state = state
    with pytest.raises(RuntimeError): pub.update(True)
    assert db.connections[0].closed


def test_cli_preferred_never_imports_dbus():
    class Child:
        def poll(self): return None
        def terminate(self): pass
        def wait(self, timeout): pass
    def absent(): pytest.fail('CLI path must not import D-Bus')
    pub = model.Publisher(22, 'approved-model', which=lambda _: '/usr/bin/avahi-publish-service', dbus_loader=absent, spawn=lambda *a, **k: Child())
    pub.update(True); pub.close()


def test_missing_dbus_dependency_truthfully_fails_without_advertisement():
    def absent(): raise ImportError('dbus unavailable')
    with pytest.raises(ImportError): model.Publisher(22, 'approved-model', which=lambda _: None, dbus_loader=absent)


def test_host_identity_change_withdraws_no_stale_name_republication():
    db = FakeDBus(); pub = fallback(db); pub.update(True); db.host = 'new-approved-model'
    with pytest.raises(RuntimeError): pub.update(True)
    assert db.connections[0].closed
    assert [c[0] for c in db.calls].count('EntryGroupNew') == 1


def test_daemon_owner_restart_withdraws_old_group_without_new_bus_inline():
    db = FakeDBus(); pub = fallback(db); pub.update(True)
    db.fail = 'GetState'  # Pinned old daemon object disappeared after restart.
    with pytest.raises(RuntimeError): pub.update(True)
    assert db.connections[0].closed and len(db.connections) == 1
    replacement = FakeDBus(); new = fallback(replacement); new.update(True)
    assert len(replacement.connections) == 1
    new.close()


def test_registration_stuck_registering_is_bounded(monkeypatch):
    db = FakeDBus(); db.group_state = 1; pub = fallback(db)
    now = [0]
    monkeypatch.setattr(model.time, 'monotonic', lambda: now[0])
    pub.update(True); now[0] = 10
    with pytest.raises(RuntimeError): pub.update(True)
    assert db.connections[0].closed


def test_cli_exit_does_not_create_five_second_retry_loop():
    class Child:
        done = None
        def poll(self): return self.done
        def terminate(self): self.done = 0
        def wait(self, timeout): return self.done
    calls = []
    def spawn(*a, **k): calls.append(Child()); return calls[-1]
    pub = model.Publisher(22, 'approved-model', spawn=spawn, which=lambda _: '/fixture/cli')
    pub.update(True); calls[0].done = 1
    with pytest.raises(RuntimeError): pub.update(True)
    assert len(calls) == 1
    pub.close()


def test_main_signal_withdraws_private_registration(monkeypatch):
    db = FakeDBus(); handlers = {}
    original = model.Publisher
    class Stop:
        value = False
        def is_set(self): return self.value
        def set(self): self.value = True
        def wait(self, seconds):
            assert seconds == 5
            handlers[model.signal.SIGTERM](None, None)
    monkeypatch.setattr(model.threading, 'Event', Stop)
    monkeypatch.setattr(model.signal, 'signal', lambda signal, callback: handlers.__setitem__(signal, callback))
    monkeypatch.setattr(model.shutil, 'which', lambda name: '/fixture/ss' if name == 'ss' else None)
    monkeypatch.setattr(model.socket, 'gethostname', lambda: 'approved-model')
    monkeypatch.setattr(model, 'ssh_ready', lambda port: True)
    monkeypatch.setattr(model, 'Publisher', lambda port, name: original(port, name, which=lambda _: None, dbus_loader=lambda: db))
    assert model.main([]) == 0
    assert db.connections[0].closed and [c[0] for c in db.calls].count('Free') == 1


def test_main_dependency_failure_reports_no_advertisement(monkeypatch, capsys):
    monkeypatch.setattr(model.shutil, 'which', lambda name: '/fixture/ss' if name == 'ss' else None)
    def unavailable(*args): raise ImportError('system dbus absent')
    monkeypatch.setattr(model, 'Publisher', unavailable)
    with pytest.raises(SystemExit) as result: model.main([])
    assert result.value.code == 2
    assert 'no service is advertised' in capsys.readouterr().err


def test_dns_host_case_is_not_a_new_identity():
    db = FakeDBus(); db.host = 'APPROVED-MODEL'; pub = fallback(db)
    pub.update(True); pub.update(True)
    assert not db.connections[0].closed
    pub.close()


def test_private_bus_connection_failure_has_no_advertisement():
    db = FakeDBus('SystemBus'); pub = fallback(db)
    with pytest.raises(RuntimeError): pub.update(True)
    assert not db.connections and not db.calls
    pub.close()
