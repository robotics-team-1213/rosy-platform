"""D-432: one screen code approves an SSH public key over discovered, verified TLS.

Requires the separately imported site CA. Does not weaken SSH host-key checks,
enable passwords, or issue a remote shell. Secrets never enter argv or stdout.
"""

import argparse
import asyncio
import getpass
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
for folder in ('src/contracts/foundation', 'src/site/fleet', 'deploy/robot/pinky_pro/release'):
    sys.path.insert(0, str(ROOT / folder))

import httpx  # noqa: E402 - standalone workspace entry point sets package paths first
from fleet.swarm.discovery_transport import DiscoveryTransport, resolve_robot  # noqa: E402
from fleet.swarm.robots import RobotEndpoint  # noqa: E402
from ssh_pairing import public_key, fingerprint  # noqa: E402


async def approve(endpoint, code, key, *, client=None):
    """One code exchange; release the temporary administrator credential afterward."""
    own_client = client is None
    client = client or httpx.AsyncClient(base_url=endpoint.base_url,
                                         transport=DiscoveryTransport(endpoint), trust_env=False,
                                         timeout=10, follow_redirects=False)
    token = None
    try:
        response = await client.post('/api/v1/auth/pair', json={'code': code, 'label': 'SSH key approval'})
        if response.status_code != 201:
            raise ValueError('screen code refused or expired')
        body = response.json()
        token = body.get('token') if isinstance(body.get('token'), str) else None
        if not isinstance(token, str) or not token or body.get('role') != 'administrator':
            raise ValueError('SSH key approval requires an administrator screen code')
        headers = {'Authorization': 'Bearer ' + token}
        info = await client.get('/api/v1/system/info', headers=headers)
        if info.status_code != 200 or info.json().get('robot_id') != endpoint.robot_id:
            raise ValueError('approved robot identity mismatch')
        response = await client.post('/api/v1/host/ssh/pair', headers=headers,
                                     json={'public_key': public_key(key), 'confirmed': True})
        body = response.json()
        if response.status_code != 200 or not body.get('available') or not body.get('ok'):
            raise ValueError('Host Agent refused SSH key registration')
        result = body.get('data') or {}
        if (result.get('account') != 'rosy' or result.get('port') != 22
                or result.get('public_key_fingerprint') != fingerprint(key)
                or result.get('host_key_fingerprint') != fingerprint(result.get('host_public_key'))):
            raise ValueError('SSH key registration readback mismatch')
        return result
    finally:
        if token:
            try:
                revoked = await client.post('/api/v1/auth/logout', headers={'Authorization': 'Bearer ' + token})
                if revoked.status_code != 204:
                    raise ValueError('temporary SSH approval session revocation unconfirmed')
            finally:
                if own_client:
                    await client.aclose()
        if own_client:
            await client.aclose()


def pin_host(path, hostname, key):
    """Refuse a changed existing binding; write only the verified public host key."""
    key = public_key(key)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding='ascii') if path.exists() else ''
    for line in existing.splitlines():
        parts = line.split()
        if parts and hostname in parts[0].split(','):
            if parts[1:3] != key.split():
                raise ValueError('SSH host key changed; operator verification required')
            return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'w', encoding='ascii') as stream:
        stream.write(('' if not existing or existing.endswith('\n') else '\n') + hostname + ' ' + key + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot-id', required=True)
    parser.add_argument('--host', required=True, help='trusted .local DNS hostname')
    parser.add_argument('--ca', required=True)
    parser.add_argument('--public-key', required=True, type=Path)
    parser.add_argument('--known-hosts', required=True, type=Path)
    parser.add_argument('--code-file', type=Path, help='private automation input; otherwise hidden terminal input')
    parser.add_argument('--connect', action='store_true')
    parser.add_argument('--private-key', type=Path)
    args = parser.parse_args(argv)
    if args.connect and not args.private_key:
        parser.error('--connect requires --private-key')
    endpoint = RobotEndpoint(args.robot_id, f'https://{args.host}:8080', 'bootstrap-not-sent',
                             tls_ca_file=args.ca, discovery=True)
    key = public_key(args.public_key.read_text(encoding='ascii').strip())
    code = (args.code_file.read_text(encoding='ascii').strip() if args.code_file else
            getpass.getpass('Robot screen administrator code: '))
    result = asyncio.run(approve(endpoint, code, key))
    pin_host(args.known_hosts, args.host, result['host_public_key'])
    print('SSH public key registered; verified host key pinned. Temporary approval session revoked.')
    if args.connect:
        address, _ = asyncio.run(resolve_robot(endpoint))
        return subprocess.call(['ssh', '-i', str(args.private_key), '-o', 'IdentitiesOnly=yes',
                                '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
                                '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlias=' + args.host,
                                '-o', 'UserKnownHostsFile=' + str(args.known_hosts), 'rosy@' + address])
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, httpx.HTTPError):
        print('SSH pairing failed; check trusted profile, screen code, and Host Agent.', file=sys.stderr)
        raise SystemExit(1)
