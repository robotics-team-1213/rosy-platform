"""Public bootstrap anchor from locally provisioned TLS material only."""
from datetime import datetime, timezone
from pathlib import Path
import re
import socket

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

try:
    from cryptography.x509.verification import PolicyBuilder, Store, VerificationError
except ImportError:  # cryptography < 42 (CI runners, current device image)
    PolicyBuilder = Store = VerificationError = None

#: Kept as a tuple so the except clause below stays valid either way.
_VERIFICATION_ERRORS = (VerificationError,) if VerificationError is not None else ()


def configured_tls_anchor(config):
    tls = config.get('network', {}).get('tls')
    if not isinstance(tls, dict) or 'ca_file' not in tls:
        return {}  # Existing public-trust TLS does not publish a private anchor.
    hostname = socket.gethostname().lower().removesuffix('.local') + '.local'
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local', hostname):
        raise ValueError('provisioned TLS hostname unavailable')
    def read(name, limit):
        path = Path(tls.get(name, ''))
        if not path.is_absolute() or path.is_symlink():
            raise ValueError('TLS public material requires a regular absolute path')
        with path.open('rb') as stream:
            value = stream.read(limit + 1)
        if not value or len(value) > limit:
            raise ValueError('TLS public material exceeds its bound')
        return value
    try:
        if PolicyBuilder is None:
            # Refuse before accessing certificate APIs absent on older libraries.
            raise ValueError('cryptography>=42 chain verification is required')
        roots = x509.load_pem_x509_certificates(read('ca_file', 8192))
        chain = x509.load_pem_x509_certificates(read('cert_file', 32768))
        if len(roots) != 1 or not 1 <= len(chain) <= 5:
            raise ValueError('bootstrap requires one explicit CA and a bounded chain')
        root, now = roots[0], datetime.now(timezone.utc)
        constraints = root.extensions.get_extension_for_class(x509.BasicConstraints).value
        usage = root.extensions.get_extension_for_class(x509.KeyUsage).value
        if not constraints.ca or not usage.key_cert_sign or not root.not_valid_before_utc <= now <= root.not_valid_after_utc:
            raise ValueError('bootstrap CA authority or validity failed')
        verified = (PolicyBuilder().store(Store(roots)).time(now).max_chain_depth(3)
                    .build_server_verifier(x509.DNSName(hostname)).verify(chain[0], chain[1:]))
        if verified[-1].fingerprint(hashes.SHA256()) != root.fingerprint(hashes.SHA256()):
            raise ValueError('TLS leaf is not bound to the configured CA')
        return {'tls_hostname': hostname, 'tls_ca_pem': root.public_bytes(serialization.Encoding.PEM).decode('ascii'),
                'tls_ca_sha256': root.fingerprint(hashes.SHA256()).hex()}
    except (OSError, ValueError, x509.ExtensionNotFound, *_VERIFICATION_ERRORS) as exc:
        raise ValueError('configured bootstrap CA does not validate the TLS leaf') from exc
