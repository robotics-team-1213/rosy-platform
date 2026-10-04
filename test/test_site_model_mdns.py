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
    pub = model.Publisher(22, 'approved-model', spawn=spawn)
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
    pub = model.Publisher(22, 'approved-model', spawn=spawn)
    try:
        pub.update(True)
        assert children[0].poll() is None
        pub.close()
        assert children[0].poll() is not None
    finally:
        pub.close()
