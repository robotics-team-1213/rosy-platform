"""D-432: explicit secure robots and site-device roles use the same classifier."""
import pytest
from core_common.protocol.discovery_txt import Accepted, Rejected, classify


@pytest.mark.parametrize('kind,role,proto,tls', [
    ('_rosy._tcp', 'robot', 'core-v1', 'required'),
    ('_rosy-dock._tcp', 'dock', 'rosy-dock/1', 'none'),
    ('_rosy-signal._tcp', 'signal', 'rosy-signal/1', 'none'),
])
def test_shared_role_contract(kind, role, proto, tls):
    txt = [('product', 'rosy'), ('role', role), ('proto', proto), ('tls', tls)]
    assert isinstance(classify(kind, 'device-a.local', '192.168.1.10', 8080, txt), Accepted)
    assert isinstance(classify(kind, 'device-a.local', '192.168.1.10', 8080,
                               [(k, 'other' if k == 'role' else v) for k, v in txt]), Rejected)
