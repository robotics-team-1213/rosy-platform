"""The site locator treats mDNS as a hint, never as a trust decision."""

import importlib.util
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


# D-358 5.1: the site script copy and FleetAgent are held to the shared TXT vectors.
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
