"""The host adapter accepts resolved ROSY services only."""

import importlib.util
from pathlib import Path


PATH = Path(__file__).resolve().parents[1] / "deploy/site/mdns-bridge.py"


def _module():
    spec = importlib.util.spec_from_file_location("rosy_site_mdns_bridge", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolved_avahi_rows_become_a_deduplicated_station_scan():
    output = "\n".join((
        '=;eth0;IPv4;ROSY rosy-a;_rosy._tcp;local;rosy-a.local;192.168.1.10;8080;'
        '"stage=CORE_READY" "release=018" "name=rosy-a" "network=sta"',
        '=;wlan0;IPv4;ROSY rosy-a;_rosy._tcp;local;rosy-a.local;192.168.1.10;8080;'
        '"stage=CORE_READY" "name=rosy-a" "network=sta"',
        '=;eth0;IPv4;ROSY rosy-b;_rosy._tcp;local;rosy-b.local;192.168.1.11;8080;'
        '"stage=BOOTING" "name=rosy-b" "network=sta"',
        '=;eth0;IPv4;ROSY ap;_rosy._tcp;local;ap.local;10.42.0.1;8080;'
        '"network=ap"',
        '+;eth0;IPv4;ROSY not resolved;_rosy._tcp;local',
    ))
    rows = _module().parse_avahi(output)
    assert len(rows) == 2
    assert rows[0] == {"name": "rosy-a", "hostname": "rosy-a.local",
                       "address": "192.168.1.10", "port": 8080,
                       "stage": "CORE_READY", "release": "018", "network": "sta"}


def test_non_rosy_and_non_local_records_are_ignored():
    output = ('=;eth0;IPv4;imposter;_http._tcp;local;x.local;192.168.1.3;80;'
              '"name=imposter"\n'
              '=;eth0;IPv4;far;_rosy._tcp;example.com;far.example.com;192.168.1.4;8080;'
              '"name=far"')
    assert _module().parse_avahi(output) == []
