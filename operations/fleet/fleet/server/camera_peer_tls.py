"""Validate the locally configured Fleet TLS leaf against its explicit site CA."""
from datetime import datetime, timezone
import re
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError


def configured_site_anchor(ca_pem, served_pem, hostname):
    if (not isinstance(ca_pem, str) or not 1 <= len(ca_pem.encode()) <= 8192
            or not isinstance(served_pem, str) or not 1 <= len(served_pem.encode()) <= 32768
            or not isinstance(hostname, str)
            or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local', hostname)):
        raise ValueError('configured camera receiver TLS material unavailable')
    try:
        roots = x509.load_pem_x509_certificates(ca_pem.encode('ascii'))
        chain = x509.load_pem_x509_certificates(served_pem.encode('ascii'))
        if len(roots) != 1 or not 1 <= len(chain) <= 5:
            raise ValueError('one site CA and bounded leaf chain required')
        root, now = roots[0], datetime.now(timezone.utc)
        constraints = root.extensions.get_extension_for_class(x509.BasicConstraints).value
        usage = root.extensions.get_extension_for_class(x509.KeyUsage).value
        if not constraints.ca or not usage.key_cert_sign or not root.not_valid_before_utc <= now <= root.not_valid_after_utc:
            raise ValueError('site CA authority or validity rejected')
        verified = (PolicyBuilder().store(Store(roots)).time(now).max_chain_depth(3)
                    .build_server_verifier(x509.DNSName(hostname)).verify(chain[0], chain[1:]))
        if verified[-1].fingerprint(hashes.SHA256()) != root.fingerprint(hashes.SHA256()):
            raise ValueError('site leaf belongs to a different trust anchor')
        return {'tls_hostname': hostname,
                'tls_ca_pem': root.public_bytes(serialization.Encoding.PEM).decode('ascii'),
                'tls_ca_sha256': root.fingerprint(hashes.SHA256()).hex()}
    except (ValueError, x509.ExtensionNotFound, VerificationError, UnicodeError) as exc:
        raise ValueError('site CA does not validate the configured receiver leaf') from exc
