from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from fleet.server.camera_peer_routes import BASE, configured_issuers, install_camera_peer_routes
from fleet.server.camera_peer_tls import configured_site_anchor
from fleet.server.site_auth import build_authorize, build_role_guards, parse_site_principals
from test_camera_peer_service import receiver, request, sign


def certificates():
    now = datetime.now(timezone.utc)
    ca_key, key = [ec.generate_private_key(ec.SECP256R1()) for _ in range(2)]
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Test site CA')])
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'site.local')])
    common = lambda: x509.CertificateBuilder().serial_number(x509.random_serial_number()).not_valid_before(
        now - timedelta(days=1)).not_valid_after(now + timedelta(days=2))
    ca = (common().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .add_extension(x509.BasicConstraints(ca=True,path_length=0), critical=True)
          .add_extension(x509.KeyUsage(True,False,False,False,False,True,True,False,False),critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),critical=False)
          .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False)
          .sign(ca_key,hashes.SHA256()))
    leaf = (common().subject_name(leaf_name).issuer_name(ca_name).public_key(key.public_key())
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('site.local')]),critical=False)
            .add_extension(x509.KeyUsage(True,False,False,False,False,False,False,False,False),critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False)
            .sign(ca_key,hashes.SHA256()))
    pem = lambda cert: cert.public_bytes(serialization.Encoding.PEM).decode('ascii')
    return pem(ca), pem(leaf) + pem(ca)


@pytest.fixture
def client(receiver):
    service, _ = receiver
    users = {sha256(b'owner-secret').hexdigest(): {'principal_id':'owner','role':'operator'},
             sha256(b'viewer-secret').hexdigest(): {'principal_id':'viewer','role':'viewer'}}
    service.store.current_issuers = lambda: configured_issuers(users)
    ca, chain = certificates()
    service.tls_anchor = configured_site_anchor(ca, chain, 'site.local')
    console = SimpleNamespace()
    setattr(console, 'user_credential_overlaps_robot_secret', lambda _:False)
    principals = parse_site_principals(users, console)
    authorize = build_authorize(None, principals, None)
    _, _, named_operator, _ = build_role_guards(authorize, principals)
    app = FastAPI()
    install_camera_peer_routes(app, service, require_named_operator=named_operator, current_users=lambda:users)
    return TestClient(app,base_url='https://site.local:8443'), service, users


def test_actual_named_owner_approval_and_camera_proof_routes(client):
    http, service, _ = client
    key = ec.generate_private_key(ec.SECP256R1())
    created = request(service,key)
    path = BASE + '/requests/' + created['request_id'] + '/decision'
    decision = {'action':'approve','revision':0,'source_id':'ceiling_north','persist_requested':True}
    assert http.post(path, json=decision,headers={'Authorization':'Bearer viewer-secret'}).status_code == 403
    assert http.post(path, json=decision).status_code == 401
    accepted = http.post(path,json=decision,headers={'Authorization':'Bearer owner-secret'})
    assert accepted.status_code == 200
    assert accepted.json()['authorization_available']
    challenge = http.post(BASE+'/challenge',json={'relationship_id':created['request_id'],'generation':0})
    fields = challenge.json()['fields']
    result = http.post(BASE+'/session',json={'fields':fields,'signature':sign(key,'session-request',fields)})
    assert result.status_code == 200
    assert result.headers['cache-control'] == 'no-store'
    assert result.json()['role'] == 'overhead-camera'
    # Credential is not a site operator and cannot approve another camera.
    assert http.post(path,json=decision,headers={'Authorization':'Bearer '+result.json()['token']}).status_code == 401


def test_http_origin_and_oversized_body_are_refused(client):
    http, service, _ = client
    plain = TestClient(http.app,base_url='http://site.local:8443')
    assert plain.get(BASE+'/identity').status_code == 403
    assert http.post(BASE+'/requests',content=b'x'*4097).status_code == 413
    assert service.requests == {}


def test_extra_expiry_does_not_become_persistent_owner(client):
    http, service, users = client
    created = request(service,ec.generate_private_key(ec.SECP256R1()))
    users[sha256(b'owner-secret').hexdigest()]['expires_at'] = 2000
    response = http.post(BASE+'/requests/'+created['request_id']+'/decision',
                         json={'action':'approve','revision':0,'source_id':'ceiling_north','persist_requested':True},
                         headers={'Authorization':'Bearer owner-secret'})
    assert response.status_code == 403
    assert service.sync_rows() == []


def test_ca_binding_uses_configured_site_name_not_advertised_robot_name():
    ca, chain = certificates()
    assert configured_site_anchor(ca,chain,'site.local')['tls_hostname'] == 'site.local'
    with pytest.raises(ValueError):
        configured_site_anchor(ca,chain,'other.local')
    other_ca, _ = certificates()
    with pytest.raises(ValueError):
        configured_site_anchor(other_ca,chain,'site.local')


def test_request_secret_requires_exact_bearer_header(client):
    http, service, _ = client
    created = request(service,ec.generate_private_key(ec.SECP256R1()))
    path = BASE+'/requests/'+created['request_id']
    request_secret = created['request_secret']
    for malformed in [request_secret, 'Basic '+request_secret, 'Bearer '+request_secret+'x']:
        assert http.get(path,headers={'Authorization':malformed}).status_code == 401
        assert http.post(path+'/cancel',headers={'Authorization':malformed}).status_code == 401
    assert http.get(path,headers={'Authorization':'Bearer '+request_secret}).status_code == 200
    limited = http.get(path,headers={'Authorization':'Bearer '+request_secret})
    assert limited.status_code == 429 and limited.headers['retry-after'] == '2'
    assert http.post(path+'/cancel',headers={'Authorization':'Bearer '+request_secret}).json()['state'] == 'cancelled'
