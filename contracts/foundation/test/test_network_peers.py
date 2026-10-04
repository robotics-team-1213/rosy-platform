"""D-452 metadata must never turn discovery into authenticated readiness."""
import pytest
from pydantic import ValidationError

from core_common.protocol.network_peers import PeerCatalogue, PeerObservation, PeerSummary


def observation(**changes):
    return dict(name='Model A', role='model-host', service_type='_rosy-model._tcp',
                transport='ssh', hostname='model-a.local', address='192.168.4.20',
                port=22, **changes)


def test_discovery_is_not_approval_or_readiness():
    row = PeerSummary(**observation(), provenance='mdns', freshness='fresh')
    assert row.peer_id is None
    assert row.approval == 'unapproved' and row.readiness == 'unknown'
    with pytest.raises(ValidationError):
        PeerSummary(**observation(), provenance='mdns', freshness='fresh', readiness='verified')


def test_listenerless_app_has_no_fake_network_endpoint():
    row = PeerSummary(name='Pilot', role='pilot', transport='session',
                      provenance='approved-directory', freshness='fresh',
                      approval='approved', peer_id='pilot-one')
    assert row.service_type is None and row.port is None
    with pytest.raises(ValidationError):
        PeerObservation(name='Pilot', role='pilot', transport='session', port=8080)


@pytest.mark.parametrize('change', [
    {'transport': 'https'}, {'role': 'robot'}, {'port': True},
    {'address': '127.0.0.1'}, {'hostname': 'untrusted.example'},
    {'name': 'bad\nname'}, {'token': 'must-not-leak'},
])
def test_wrong_role_transport_endpoint_and_secret_rejected(change):
    value = observation()
    value.update(change)
    with pytest.raises(ValidationError):
        PeerObservation(**value)


def test_catalogue_bounds_and_stale_verified_rejected():
    value = dict(**observation(), provenance='mdns', freshness='fresh')
    assert len(PeerCatalogue(peers=[value] * 64).peers) == 64
    with pytest.raises(ValidationError):
        PeerCatalogue(peers=[value] * 65)
    value.update(approval='approved', peer_id='model-a', readiness='verified', freshness='expired')
    with pytest.raises(ValidationError):
        PeerSummary(**value)


def test_approved_directory_dns_and_unresolved_identity_are_not_fake_mdns():
    value = observation()
    value.update(hostname='model.site.example', address=None, peer_id='approved-model',
                 approval='approved', provenance='approved-directory', freshness='unavailable')
    row = PeerSummary(**value)
    assert row.address is None and row.readiness == 'unknown'
    value.update(address='100.64.0.4', freshness='fresh')
    assert PeerSummary(**value).address == '100.64.0.4'
    value.update(provenance='mdns')
    with pytest.raises(ValidationError):
        PeerSummary(**value)


def test_directory_claim_without_approved_identity_is_rejected():
    with pytest.raises(ValidationError):
        PeerSummary(**observation(), provenance='approved-directory', freshness='fresh')


def test_legacy_approved_address_has_no_invented_dns_name():
    value = observation()
    value.update(hostname=None, address='100.64.0.4', peer_id='approved-model',
                 approval='approved', provenance='approved-directory', freshness='unavailable')
    assert PeerSummary(**value).hostname is None
    value.update(hostname='100.64.0.4')
    with pytest.raises(ValidationError):
        PeerSummary(**value)
