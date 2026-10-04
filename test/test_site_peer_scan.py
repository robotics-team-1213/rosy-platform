"""The host scanner provides bounded six-role hints, never credentials."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from core_common.protocol.discovery_txt import Accepted, REQUIRED, classify

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('site_peer_scan', ROOT / 'deploy/site/mdns-bridge.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def row(kind, txt, host='site.local', address='192.168.1.20', port=8443):
    fields = ' '.join(json.dumps(f'{key}={value}') for key, value in txt)
    return f'=;eth0;IPv4;ROSY service;{kind};local;{host};{address};{port};{fields}'


def test_copied_profiles_equal_canonical_classifier():
    assert module().SERVICE_TXT == REQUIRED


def test_all_six_roles_have_actual_transport_and_never_endpoint_secrets():
    scanner = module()
    lines = []
    for kind, required in REQUIRED.items():
        txt = {**required, 'name': required['role'], 'network': 'sta'}
        if kind == '_rosy-overhead._tcp':
            txt['tls_host'] = 'site.local'
        lines.append(row(kind, txt.items()))
    services = scanner.parse_services('\n'.join(lines))
    assert {service['role'] for service in services} == {entry['role'] for entry in REQUIRED.values()}
    assert next(service for service in services if service['role'] == 'model-host')['transport'] == 'ssh'
    assert all(set(service) == {'name', 'role', 'transport', 'service_type', 'hostname', 'address', 'port'}
               for service in services)


def test_scanner_matches_resolved_nonlegacy_classifier_vectors():
    vectors = json.loads((ROOT / 'test/fixtures/protocol/discovery-txt.v1.json').read_text(encoding='utf-8'))
    scanner = module()
    for case in vectors['cases']:
        if case['host'] is None or case['address'] is None:
            continue
        txt = [tuple(pair.split('=', 1)) if isinstance(pair, str) else tuple(pair) for pair in case['txt']]
        decision = classify(case['service_type'], case['host'], case['address'], case['port'], txt)
        observed = scanner.parse_services(row(case['service_type'], txt, case['host'], case['address'], case['port']))
        # TXT classification is shared; catalogue observations additionally require RFC1918.
        import ipaddress
        address = ipaddress.ip_address(case['address'])
        lan = address.version == 4 and any(address in ipaddress.ip_network(net) for net in
                ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
        assert bool(observed) == (isinstance(decision, Accepted) and not decision.legacy and lan), case['id']


def test_conflicting_names_are_not_silently_collapsed():
    txt = REQUIRED['_rosy-fleet._tcp'].items()
    services = module().parse_services(row('_rosy-fleet._tcp', txt) + '\n' +
                                       row('_rosy-fleet._tcp', txt, address='192.168.1.21'))
    assert len(services) == 2


@pytest.mark.parametrize('address', ['100.82.51.8', '127.0.0.1', '169.254.1.2', '224.0.0.251'])
def test_mdns_hints_do_not_invent_cross_network_discovery(address):
    assert module().parse_services(row('_rosy-fleet._tcp', REQUIRED['_rosy-fleet._tcp'].items(), address=address)) == []


@pytest.mark.skipif(os.name != 'posix', reason='deployed host scanner uses POSIX selectable child pipes')
@pytest.mark.parametrize('program, exception', [
    ("import time; time.sleep(10)", subprocess.TimeoutExpired),
    ("import sys; sys.stdout.buffer.write(b'x' * (1024 * 1024 + 1)); sys.stdout.flush()", ValueError),
    ("import sys; sys.exit(7)", subprocess.CalledProcessError),
])
def test_scan_bounds_output_and_time_and_reaps_only_its_child(monkeypatch, program, exception):
    scanner = module()
    popen = subprocess.Popen
    children = []

    def owned_child(args, **kwargs):
        assert args == ['avahi-browse', '-a', '-r', '-t', '-p', '-k']
        child = popen([sys.executable, '-c', program], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(scanner.subprocess, 'Popen', owned_child)
    with pytest.raises(exception):
        scanner.scan_output(timeout_s=.25)
    assert len(children) == 1 and children[0].poll() is not None
    assert children[0].stdout.closed
