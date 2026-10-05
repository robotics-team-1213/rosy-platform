"""User discovery bootstrap with fake host commands; no live unit or Avahi writes."""

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy/site/install-user-discovery.py"
spec = importlib.util.spec_from_file_location("site_user_discovery", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class Host:
    def __init__(self, *, linger="yes", duplicate=None):
        self.calls = []
        self.linger = linger
        self.duplicate = duplicate

    def __call__(self, argv):
        self.calls.append(argv)
        text, code = "", 0
        if argv[0] == "loginctl":
            text = self.linger
        elif argv[:3] == ["systemctl", "--user", "is-active"]:
            code = 3
        elif argv[:2] == ["systemctl", "is-enabled"]:
            code = 0 if argv[-1] == self.duplicate else 1
        elif argv[:2] == ["systemctl", "is-active"]:
            code = 0 if argv[-1] in ("avahi-daemon.service", self.duplicate) else 3
        return subprocess.CompletedProcess(argv, code, text, "")


def test_install_keeps_one_secret_private_and_uses_user_units(tmp_path):
    host = Host()
    ca, token = tmp_path / "ca.crt", tmp_path / "selected-token"
    ca.write_text("public CA")
    token.write_text("selected-discovery-value")
    installed = tool.install(tmp_path / "home", ca, token, "site-pc.local", 8443,
                             runner=host, avahi_dir=tmp_path / "system-avahi", user="operator")
    state = tmp_path / "home/.local/share/rosy/site-discovery"
    assert (state / "discovery_token").read_text() == token.read_text()
    assert (state / "site-ca.crt").read_text() == ca.read_text()
    if os.name == "posix":
        assert (state / "discovery_token").stat().st_mode & 0o777 == 0o600
        assert (state / "site-ca.crt").stat().st_mode & 0o777 == 0o644
    assert json.loads((state / "config.json").read_text()) == {"tls_host": "site-pc.local", "port": 8443}
    for name in installed:
        text = (tmp_path / "home/.config/systemd/user" / name).read_text()
        assert "selected-discovery-value" not in text
        assert "sudo" not in text and "User=" not in text
    assert ["systemctl", "--user", "enable", "--now", *tool.ENABLED] in host.calls
    bridge = (state / "mdns-bridge.py").read_text()
    assert bridge == (ROOT / "deploy/site/mdns-bridge.py").read_text()


@pytest.mark.parametrize("duplicate", tool.SYSTEM_UNITS)
def test_install_refuses_active_root_services_before_writing(tmp_path, duplicate):
    with pytest.raises(tool.InstallError, match="system discovery"):
        tool.preflight(Host(duplicate=duplicate), tmp_path, "operator")


def test_failed_root_units_and_enabled_timer_do_not_block_fallback(tmp_path):
    host = Host(duplicate="rosy-mdns-bridge.timer")
    tool.preflight(host, tmp_path, "operator")


def test_known_unreadable_root_xml_is_left_in_place(tmp_path, monkeypatch):
    target = tmp_path / "rosy-fleet.service"
    target.write_text("unreadable Avahi artifact")
    original = Path.stat

    def metadata(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path == target:
            fields = list(value)
            fields[0], fields[4] = 0o100600, 0
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(Path, "stat", metadata)
    tool.preflight(Host(), tmp_path, "operator")
    assert target.read_text() == "unreadable Avahi artifact"


def test_inactive_xml_advertisement_also_blocks_fallback(tmp_path):
    (tmp_path / "rosy-fleet.service").write_text("already advertised")
    with pytest.raises(tool.InstallError, match="Avahi service"):
        tool.preflight(Host(), tmp_path, "operator")


def test_linger_is_required_without_enabling_it(tmp_path):
    host = Host(linger="no")
    with pytest.raises(tool.InstallError, match="Linger=yes"):
        tool.preflight(host, tmp_path, "operator")
    assert not any("enable-linger" in call for call in host.calls)


def test_temporary_user_advertisers_must_be_stopped_first(tmp_path):
    host = Host()

    def running(argv):
        if argv[:3] == ["systemctl", "--user", "is-active"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        return host(argv)

    with pytest.raises(tool.InstallError, match="stop it"):
        tool.preflight(running, tmp_path, "operator")


def test_bridge_command_reuses_verified_loopback_implementation(tmp_path):
    argv = tool.runtime_command("bridge", tmp_path, {"tls_host": "site-pc.local", "port": 8443})
    assert argv == ["/usr/bin/python3", str(tmp_path / "mdns-bridge.py"), "--tls-host", "site-pc.local",
                    "--port", "8443", "--ca-file", str(tmp_path / "site-ca.crt"),
                    "--token-file", str(tmp_path / "discovery_token")]


def test_timer_coalescing_stays_inside_fleet_scanner_lease(tmp_path):
    timer = tool.render_units(tmp_path)["rosy-user-mdns-bridge.timer"]
    interval = int(re.search(r"OnUnitInactiveSec=(\d+)s", timer).group(1))
    accuracy = re.search(r"AccuracySec=(\d+)s", timer)
    # systemd defaults to one minute without AccuracySec; Fleet expires at 45 s.
    worst_delay = interval + (int(accuracy.group(1)) if accuracy else 60)
    assert worst_delay < 45


def test_advertisers_share_the_exact_existing_protocol_txt(tmp_path):
    for role, kind in (("fleet", "_rosy-fleet._tcp"), ("overhead", "_rosy-overhead._tcp")):
        argv = tool.runtime_command(role, ROOT / "deploy/site", {"tls_host": "site-pc.local", "port": 8443})
        assert argv[:2] == ["/usr/bin/avahi-publish-service", "--host=site-pc.local"]
        assert kind in argv and "tls=required" in argv and "product=rosy" in argv
        assert "tls_host=site-pc.local" in argv


def test_explicit_pair_capability_is_overhead_only():
    config = {"tls_host": "site-pc.local", "port": 8443, "pair": True}
    overhead = tool.runtime_command("overhead", ROOT / "deploy/site", config)
    fleet = tool.runtime_command("fleet", ROOT / "deploy/site", config)
    assert "pair=rosy-pair/1" in overhead
    assert not any(item.startswith(("pair=", "peer=")) for item in fleet)


@pytest.mark.parametrize("flags", [{"pair": "true"}, {"camera_peer": 1},
                                  {"pair": False, "camera_peer": True}])
def test_invalid_capability_config_is_refused_before_any_advertisement(flags):
    with pytest.raises(tool.InstallError):
        tool.runtime_command("overhead", ROOT / "deploy/site",
                             {"tls_host": "site-pc.local", "port": 8443, **flags})


@pytest.fixture
def receiver_identity():
    import base64
    import hashlib
    import ssl
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.DER,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)
    digest = hashlib.sha256(public).hexdigest()
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "fixture site CA")])
    now = datetime.now(timezone.utc)
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(1).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
          .sign(key, hashes.SHA256()))
    pem = ca.public_bytes(serialization.Encoding.PEM).decode()
    der = ssl.PEM_cert_to_DER_cert(pem)
    identity = dict(profile="rosy.camera-peer/1", audience="fleet-camera-ingest",
                    device_kind="overhead-camera", source_role="camera",
                    receiver_id="fleet-" + digest[:32], receiver_public_key=base64.b64encode(public).decode(),
                    receiver_key_sha256=digest, tls_hostname="site-pc.local", tls_ca_pem=pem,
                    tls_ca_sha256=hashlib.sha256(der).hexdigest())
    return identity, der


@pytest.mark.parametrize("change", ["profile", "source_role", "receiver_key_sha256", "receiver_id",
                                   "tls_hostname", "tls_ca_sha256", "tls_ca_pem", "receiver_public_key",
                                   "missing", "extra", "duplicate", "oversized"])
def test_receiver_binding_denies_incomplete_or_mismatched_identity(receiver_identity, change):
    identity, anchor = receiver_identity
    if change == "missing": identity.pop("audience")
    elif change == "extra": identity["approved"] = True
    elif change not in {"duplicate", "oversized"}: identity[change] = "wrong"
    payload = json.dumps(identity).encode()
    if change == "duplicate": payload = payload[:-1] + b',"profile":"rosy.camera-peer/1"}'
    if change == "oversized": payload += b" " * 16385
    with pytest.raises(tool.InstallError):
        tool.camera_peer_binding(payload, "site-pc.local", anchor)


def test_verified_peer_advertisement_preserves_owner_and_never_grants_trust(receiver_identity, monkeypatch):
    identity, anchor = receiver_identity
    binding = tool.camera_peer_binding(json.dumps(identity).encode(), "site-pc.local", anchor)
    checks = []
    def verify(host, port, ca):
        checks.append((host, port, ca))
        return binding
    monkeypatch.setattr(tool, "verify_camera_peer", verify)
    config = dict(tls_host="site-pc.local", port=8443, pair=True, camera_peer=True, camera_peer_binding=binding)
    argv = tool.runtime_command("overhead", ROOT / "deploy/site", config)
    assert "pair=rosy-pair/1" in argv and "peer=rosy.camera-peer/1" in argv
    assert checks == [("site-pc.local", 8443, ROOT / "deploy/site/site-ca.crt")]
    assert not any(word in " ".join(argv).lower() for word in ("bearer", "approved=", "readiness=", "token="))
    tool.runtime_command("fleet", ROOT / "deploy/site", config)
    assert len(checks) == 1
    config["camera_peer_binding"] = {**binding, "receiver_id": "fleet-foreign"}
    with pytest.raises(tool.InstallError, match="identity changed"):
        tool.runtime_command("overhead", ROOT / "deploy/site", config)


def test_failed_receiver_probe_leaves_secret_ca_units_and_configuration_unchanged(tmp_path, monkeypatch):
    ca, token = tmp_path / "ca", tmp_path / "token"
    ca.write_bytes(b"existing public CA"); token.write_bytes(b"existing-selected-token")
    home = tmp_path / "home"
    state = home / ".local/share/rosy/site-discovery"
    state.mkdir(parents=True)
    for name in ("site-ca.crt", "discovery_token", "config.json"):
        (state / name).write_bytes(b"previous preserved bytes")
    before = {p: p.read_bytes() for p in state.iterdir()}
    host = Host()
    def unavailable(*args): raise tool.InstallError("camera peer receiver identity unavailable")
    monkeypatch.setattr(tool, "verify_camera_peer", unavailable)
    with pytest.raises(tool.InstallError, match="unavailable"):
        tool.install(home, ca, token, "site-pc.local", 8443, runner=host,
                     avahi_dir=tmp_path / "system-avahi", user="operator", pair=True, camera_peer=True)
    assert {p: p.read_bytes() for p in state.iterdir()} == before
    assert not (home / ".config").exists()
    assert not any("enable" in call or "daemon-reload" in call for call in host.calls)


def test_successful_install_persists_only_explicit_verified_metadata(tmp_path, monkeypatch, receiver_identity):
    identity, anchor = receiver_identity
    binding = tool.camera_peer_binding(json.dumps(identity).encode(), "site-pc.local", anchor)
    ca, token = tmp_path / "ca", tmp_path / "token"
    ca.write_bytes(identity["tls_ca_pem"].encode()); token.write_bytes(b"selected-existing-token")
    monkeypatch.setattr(tool, "verify_camera_peer", lambda *args: binding)
    tool.install(tmp_path / "home", ca, token, "site-pc.local", 8443, runner=Host(),
                 avahi_dir=tmp_path / "system-avahi", user="operator", pair=True, camera_peer=True)
    state = tmp_path / "home/.local/share/rosy/site-discovery"
    assert json.loads((state / "config.json").read_text()) == dict(
        tls_host="site-pc.local", port=8443, pair=True, camera_peer=True, camera_peer_binding=binding)
    assert (state / "site-ca.crt").read_bytes() == ca.read_bytes()
    assert (state / "discovery_token").read_bytes() == token.read_bytes()


@pytest.mark.parametrize("status", [200, 404, 302])
def test_identity_transport_uses_existing_ca_named_tls_and_only_read_only_get(
        tmp_path, monkeypatch, receiver_identity, status):
    import ssl
    identity, anchor = receiver_identity
    ca = tmp_path / "ca.crt"; ca.write_text(identity["tls_ca_pem"])
    real_context = ssl.create_default_context(cafile=str(ca))
    observed = {}
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, value): observed['timeout'] = value
        def sendall(self, value): observed['request'] = value
    raw = Socket()
    class Context:
        verify_flags = real_context.verify_flags
        def get_ca_certs(self, binary_form): return real_context.get_ca_certs(binary_form=binary_form)
        def wrap_socket(self, connection, server_hostname):
            assert connection is raw
            observed['hostname'] = server_hostname
            return raw
    def context(*, cafile):
        assert cafile == str(ca)
        assert real_context.verify_mode == ssl.CERT_REQUIRED and real_context.check_hostname
        return Context()
    def connect(address, timeout):
        observed['address'], observed['connect_timeout'] = address, timeout
        return raw
    class Response:
        def __init__(self, connection): assert connection is raw; self.status = status
        def begin(self): pass
        def read(self, count): assert count == 16385; return json.dumps(identity).encode()
    monkeypatch.setattr(tool.ssl, "create_default_context", context)
    monkeypatch.setattr(tool.socket, "create_connection", connect)
    monkeypatch.setattr(tool.http.client, "HTTPResponse", Response)
    if status == 200:
        assert tool.verify_camera_peer("site-pc.local", 8443, ca) == dict(
            receiver_id=identity["receiver_id"], receiver_key_sha256=identity["receiver_key_sha256"])
    else:
        with pytest.raises(tool.InstallError, match="unavailable"):
            tool.verify_camera_peer("site-pc.local", 8443, ca)
    assert observed == dict(address=("127.0.0.1", 8443), connect_timeout=5, hostname="site-pc.local",
                           timeout=5, request=b"GET /api/fleet/pairing/v2/identity HTTP/1.1\r\n"
                           b"Host: site-pc.local:8443\r\nConnection: close\r\n\r\n")


@pytest.mark.parametrize("flags", [{"pair": 0}, {"camera_peer": ""}])
def test_installer_rejects_falsey_nonboolean_flags_before_host_commands(tmp_path, flags):
    host = Host()
    with pytest.raises(tool.InstallError, match="boolean"):
        tool.install(tmp_path, tmp_path / "ca", tmp_path / "token", "site-pc.local", 8443,
                     runner=host, **flags)
    assert host.calls == []


def test_secret_destination_symlink_is_refused(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX symlink permissions")
    outside = tmp_path / "outside"
    outside.write_text("keep")
    destination = tmp_path / "token"
    destination.symlink_to(outside)
    with pytest.raises(tool.InstallError, match="symlink"):
        tool.write_file(destination, b"replace", 0o600)
    assert outside.read_text() == "keep"
