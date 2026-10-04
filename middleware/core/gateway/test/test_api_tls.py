"""D-432: opt-in CORE TLS fails closed before opening a listener."""

import pytest

from core.api_tls import server_tls_options


def test_legacy_listener_has_no_tls_options():
    assert server_tls_options({}) == {}


def test_explicit_lan_development_listener_needs_no_client_setup(monkeypatch):
    monkeypatch.setenv('ROSY_DEPLOYMENT', 'development')
    assert server_tls_options({'network': {'connection_mode': 'development'}}) == {}


@pytest.mark.parametrize('network', [{'connection_mode': 'auto'}, {'connection_mode': 'development'},
                                     {'connection_mode': 'development', 'tls': {}}])
def test_development_requires_explicit_policy_and_authenticated_listener(network):
    with pytest.raises(ValueError):
        server_tls_options({'network': network})


@pytest.mark.parametrize('tls', [
    True, {'cert_file': 'missing'}, {'key_file': 'missing'},
    {'cert_file': 'missing', 'key_file': 'missing'}, {'cert_file': '', 'key_file': ''},
])
def test_incomplete_or_unreadable_tls_does_not_fall_back_to_http(tls):
    with pytest.raises(ValueError, match='TLS'):
        server_tls_options({'network': {'tls': tls}})


def test_invalid_certificate_and_key_are_rejected(tmp_path):
    cert, key = tmp_path / 'chain.pem', tmp_path / 'key.pem'
    cert.write_text('not a certificate')
    key.write_text('not a key')
    with pytest.raises(ValueError, match='TLS'):
        server_tls_options({'network': {'tls': {'cert_file': str(cert), 'key_file': str(key)}}})
