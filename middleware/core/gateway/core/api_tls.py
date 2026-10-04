"""D-432 optional CORE TLS, validated before the API listener starts."""

from pathlib import Path
import ssl
import os

from core_common.protocol.link_policy import LinkPolicy


def server_tls_options(config: dict) -> dict:
    network = config.get('network', {})
    if not isinstance(network, dict):
        raise ValueError('network must be a mapping')
    mode = network.get('connection_mode', 'paired')
    if mode not in ('paired', 'development'):
        raise ValueError('connection mode must be paired or development')
    tls = network.get('tls')
    if mode == 'development':
        path = network.get('link_policy_file')
        if path is None:
            if os.environ.get('ROSY_DEPLOYMENT', '').strip() != 'development':
                raise ValueError('development connection requires an explicit development deployment')
        else:
            if not isinstance(path, str) or not Path(path).is_absolute() or tls is None:
                raise ValueError('scoped development connection requires explicit policy and TLS')
            policy = LinkPolicy.from_file(path, deployment=os.environ.get('ROSY_DEPLOYMENT', 'development'))
            identity = config.get('robot', {})
            if not policy.permits(identity.get('id'), '_rosy._tcp', str(identity.get('name', '')) + '.local',
                                  authenticated=True):
                raise ValueError('development connection policy does not bind this robot')
    if tls is None:
        return {}
    if not isinstance(tls, dict) or set(tls) not in ({'cert_file', 'key_file'}, {'cert_file', 'key_file', 'ca_file'}):
        raise ValueError('TLS requires cert_file and key_file together')
    for value in tls.values():
        if not isinstance(value, str) or not value or not Path(value).is_absolute() or not Path(value).is_file():
            raise ValueError('TLS certificate and key must be readable absolute paths')
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(tls['cert_file'], tls['key_file'])
    except (OSError, ssl.SSLError) as exc:
        raise ValueError('TLS certificate/key validation failed') from exc
    if 'ca_file' in tls:
        from core_api_web.api.peer_pairing.tls_anchor import configured_tls_anchor
        configured_tls_anchor(config)
    return {'ssl_certfile': tls['cert_file'], 'ssl_keyfile': tls['key_file']}
