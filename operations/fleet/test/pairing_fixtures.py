"""Shared D-341 pairing test material: public fixture certificates and a phone-side helper.

Certificates come from the public site-link vector; no private key exists in the tree.
Phone secrets are generated per test run so no credential literal lands in the source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from core_common.protocol import pairing

FIXTURES = Path(__file__).resolve().parents[3] / "test/fixtures/protocol"
_SITE_LINK = {case["id"]: case for case in json.loads(
    (FIXTURES / "site-link.v1.json").read_text(encoding="utf-8"))["cases"]}
SITE_CA_PEM = _SITE_LINK["overhead_camera_with_credential_ref"]["record"]["ca_pem"]
LEAF_PEM = _SITE_LINK["ca_pem_is_leaf"]["record"]["ca_pem"]
LEAF_SHA256 = pairing.der_sha256(LEAF_PEM)
TLS_HOST = "fixture-site.local"


def conformant_site_tls():
    """Runtime-generated RFC 5280-conformant site CA + server leaf.

    The public site-link vector certs carry only BasicConstraints; the strict
    chain verifier (cryptography>=42 ``PolicyBuilder``) requires SKI/AKI/EKU,
    so a test that actually verifies the chain generates its own pair instead
    of weakening the verifier. No key or literal lands in the tree.
    """
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Rosy test site CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=365))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=False, key_encipherment=False,
                                       content_commitment=False, data_encipherment=False,
                                       key_agreement=False, key_cert_sign=True, crl_sign=True,
                                       encipher_only=False, decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, TLS_HOST)]))
            .issuer_name(ca.subject).public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=90))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False,
                                         content_commitment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(TLS_HOST)]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    pem = lambda cert: cert.public_bytes(serialization.Encoding.PEM).decode("ascii")  # noqa: E731
    return pem(ca), pem(leaf)


class FakeClock:
    """Monotonic and wall clocks that move only when a test says so."""

    def __init__(self, start: float = 1_000.0, wall: float = 1_790_000_000.0) -> None:
        self.now = start
        self.wall_offset = wall - start

    def monotonic(self) -> float:
        return self.now

    def wall(self) -> float:
        return self.now + self.wall_offset

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Phone:
    """What a Rosy Cam phone keeps during one pairing attempt."""

    label: str = "Galaxy S21 ceiling"
    client_nonce: str = field(default_factory=pairing.new_secret)
    poll: str = field(default_factory=pairing.new_secret)

    def request_body(self, **changes) -> dict:
        body = {"proto": pairing.PROTO, "role": pairing.ROLE, "device_label": self.label,
                "app_version": "0.4.0", "client_commit": pairing.commit(self.client_nonce),
                "poll_secret_sha256": pairing.sha256_text(self.poll)}
        body.update(changes)
        return body

    def request_bytes(self, **changes) -> bytes:
        return json.dumps(self.request_body(**changes)).encode("utf-8")

    def reveal_bytes(self) -> bytes:
        return json.dumps({"client_nonce": self.client_nonce}).encode("utf-8")

    def code(self, request_id: str, server_nonce: str, leaf_sha256: str = LEAF_SHA256) -> str:
        return pairing.confirmation_code(role=pairing.ROLE, request_id=request_id,
                                         leaf_cert_sha256=leaf_sha256,
                                         client_nonce=self.client_nonce, server_nonce=server_nonce)

    @property
    def bearer(self) -> str:
        return "Bearer " + self.poll
