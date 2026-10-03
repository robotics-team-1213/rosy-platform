"""D-432 shared discovery still verifies Fleet TLS before returning an endpoint."""

import pytest

from core_common.discover import DiscoveredDevice
from core_features.fleet_agent.discovery import locate_fleet


class Cache:
    def __init__(self, rows):
        self.rows = rows

    def wait(self, service_type, *, timeout_s):
        assert service_type == '_rosy-fleet._tcp'
        assert timeout_s == 3
        return self.rows


def candidate(host='fleet-a.local', tls='required'):
    return DiscoveredDevice('Fleet A', '_rosy-fleet._tcp', host, 9443, ('192.168.1.20',),
                            (('product', 'rosy'), ('role', 'fleet'), ('proto', 'site-v1'), ('tls', tls)))


def test_live_cache_never_returns_url_before_pinned_probe(tmp_path):
    ca = tmp_path / 'ca.crt'
    ca.write_text('fixture')
    probed = []
    url = locate_fleet('fleet-a.local', ca, cache=Cache([candidate()]),
                       probe=lambda *args: probed.append(args))
    assert url == 'https://fleet-a.local:9443'
    assert probed == [({'hostname': 'fleet-a.local', 'address': '192.168.1.20', 'port': 9443},
                       'fleet-a.local', ca)]


def test_untrusted_tls_failure_or_wrong_advertisement_is_not_a_site(tmp_path):
    ca = tmp_path / 'ca.crt'
    ca.write_text('fixture')

    def no_probe(*args):
        pytest.fail('incompatible advertisement must not reach TLS probe')

    with pytest.raises(ValueError, match='not found'):
        locate_fleet('fleet-a.local', ca, cache=Cache([candidate(tls='none')]), probe=no_probe)

    def reject(*args):
        raise ValueError('TLS identity mismatch')

    with pytest.raises(ValueError, match='TLS identity mismatch'):
        locate_fleet('fleet-a.local', ca, cache=Cache([candidate()]), probe=reject)
