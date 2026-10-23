"""Renew only this site's Account TLS pair through the existing Docker authority.

    python3 account_tls_renew.py --certs <certificate folder> --domain <site tailnet name>

Runs daily from rosy-account-tls-renew.timer (deploy/site/README.md). The certificate folder is data
(keys, backups) and stays where it was prepared; this file is code installed from a release.
tailscale issues a new pair only when the current one has less than 30 days left (--min-validity).
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

PRODUCTION = Path('/etc/rosy/account-tls')

HELPER = r'''
import hashlib, json, os, subprocess, tempfile
from datetime import datetime, timezone
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import serialization
os.umask(0o077)
root = Path('/certs')
domain = os.environ['ROSY_TLS_DOMAIN']
names = ('account-frontend.crt', 'account-frontend.key')
for name in names:
    if (root / name).is_symlink():
        raise SystemExit('certificate source must not be a symlink')
with tempfile.TemporaryDirectory(prefix='.tls-renew-', dir=root) as tmp:
    tmp = Path(tmp)
    cert, key = (tmp / name for name in names)
    subprocess.run(['/usr/bin/tailscale', 'cert', '--min-validity=720h',
                    '--cert-file=' + str(cert), '--key-file=' + str(key), domain],
                   check=True, capture_output=True, timeout=120)
    certificate = x509.load_pem_x509_certificate(cert.read_bytes())
    private = serialization.load_pem_private_key(key.read_bytes(), password=None)
    fmt = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    assert certificate.public_key().public_bytes(*fmt) == private.public_key().public_bytes(*fmt)
    subprocess.run(['openssl', 'verify', '-CApath', '/etc/ssl/certs', '-untrusted', str(cert), str(cert)], check=True, capture_output=True)
    subprocess.run(['openssl', 'x509', '-in', str(cert), '-noout', '-checkhost', domain], check=True, capture_output=True)
    subprocess.run(['openssl', 'x509', '-in', str(cert), '-noout', '-checkend', '2592000'], check=True, capture_output=True)
    data = {name: (tmp / name).read_bytes() for name in names}
    targets = [root]
    installed = Path('/installed')
    if installed.is_dir():
        targets.append(installed)
    changed = [target for target in targets if any(not (target / name).is_file() or (target / name).read_bytes() != data[name] for name in names)]
    if installed in changed:
        pending = root / '.tls-reload-pending'
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    if changed:
        backups = root / 'backups'
        if backups.is_symlink():
            raise SystemExit('backup directory must not be a symlink')
        backups.mkdir(mode=0o700, exist_ok=True)
        backup = backups / ('renew-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
        backup.mkdir(mode=0o700)
        for index, target in enumerate(changed):
            staged = []
            try:
                for name in names:
                    dest = target / name
                    if dest.is_symlink():
                        raise SystemExit('installed certificate must not be a symlink')
                    if dest.is_file():
                        (backup / (str(index) + '-' + name)).write_bytes(dest.read_bytes())
                    fd, filename = tempfile.mkstemp(prefix='.' + name + '.', suffix='.new', dir=target)
                    leaf = Path(filename)
                    staged.append((leaf, dest))
                    with os.fdopen(fd, 'wb') as f:
                        f.write(data[name])
                        f.flush()
                        os.fsync(f.fileno())
                    leaf.chmod(0o400 if target == installed else 0o600)
                    if target == installed:
                        os.chown(leaf, 10001, 10001)
                for leaf, dest in staged:
                    leaf.replace(dest)
                fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            finally:
                for leaf, _ in staged:
                    leaf.unlink(missing_ok=True)
    print(json.dumps({'certificate_checked': True, 'pair_matches': True,
                      'changed': bool(changed), 'installed_updated': installed in changed,
                      'not_after': certificate.not_valid_after_utc.isoformat(),
                      'certificate_sha256': hashlib.sha256(data[names[0]]).hexdigest()}))
'''


def reload_vault_proxy():
    result = subprocess.run(['docker', 'inspect', 'rosy-vault-proxy-1'],
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        if 'No such object' in result.stderr or 'No such container' in result.stderr:
            return False
        raise RuntimeError('cannot inspect the Vault TLS consumer')
    labels = json.loads(result.stdout)[0]['Config'].get('Labels', {})
    if (labels.get('com.docker.compose.project') != 'rosy-vault'
            or labels.get('com.docker.compose.service') != 'proxy'):
        raise RuntimeError('unexpected Vault TLS consumer identity')
    compose = Path.home() / 'rosy-vault/current/deploy/compose.yaml'
    env = Path.home() / '.config/rosy/vault/compose.env'
    if not compose.is_file() or not env.is_file() or env.is_symlink():
        raise RuntimeError('Vault TLS consumer deployment files unavailable')
    # Recreate remounts atomically replaced TLS leaf files; restart alone can retain old inodes.
    subprocess.run(['docker', 'compose', '--env-file', str(env), '-p', 'rosy-vault',
                    '-f', str(compose), 'up', '-d', '--no-deps', '--force-recreate',
                    '--pull', 'never', '--no-build', 'proxy'],
                   check=True, capture_output=True, timeout=60)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--certs', type=Path, required=True)
    parser.add_argument('--domain', required=True)
    args_in = parser.parse_args()
    root, domain = args_in.certs, args_in.domain
    if not root.is_dir() or root.is_symlink() or not re.fullmatch(r'[a-z0-9-]+(\.[a-z0-9-]+)+', domain):
        raise SystemExit('an existing certificate folder and a plain DNS name are required')
    image = json.loads(subprocess.check_output(
        ['docker', 'inspect', 'rosy-site-fleet-1'], text=True))[0]['Image']
    args = ['docker', 'run', '--rm', '--pull=never', '--network', 'none',
            '--read-only', '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE',
            '--cap-add', 'CHOWN', '--security-opt', 'no-new-privileges', '--user', '0:0',
            '--env', f'ROSY_TLS_DOMAIN={domain}']
    for source, destination, readonly in [
        ('/usr/bin/tailscale', '/usr/bin/tailscale', True),
        ('/var/run/tailscale/tailscaled.sock', '/var/run/tailscale/tailscaled.sock', True),
        (str(root), '/certs', False),
    ]:
        args += ['--mount', f'type=bind,src={source},dst={destination}' + (',readonly' if readonly else '')]
    if PRODUCTION.exists():
        if PRODUCTION.is_symlink():
            raise RuntimeError('production certificate directory must not be a symlink')
        args += ['--mount', f'type=bind,src={PRODUCTION},dst=/installed']
    result = subprocess.run(args + ['--entrypoint', 'python3', image, '-c', HELPER],
                            capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError('certificate renewal failed: ' + result.stderr[-500:])
    receipt = json.loads(result.stdout)
    pending = root / '.tls-reload-pending'
    if pending.exists():
        failures = []
        try:
            subprocess.run(['docker', 'exec', '--user', '10001:10001', 'rosy-site-proxy-1',
                            'caddy', 'reload', '--force', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile'],
                           check=True, capture_output=True, timeout=30)
        except Exception:
            failures.append('Account')
        try:
            receipt['vault_proxy_recreated'] = reload_vault_proxy()
            if not receipt['vault_proxy_recreated']:
                raise RuntimeError('Vault TLS consumer unavailable')
        except Exception:
            failures.append('Vault')
        if failures:
            raise RuntimeError('TLS consumer reload pending: ' + ', '.join(failures))
        pending.unlink()
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
