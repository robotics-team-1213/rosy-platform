"""D-432: changing LAN location must retain the TLS name and credential boundary."""

import pytest

from fleet.swarm.robots import RobotEndpoint, RobotsFileError, load_robots, write_robots
from fleet.swarm.discovery_transport import select_robot
from core_common.discover import DiscoveredDevice


def endpoint(ca='ca.pem'):
    return RobotEndpoint('rosy_01', 'https://robot-a.local:8443', 'test-device-token',
                         tls_ca_file=ca, discovery=True)


def record(address='192.168.1.10', host='robot-a.local', port=8443, tls='required'):
    return DiscoveredDevice('Robot A', '_rosy._tcp', host, port,
                            addresses=(address,), txt=(('product', 'rosy'), ('role', 'robot'),
                                                       ('proto', 'core-v1'), ('tls', tls),
                                                       ('network', 'sta')))


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
