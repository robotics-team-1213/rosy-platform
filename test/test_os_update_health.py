"""Trial health uses real durable files; service, projection, signature and watchdog observations are models here."""
import importlib
import subprocess

import pytest

from test_os_update_policy import _trial_policy
from test_os_update_state import TRANSACTION, TRIAL_BOOT


def _health(tmp_path, monkeypatch):
    _, state, root, journal, _, _, _, host = _trial_policy(tmp_path, monkeypatch)
    m = importlib.import_module("os_update_health")
    pending = state.read_state(root)["pending"]
    directory = journal.parent / "rauc"
    directory.mkdir(mode=0o700)
    calls = []
    ready = dict(schema_version=1, boot_id=TRIAL_BOOT, slot="b")
    factory = dict(schema_version=1, **pending["verified"]["metadata"]["native_factory"])
    monkeypatch.setattr(m, "verify_ready", lambda r: ready)
    monkeypatch.setattr(m, "verify_current", lambda r, v: factory)
    monkeypatch.setattr(m, "read_bound_report", lambda r, p: dict(native_factory=factory))
    monkeypatch.setattr(m, "observe_watchdog", lambda r, **k: dict(boot_id=TRIAL_BOOT))
    monkeypatch.setattr(m, "_probe", lambda: None)
    monkeypatch.setattr(m, "_now", lambda: 40_000_000_000)
    frozen = m.Path(m.__file__).parent / "rosy-os-io-guard.conf"
    dropin = root / "etc/systemd/system/rosy-io.service.d/zz-rosy-os-guard.conf"
    dropin.parent.mkdir(parents=True)
    dropin.write_bytes(frozen.read_bytes())
    source = root / "opt/rosy/releases" / factory["release_id"] / "deploy/robot/native/rosy-io.service"
    source.parent.mkdir(parents=True)
    source.write_bytes((m.Path(m.__file__).parent / "rosy-io.service").read_bytes())
    (root / "etc/systemd/system/rosy-io.service").write_bytes(source.read_bytes())
    data = dict(ActiveState="active", SubState="running", MainPID="123", InvocationID="a" * 32,
                Result="success", EnvironmentFiles=m.IO_ENVIRONMENT_FILES,
                DropInPaths="/etc/systemd/system/rosy-io.service.d/zz-rosy-os-guard.conf")
    def run(argv, **kwargs):
        calls.append(argv)
        if "show" in argv:
            if "rosy-navigation.service" in argv:
                value = dict(ActiveState="inactive", MainPID="0", ControlGroup="")
            else:
                value = data
            return subprocess.CompletedProcess(argv, 0, "\n".join(k + "=" + v for k, v in value.items()), "")
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(m, "_empty_cgroup", lambda *a, **kw: None)
    return m, state, root, journal, host, calls, run, data, ready, dropin


def test_trial_health_restarts_inhibited_io_and_binds_durable_receipt_without_committing(tmp_path, monkeypatch):
    m, state, root, journal, host, calls, run, _, _, _ = _health(tmp_path, monkeypatch)
    before = journal.read_bytes()
    report = m.check(root, TRANSACTION, host=host, run=run)
    assert report["boot_id"] == TRIAL_BOOT and report["target_slot"] == "b"
    assert report["samples"]["second_written_at"] > report["samples"]["first_written_at"]
    assert report == m.read_health(root, state.read_state(root)["pending"])
    assert journal.read_bytes() == before
    assert calls.index(["/usr/bin/systemctl", "stop", "rosy-navigation.service"]) < calls.index(
        ["/usr/bin/systemctl", "restart", "rosy-io.service"])
    assert not any("reboot" in command for command in calls)
    assert (root / "run/rosy-os-update/motion.env").read_text() == "ROSY_IO_DRIVE_ENABLED=false\n"


@pytest.mark.parametrize("damage", ["factory", "projection", "watchdog", "api", "environment", "dropin",
    "navigation", "restart", "pid", "invocation", "boot", "deadline", "expired_receipt"])
def test_unknown_or_changed_health_cannot_publish_usable_evidence(tmp_path, monkeypatch, damage):
    m, state, root, journal, host, _, run, data, ready, dropin = _health(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        raise ValueError("modeled observation unavailable")
    if damage in ("factory", "watchdog", "api"):
        monkeypatch.setattr(m, {"factory": "verify_current", "watchdog": "observe_watchdog", "api": "_probe"}[damage], fail)
    elif damage == "projection": ready["boot_id"] = TRANSACTION
    elif damage == "environment": data["EnvironmentFiles"] = "/etc/rosy/runtime.env (ignore_errors=no)"
    elif damage == "dropin": dropin.write_text("[Service]\n")
    elif damage in ("navigation", "restart"):
        original = run
        def run(argv, **kwargs):
            if (damage == "navigation" and "rosy-navigation.service" in argv and "show" in argv
                    or damage == "restart" and "restart" in argv):
                return subprocess.CompletedProcess(argv, 1, "", "unavailable")
            return original(argv, **kwargs)
    elif damage == "deadline": monkeypatch.setattr(m, "_now", lambda: 166_000_000_000)
    elif damage != "expired_receipt":
        original = host.sleep
        def sleep(seconds):
            original(seconds)
            if damage == "pid": data["MainPID"] = "456"
            elif damage == "invocation": data["InvocationID"] = "b" * 32
            else: (root / "proc/sys/kernel/random/boot_id").write_text(TRANSACTION)
        host.sleep = sleep
    before = journal.read_bytes()
    if damage == "expired_receipt":
        m.check(root, TRANSACTION, host=host, run=run)
        monkeypatch.setattr(m, "_now", lambda: 71_000_000_000)
        with pytest.raises(ValueError):
            m.read_health(root, state.read_state(root)["pending"])
    else:
        with pytest.raises(ValueError):
            m.check(root, TRANSACTION, host=host, run=run)
    assert journal.read_bytes() == before


def test_health_with_a_fake_root_never_uses_the_real_service_manager(tmp_path):
    m = importlib.import_module("os_update_health")
    with pytest.raises(ValueError, match="explicit test runner"):
        m.check(tmp_path, TRANSACTION)


@pytest.mark.parametrize("damage", ["samples", "projection", "factory_schema", "watchdog", "services", "service_pid"])
def test_malformed_private_health_receipt_is_a_hold(tmp_path, monkeypatch, damage):
    import json
    m, state, root, _, host, _, run, _, _, _ = _health(tmp_path, monkeypatch)
    m.check(root, TRANSACTION, host=host, run=run)
    pending = state.read_state(root)["pending"]
    target = m._report_path(root, pending)
    value = json.loads(target.read_text())
    if damage == "factory_schema": value["native_factory"]["schema_version"] = True
    elif damage == "service_pid": value["services"]["rosy-io.service"]["MainPID"] = "0"
    else: value[damage] = []
    target.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        m.read_health(root, pending)


@pytest.mark.parametrize("status,accepted", [(200, True), (401, True), (503, False), (302, True)])
def test_actual_loopback_probe_uses_existing_core_readiness_contract(monkeypatch, status, accepted):
    import http.server
    import threading
    m = importlib.import_module("os_update_health")
    paths = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(status)
            self.end_headers()
        def log_message(self, *args):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    monkeypatch.setenv("ROSY_API_PORT", str(server.server_port))
    monkeypatch.setenv("ROSY_API_TLS", "none")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    worker.start()
    try:
        if accepted: m._probe()
        else:
            with pytest.raises(ValueError): m._probe()
        assert paths == ["/api/v1"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_frozen_trial_health_import_does_not_depend_on_mutable_sdk(tmp_path):
    import sys
    from test_os_frozen_firstboot import _prefix, _stage
    prefix = _prefix(tmp_path)
    _stage(prefix)
    for source in (prefix / "native-runtime").glob("*.py"):
        source.write_text("raise RuntimeError('mutable SDK executed')\n")
    frozen = prefix / "os-bootstrap/native-runtime"
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import os_update_health
for name in ('os_update_health', 'os_update_policy', 'os_update_install', 'os_update_watchdog', 'os_rauc_service'):
    assert Path(sys.modules[name].__file__).is_relative_to(Path(sys.argv[1]))
assert Path(os_update_health.__file__).with_name('rosy-os-io-guard.conf').is_file()
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(frozen)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("fault", [None, "hostname", "trust"])
def test_actual_tls_probe_verifies_the_configured_device_identity(tmp_path, monkeypatch, fault):
    from datetime import datetime, timedelta, timezone
    import http.server
    import ssl
    import threading
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    m = importlib.import_module("os_update_health")
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "rosy-fixture.local")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("rosy-fixture.local")]), critical=False)
            .sign(key, hashes.SHA256()))
    ca, private = tmp_path / "ca.pem", tmp_path / "key.pem"
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
        def log_message(self, *args):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, private)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("ROSY_API_PORT", str(server.server_port))
    monkeypatch.setenv("ROSY_API_TLS", "required")
    monkeypatch.setenv("ROSY_API_TLS_HOST", "other.local" if fault == "hostname" else "rosy-fixture.local")
    monkeypatch.setenv("ROSY_API_TLS_CA_FILE", str(private if fault == "trust" else ca))
    try:
        if fault:
            with pytest.raises(ssl.SSLError): m._probe()
        else: m._probe()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
