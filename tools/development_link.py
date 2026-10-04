"""D-432 opt-in private development bundle; no code entry, IP pin or motor activation.

Run with --mode development --site <name> --robot rosy_01=robot-a.local
--output <private-directory>. Install generated files deliberately on each owner.
No credentials are printed and existing output is never overwritten.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / 'contracts/foundation', ROOT / 'operations/fleet'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import yaml  # noqa: E402 - standalone workspace entry point sets package paths first
from core_common.protocol.discovery_txt import HOSTNAME  # noqa: E402
from core_common.protocol.link_policy import LinkPolicy  # noqa: E402


def _write(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(text)


def _certificate(host, ca_key, ca_cert, start, end):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, host)]))
            .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(start).not_valid_after(end)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM).decode(),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()).decode())


def provision(output, *, site, robots, mode='development', lifetime_hours=24, runtime_root=None):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    output = Path(output).resolve()
    if output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / 'private'):
        raise ValueError('development credentials must stay outside source or under ignored private/')
    if mode != 'development':
        raise ValueError('bootstrap requires explicit development mode')
    if not isinstance(site, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,40}', site):
        raise ValueError('invalid named development site')
    if not isinstance(lifetime_hours, int) or isinstance(lifetime_hours, bool) or not 1 <= lifetime_hours <= 168:
        raise ValueError('development lifetime must be 1..168 hours')
    if not 1 <= len(robots) <= 60:
        raise ValueError('provide 1..60 distinct robot identities')
    site_host = f'{site}.local'
    bindings = [{'device_id': 'overhead-1', 'service_type': '_rosy-overhead._tcp', 'tls_host': site_host},
                {'device_id': site, 'service_type': '_rosy-fleet._tcp', 'tls_host': site_host}]
    for robot_id, host in robots:
        if not re.fullmatch(r'rosy_(?:0[1-9]|[1-9][0-9]*)', robot_id) or not HOSTNAME.fullmatch(host):
            raise ValueError('robot identity requires rosy_NN and a .local DNS hostname')
        if host == site_host:
            raise ValueError('robot and site must have different TLS hostnames')
        bindings.append({'device_id': robot_id, 'service_type': '_rosy._tcp', 'tls_host': host})
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=lifetime_hours)
    expiry = end.isoformat(timespec='seconds').replace('+00:00', 'Z')
    policy = {'mode': 'development', 'site_name': site, 'expires_at': expiry, 'devices': bindings}
    LinkPolicy.from_mapping(policy)
    if output.exists():
        raise ValueError('development output already exists; choose a new private directory')
    runtime = (PurePosixPath(runtime_root) if runtime_root and str(runtime_root).startswith('/')
               else Path(runtime_root) if runtime_root else output)
    if not runtime.is_absolute():
        raise ValueError('runtime root must be absolute')
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, f'Rosy development {site}')])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
          .not_valid_after(end).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
          .sign(key, hashes.SHA256()))
    ca_pem = ca.public_bytes(serialization.Encoding.PEM).decode()
    site_cert, site_key = _certificate(site_host, key, ca, now - timedelta(minutes=5), end)
    payloads = {'ca.pem': ca_pem, 'site-chain.pem': site_cert + ca_pem, 'site-key.pem': site_key,
                'link-policy.json': json.dumps(policy, indent=2) + '\n'}
    rows = []
    pilot_rows = []
    for robot_id, host in robots:
        token, pairing_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        cert, private_key = _certificate(host, key, ca, now - timedelta(minutes=5), end)
        prefix = runtime / robot_id
        config = {'robot': {'id': robot_id, 'number': int(robot_id.split('_')[1]), 'name': host[:-6]},
                  'runtime': {'mode': 'core'},
                  'network': {'api_port': 8080, 'connection_mode': 'development',
                              'link_policy_file': str(runtime / 'link-policy.json'),
                              'tls': {'cert_file': str(prefix / 'chain.pem'), 'key_file': str(prefix / 'key.pem')}},
                  'auth': {'tokens': [{'sha256': hashlib.sha256(token.encode()).hexdigest(),
                                       'role': 'operator', 'expires_at': expiry, 'source': 'manual',
                                       'label': f'development:{site}'}]},
                  'fleet': {'pairing_token': pairing_token,
                            'discovery': {'expected_hostname': site_host, 'ca_file': str(runtime / 'ca.pem')}}}
        payloads[f'{robot_id}/core.yaml'] = yaml.safe_dump(config, sort_keys=False)
        payloads[f'{robot_id}/runtime.env.fragment'] = (
            f'ROSY_CONFIG={prefix / "core.yaml"}\nROSY_API_TLS=required\nROSY_API_TLS_HOST={host}\n'
            f'ROSY_API_TLS_CA_FILE={runtime / "ca.pem"}\n')
        payloads[f'{robot_id}/chain.pem'], payloads[f'{robot_id}/key.pem'] = cert + ca_pem, private_key
        payloads[f'{robot_id}/avahi.service'] = (
            '<service-group><name>ROSY ' + host[:-6] + '</name><service><type>_rosy._tcp</type>'
            '<port>8080</port><txt-record>product=rosy</txt-record><txt-record>role=robot</txt-record>'
            '<txt-record>proto=core-v1</txt-record><txt-record>tls=required</txt-record>'
            '<txt-record>tls_host=' + host + '</txt-record>'
            '<txt-record>network=sta</txt-record><txt-record>name=' + host[:-6] + '</txt-record>'
            '</service></service-group>\n')
        rows.append({'robot_id': robot_id, 'base_url': f'https://{host}:8080', 'token': token,
                     'fleet_pairing_token': pairing_token, 'tls_ca_file': str(output / 'ca.pem'),
                     'discovery': True, 'link_policy_file': str(output / 'link-policy.json')})
        pilot_rows.append({'robot_id': robot_id, 'tls_host': host, 'port': 8080, 'credential': token})
    payloads['robots.yaml'] = yaml.safe_dump({'robots': rows}, sort_keys=False)
    payloads['pilot-development.json'] = json.dumps({'policy': policy, 'ca_pem': ca_pem,
                                                    'robots': pilot_rows}, indent=2) + '\n'
    cam_token = secrets.token_urlsafe(32)
    record = {'site_name': site, 'tls_host': site_host, 'port': 9443, 'ca_pem': ca_pem,
              'role': 'overhead-camera', 'credential_id': secrets.token_hex(12),
              'credential': cam_token, 'expires_at': expiry}
    payloads['cam-development.json'] = json.dumps({'policy': policy, 'site_link': record,
                                                  'source': 'overhead-1'}, indent=2) + '\n'
    payloads['vision-token.txt'] = cam_token + '\n'
    payloads['site-operator-token.txt'] = secrets.token_urlsafe(32) + '\n'
    payloads['site-users.yaml'] = yaml.safe_dump({'users': [
        {'principal_id': 'development-operator', 'role': 'operator',
         'token_sha256': hashlib.sha256(payloads['site-operator-token.txt'].strip().encode()).hexdigest()}]})
    # Only local private files carry the trust root; no CA signing key is retained.
    output.mkdir(mode=0o700, parents=True)
    for robot_id, _ in robots:
        (output / robot_id).mkdir(mode=0o700)
    for filename, text in payloads.items():
        _write(output / filename, text)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=['development'])
    parser.add_argument('--site', required=True)
    parser.add_argument('--robot', action='append', required=True, metavar='ROBOT_ID=HOST.local')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--runtime-root', help='absolute path on the target robot, e.g. /etc/rosy/development')
    parser.add_argument('--lifetime-hours', type=int, default=24)
    args = parser.parse_args(argv)
    try:
        robots = [tuple(value.split('=', 1)) for value in args.robot]
        if any(len(row) != 2 for row in robots):
            raise ValueError('each --robot must be ROBOT_ID=HOST.local')
        result = provision(args.output, site=args.site, robots=robots, mode=args.mode,
                           lifetime_hours=args.lifetime_hours, runtime_root=args.runtime_root)
    except (ValueError, OSError):
        parser.error('invalid development configuration or unwritable private output')
    print(f'Development configuration created at {result}; credentials are in private files only.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
