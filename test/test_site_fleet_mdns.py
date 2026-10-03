"""The site locator treats mDNS as a hint, never as a trust decision."""

import importlib.util
import os
from pathlib import Path
from xml.etree import ElementTree

import pytest


PATH = Path(__file__).resolve().parents[1] / "deploy/site/fleet-mdns.py"


def _module():
    spec = importlib.util.spec_from_file_location("rosy_site_fleet_mdns", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _robot_module():
    path = (Path(__file__).resolve().parents[1]
            / "src/runtime/services/core_features/fleet_agent/discovery.py")
    spec = importlib.util.spec_from_file_location("rosy_robot_fleet_mdns", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(host="fleet-a.local", address="192.168.1.20", port=8443,
         txt='"product=rosy" "role=fleet" "proto=site-v1" "tls=required"'):
    return (f'=;eth0;IPv4;ROSY Fleet;_rosy-fleet._tcp;local;{host};'
            f'{address};{port};{txt}')


def test_advertisement_contains_only_public_service_metadata():
    root = ElementTree.fromstring(_module().render_service(8443))
    service = root.find("service")
    assert service.findtext("type") == "_rosy-fleet._tcp"
    assert service.findtext("port") == "8443"
    assert root.find("name").attrib["replace-wildcards"] == "yes"
    assert {item.text for item in service.findall("txt-record")} == {
        "product=rosy", "role=fleet", "proto=site-v1", "tls=required",
    }
    with pytest.raises(ValueError):
        _module().render_service(0)


def test_publish_replaces_service_file_with_configured_port(tmp_path):
    module = _module()
    output = tmp_path / "rosy-fleet.service"
    output.write_text("old service", encoding="utf-8")
    module.publish_service(output, 9443)
    assert ElementTree.fromstring(output.read_text(encoding="utf-8")).findtext(
        "service/port") == "9443"
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes are required")
@pytest.mark.parametrize("role", ["fleet", "overhead"])
def test_public_advertisement_is_readable_before_atomic_replace(tmp_path, monkeypatch, role):
    module = _module()
    output = tmp_path / "rosy.service"
    output.write_text("old advertisement", encoding="utf-8")
    output.chmod(0o600)
    original_replace = Path.replace
    replaced = []

    def replace(source, destination):
        # The new XML must already be readable when Avahi observes the rename.
        assert source.stat().st_mode & 0o777 == 0o644
        assert output.read_text(encoding="utf-8") == "old advertisement"
        replaced.append(source)
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", replace)
    old_umask = os.umask(0o077)
    try:
        module.publish_service(output, 8443, role=role, tls_host="fleet-a.local")
    finally:
        os.umask(old_umask)
    assert replaced
    assert output.stat().st_mode & 0o777 == 0o644
    assert ElementTree.fromstring(output.read_text(encoding="utf-8")).findtext("service/port") == "8443"
    assert list(tmp_path.iterdir()) == [output]


def test_overhead_advertisement_exposes_tls_ingest_without_credentials():
    root = ElementTree.fromstring(_module().render_service(
        8443, role="overhead", tls_host="camera-site.local"
    ))
    service = root.find("service")
    assert service.findtext("type") == "_rosy-overhead._tcp"
    assert service.findtext("port") == "8443"
    assert {item.text for item in service.findall("txt-record")} == {
        "product=rosy", "role=overhead-camera", "proto=rosy-overhead/1",
        "tls=required", "tls_host=camera-site.local",
    }
    assert "token" not in ElementTree.tostring(root, encoding="unicode").lower()


def _txt(xml):
    return {item.text for item in ElementTree.fromstring(xml).find("service").findall("txt-record")}


def test_overhead_pair_key_only_when_asked_and_never_by_default():
    module = _module()
    default = _txt(module.render_service(8443, role="overhead", tls_host="camera-site.local"))
    paired = _txt(module.render_service(8443, role="overhead", tls_host="camera-site.local",
                                        pair=True))
    assert not any(item.startswith("pair=") for item in default)
    assert paired - default == {"pair=rosy-pair/1"}
    with pytest.raises(ValueError):
        module.render_service(8443, role="fleet", pair=True)


@pytest.mark.parametrize("flag,expected", [
    ([], False), (["--pair"], True), (["--pair=1"], True), (["--pair="], False),
    (["--pair=0"], False),
])
def test_publish_pair_flag_is_explicit_and_systemd_env_friendly(tmp_path, flag, expected):
    module = _module()
    out = tmp_path / "rosy-overhead.service"
    import sys
    argv = ["fleet-mdns.py", "publish", "--role", "overhead", "--port", "8443",
            "--tls-host", "camera-site.local", "--output", str(out), *flag]
    old, sys.argv = sys.argv, argv
    try:
        assert module.main() == 0
    finally:
        sys.argv = old
    assert ("pair=rosy-pair/1" in _txt(out.read_text(encoding="utf-8"))) is expected


def test_publish_pair_rejects_unknown_value_and_non_overhead_role(tmp_path):
    module = _module()
    import sys
    base = ["fleet-mdns.py", "publish", "--port", "8443", "--output", str(tmp_path / "x")]
    for extra in (["--role", "overhead", "--tls-host", "a.local", "--pair=yes"],
                  ["--role", "fleet", "--pair"]):
        old, sys.argv = sys.argv, base + extra
        try:
            with pytest.raises(SystemExit):
                module.main()
        finally:
            sys.argv = old


def test_parser_accepts_site_fleet_and_deduplicates_interfaces():
    rows = "\n".join((_row(), _row(),
                      _row(host="fleet-b.local", address="192.168.1.21"),
                      _row(txt='"role=fleet" "tls=required"'),
                      _row(host="evil.example"),
                      _row(address="127.0.0.1"),
                      _row(address="169.254.2.3"),
                      _row(port=0),
                      _row(txt='"product=rosy" "role=fleet" "role=fleet" '
                               '"proto=site-v1" "tls=required"'),
                      _row().replace("_rosy-fleet._tcp", "_http._tcp"),
                      "+;eth0;IPv4;unresolved;_rosy-fleet._tcp;local"))
    assert _module().parse_avahi(rows) == [
        {"hostname": "fleet-a.local", "address": "192.168.1.20", "port": 8443},
        {"hostname": "fleet-b.local", "address": "192.168.1.21", "port": 8443},
    ]
    assert _robot_module().parse_avahi(rows) == _module().parse_avahi(rows)


def test_selection_requires_explicit_hostname_and_rejects_ambiguity():
    candidates = _module().parse_avahi(
        _row() + "\n" + _row(address="192.168.1.22"))
    with pytest.raises(ValueError, match="expected hostname"):
        _module().select_candidate(candidates, "")
    with pytest.raises(ValueError, match="not found"):
        _module().select_candidate(candidates, "unknown.local")
    with pytest.raises(ValueError, match="ambiguous"):
        _module().select_candidate(candidates, "fleet-a.local")
    with pytest.raises(ValueError, match="local hostname"):
        _module().select_candidate(candidates, "fleet-a.example")


def test_verification_uses_pinned_hostname_and_ca_before_returning_endpoint(monkeypatch, tmp_path):
    module = _module()
    candidate = module.select_candidate(module.parse_avahi(_row()), "fleet-a.local")
    calls = []

    def probe(address, port, hostname, ca_file):
        calls.append((address, port, hostname, ca_file))

    monkeypatch.setattr(module, "probe_health", probe)
    ca_file = tmp_path / "site-ca.crt"
    ca_file.write_text("test CA fixture", encoding="utf-8")
    assert module.verify_endpoint(candidate, "fleet-a.local", ca_file) == \
        "https://fleet-a.local:8443"
    assert calls == [("192.168.1.20", 8443, "fleet-a.local", ca_file)]


# D-370 S7 prerequisite: /healthz may grow {"status","role","proto","contract_version"};
# both probes accept the old body and the extended shape, and nothing looser.
HEALTH_ACCEPTED = (
    b'{"status":"ok"}',
    b'{"status":"ok","role":"fleet","proto":"site-v1","contract_version":"1"}',
    b'{"status":"ok","future_field":[1,2]}',
)
HEALTH_REJECTED = (
    b'{"status":"ok","role":"overhead-camera"}',
    b'{"status":"ok","role":null}',
    b'{"status":"degraded","role":"fleet"}',
    b'{"status":"down"}',
    b'{"role":"fleet"}',
    b'["status","ok"]',
    b'"ok"',
    b'not json',
    b'{"status":"ok","pad":"' + b"x" * 1024 + b'"}',
)


@pytest.mark.parametrize("loader", (_module, _robot_module), ids=("site", "agent"))
def test_health_probes_accept_old_and_extended_ok_bodies(loader):
    module = loader()
    for body in HEALTH_ACCEPTED:
        module.check_health_body(body)


@pytest.mark.parametrize("loader", (_module, _robot_module), ids=("site", "agent"))
@pytest.mark.parametrize("body", HEALTH_REJECTED, ids=(
    "wrong_role", "null_role", "degraded", "down", "no_status", "array", "string",
    "not_json", "oversize"))
def test_health_probes_reject_wrong_role_status_shape_or_size(loader, body):
    with pytest.raises(ValueError, match="unexpected Fleet health response"):
        loader().check_health_body(body)


# D-370 5.1: the site script copy and FleetAgent are held to the shared TXT vectors.
import json  # noqa: E402

VECTORS = json.loads((Path(__file__).resolve().parent / "fixtures/protocol/discovery-txt.v1.json")
                     .read_text(encoding="utf-8"))


def avahi_line(case: dict) -> str:
    family = "IPv6" if ":" in (case["address"] or "") else "IPv4"
    txt = " ".join(f'"{item}"' for item in case["txt"])
    return (f'=;eth0;{family};ROSY {case["id"]};{case["service_type"]};local;'
            f'{case["host"]};{case["address"]};{case["port"]};{txt}')


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["id"])
def test_site_locator_and_agent_accept_exactly_the_fleet_vectors(case):
    accepted = case["expect"]["accepted"] and case["service_type"] == "_rosy-fleet._tcp"
    line = avahi_line(case)
    assert bool(_module().parse_avahi(line)) is accepted
    assert bool(_robot_module().parse_avahi(line)) is accepted


FLEET_CASES = [case for case in VECTORS["cases"] if case["service_type"] == "_rosy-fleet._tcp"]


@pytest.mark.parametrize("case", FLEET_CASES, ids=lambda case: case["id"])
def test_site_locator_classifier_copy_gives_the_vector_reason(case):
    """The vendored copy must reject for the same reason as core_common, not just reject."""
    result = _module().classify_fleet(case["host"], case["address"], case["port"],
                                      [tuple(item.split("=", 1)) for item in case["txt"]])
    assert result == (None if case["expect"]["accepted"] else case["expect"]["reason"])


_BASE_TXT = [("product", "rosy"), ("role", "fleet"), ("proto", "fleet-v1"), ("tls", "required")]
_EXTRA_INPUTS = [
    ("site.local", "0.0.0.0", 8443, _BASE_TXT),
    ("site.local", "224.0.0.251", 8443, _BASE_TXT),
    ("site.local", "8.8.8.8", 8443, _BASE_TXT),
    ("bad host!", "192.168.1.10", 8443, _BASE_TXT),
    ("site.local", "192.168.1.10", 0, _BASE_TXT),
    ("site.local", "192.168.1.10", 8443, _BASE_TXT + [("role", "robot")]),
    ("site.local", "192.168.1.10", 8443, [("product", "rosy")]),
    ("site.local", None, 8443, _BASE_TXT),
]


@pytest.mark.parametrize("inputs", [(c["host"], c["address"], c["port"],
                                     [tuple(i.split("=", 1)) for i in c["txt"]])
                                    for c in FLEET_CASES] + _EXTRA_INPUTS)
def test_site_locator_copy_agrees_with_core_common_outside_the_vectors_too(inputs):
    """Drift guard: the vendored copy must give core_common's verdict, not only the fixture's."""
    from core_common.protocol.discovery_txt import classify
    host, address, port, txt = inputs
    real = classify("_rosy-fleet._tcp", host, address, port, txt)
    expected = getattr(real, "reason", None)
    assert _module().classify_fleet(host, address, port, txt) == expected
