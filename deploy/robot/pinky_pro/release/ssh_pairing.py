"""D-432: register an approved operator public key; SSH stays key-only."""

import base64
import hashlib
import os
from pathlib import Path
import stat
import struct


def public_key(value: str) -> str:
    if not isinstance(value, str) or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ValueError('invalid SSH public key')
    parts = value.strip().split()
    if len(parts) < 2 or parts[0] != 'ssh-ed25519':
        raise ValueError('only ssh-ed25519 public keys are accepted')
    try:
        raw = base64.b64decode(parts[1], validate=True)
    except (ValueError, TypeError):
        raise ValueError('invalid SSH public key encoding') from None
    if (len(raw) != 51 or raw[:4] != struct.pack('>I', 11) or raw[4:15] != b'ssh-ed25519'
            or raw[15:19] != struct.pack('>I', 32)):
        raise ValueError('invalid SSH public key packet')
    return 'ssh-ed25519 ' + parts[1]


def fingerprint(value: str) -> str:
    raw = base64.b64decode(public_key(value).split()[1], validate=True)
    return 'SHA256:' + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')


def register_operator_key(value: str, *, root=Path('/'), owner=None) -> dict:
    """Fixed account/path only. No caller-supplied paths, commands, or key options."""
    key = public_key(value)
    root = Path(root)
    host_file = root / 'etc/ssh/ssh_host_ed25519_key.pub'
    if host_file.is_symlink():
        raise ValueError('SSH host key file must not be a symlink')
    host_key = public_key(host_file.read_text(encoding='ascii').strip())
    home = root / 'home/rosy'
    directory = home / '.ssh'
    if home.is_symlink() or directory.is_symlink() or not home.is_dir():
        raise ValueError('operator SSH directory is unavailable or unsafe')
    if owner is None:
        import pwd
        account = pwd.getpwnam('rosy')
        owner = (account.pw_uid, account.pw_gid)
    directory.mkdir(mode=0o700, exist_ok=True)
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    # Hold the directory descriptor on Linux; a renamed parent cannot redirect writes.
    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | nofollow) if os.name == 'posix' else None
    try:
        flags = os.O_RDWR | os.O_CREAT | nofollow
        path = 'authorized_keys' if dir_fd is not None else str(directory / 'authorized_keys')
        if (directory / 'authorized_keys').is_symlink():
            raise ValueError('operator SSH keys must not be a symlink')
        fd = os.open(path, flags, 0o600, dir_fd=dir_fd) if dir_fd is not None else os.open(path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
                raise ValueError('operator SSH keys must be a private regular file')
            if os.name == 'posix':
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            raw = os.read(fd, 65537)
            if len(raw) > 65536:
                raise ValueError('operator SSH key store is too large')
            existing = raw.decode('ascii')
            lines = [line.strip() for line in existing.splitlines() if line.strip() and not line.startswith('#')]
            known = any(line.split()[:2] == key.split() for line in lines)
            if not known:
                if len(lines) >= 8:
                    raise ValueError('operator SSH key limit reached')
                os.lseek(fd, 0, os.SEEK_END)
                payload = ('' if not raw or raw.endswith(b'\n') else '\n') + key + '\n'
                os.write(fd, payload.encode('ascii'))
                os.fsync(fd)
            if os.name == 'posix':
                os.fchmod(fd, 0o600)
                os.fchmod(dir_fd, 0o700)
                os.fchown(fd, *owner)
                os.fchown(dir_fd, *owner)
            else:
                os.chmod(directory, 0o700)
                os.chmod(directory / 'authorized_keys', 0o600)
        finally:
            os.close(fd)
    finally:
        if dir_fd is not None:
            os.close(dir_fd)
    return {'account': 'rosy', 'port': 22, 'public_key_fingerprint': fingerprint(key),
            'host_public_key': host_key, 'host_key_fingerprint': fingerprint(host_key), 'already_registered': known}
