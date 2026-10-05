"""D-432: changing LAN location must retain the TLS name and credential boundary."""

import asyncio
import socket

import pytest

from fleet.swarm.robots import RobotEndpoint, RobotsFileError, load_robots, write_robots
from fleet.swarm.discovery_transport import resolve_robot, select_robot
from core_common.discover import DiscoveredDevice


def endpoint(ca='ca.pem'):
    return RobotEndpoint('rosy_01', 'https://robot-a.local:8443', 'test-device-token',
                         tls_ca_file=ca, discovery=True)


def record(address='192.168.1.10', host='robot-a.local', port=8443, tls='required', network='sta'):
    return DiscoveredDevice('Robot A', '_rosy._tcp', host, port,
                            addresses=(address,), txt=(('product', 'rosy'), ('role', 'robot'),
                                                       ('proto', 'core-v1'), ('tls', tls),
                                                       ('network', network)))


def test_secure_endpoint_round_trips(tmp_path):
    file = tmp_path / 'robots.yaml'
    write_robots(file, [endpoint(str(tmp_path / 'ca.pem'))])
    assert load_robots(file) == [endpoint(str(tmp_path / 'ca.pem'))]


@pytest.mark.parametrize('url,ca,discovery', [
    ('http://robot-a.local:8080', 'ca.pem', True),
    ('https://192.168.1.10:8443', 'ca.pem', True),
    ('https://robot-a.local:8443', None, True),
])
def test_discovery_cannot_enable_unverified_address_following(tmp_path, url, ca, discovery):
    import yaml
    file = tmp_path / 'robots.yaml'
    file.write_text(yaml.safe_dump({'robots': [{
        'robot_id': 'rosy_01', 'base_url': url, 'token': 'fixture',
        'tls_ca_file': ca, 'discovery': discovery,
    }]}))
    with pytest.raises(RobotsFileError):
        load_robots(file)


def test_dhcp_move_keeps_expected_name_and_reads_real_port():
    assert select_robot(endpoint(), [record()]) == ('192.168.1.10', 8443)
    assert select_robot(endpoint(), [record('192.168.1.20', port=9443)]) == ('192.168.1.20', 9443)


def test_ambiguous_name_and_plain_advertisement_cannot_select():
    with pytest.raises(ValueError, match='conflict'):
        select_robot(endpoint(), [record(), record('192.168.1.20')])
    with pytest.raises(ValueError, match='not_discovered'):
        select_robot(endpoint(), [record(tls='none')])
    with pytest.raises(ValueError, match='not_discovered'):
        select_robot(endpoint(), [record(host='other.local')])


def _patch_lookup(monkeypatch, answers):
    calls = []

    def lookup(host, port, *args, **kwargs):
        calls.append((host, port))
        if isinstance(answers, BaseException):
            raise answers
        return answers

    monkeypatch.setattr('fleet.swarm.discovery_transport.socket.getaddrinfo', lookup)
    return calls


def _addr(address):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 9))


def test_empty_discovery_uses_one_saved_host_address(monkeypatch):
    calls = _patch_lookup(monkeypatch, [_addr('192.168.1.50'), _addr('192.168.1.50')])
    assert asyncio.run(resolve_robot(endpoint(), lambda *a, **k: [])) == ('192.168.1.50', 8443)
    assert asyncio.run(resolve_robot(endpoint(), lambda *a, **k: [record(host='other.local')])) == (
        '192.168.1.50', 8443)
    assert calls == [('robot-a.local', 8443), ('robot-a.local', 8443)]


def test_unusable_or_split_host_address_stays_a_connection_failure(monkeypatch):
    for answers in ([], [_addr('8.8.8.8')], [_addr('127.0.0.1')], [_addr('169.254.1.1')],
                    [_addr('0.0.0.0')], socket.gaierror(8, 'fixture')):
        _patch_lookup(monkeypatch, answers)
        with pytest.raises(ValueError, match='not_discovered'):
            asyncio.run(resolve_robot(endpoint(), lambda *a, **k: []))
    _patch_lookup(monkeypatch, [_addr('192.168.1.10'), _addr('192.168.1.11')])
    with pytest.raises(ValueError, match='conflict: robot name is advertised at disjoint locations'):
        asyncio.run(resolve_robot(endpoint(), lambda *a, **k: []))


def test_advertised_name_does_not_fall_back_to_host_lookup(monkeypatch):
    def lookup(*args, **kwargs):
        raise AssertionError('host lookup')

    monkeypatch.setattr('fleet.swarm.discovery_transport.socket.getaddrinfo', lookup)
    assert asyncio.run(resolve_robot(endpoint(), lambda *a, **k: [record()])) == ('192.168.1.10', 8443)
    with pytest.raises(ValueError, match='not_discovered'):
        asyncio.run(resolve_robot(endpoint(), lambda *a, **k: [record(tls='none')]))
    with pytest.raises(ValueError, match='not_discovered'):
        asyncio.run(resolve_robot(endpoint(), lambda *a, **k: [record(network='ap')]))
    with pytest.raises(ValueError, match='conflict'):
        asyncio.run(resolve_robot(endpoint(), lambda *a, **k: [record(), record('192.168.1.20')]))
