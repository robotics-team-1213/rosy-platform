"""Admin provisioning for one dedicated bubblewrap path; never changes global sysctls."""
import argparse
import hashlib
import os
import re
import subprocess
import tempfile
import sys
from pathlib import Path

BWRAP = Path('/usr/local/libexec/rosy-deliberation/bwrap')
PROFILE_PATH = Path('/etc/apparmor.d/rosy-deliberation-bwrap')
PROFILE = b'''abi <abi/4.0>,
include <tunables/global>
profile rosy-deliberation-bwrap /usr/local/libexec/rosy-deliberation/bwrap flags=(unconfined) {
  userns,
}
'''


def dedicated_account():
    import pwd
    try:
        pwd.getpwnam('rosy-deliberation')
    except KeyError:
        subprocess.run(['/usr/sbin/useradd', '--system', '--user-group', '--create-home',
            '--home-dir', '/var/lib/rosy-deliberation', '--shell', '/usr/sbin/nologin',
            'rosy-deliberation'], check=True, timeout=10)
    return validated_account()


def validated_account():
    import pwd
    import grp
    user = pwd.getpwnam('rosy-deliberation')
    group = grp.getgrnam('rosy-deliberation')
    if (not 0 < user.pw_uid < 1000 or user.pw_gid != group.gr_gid or group.gr_mem
            or any(p.pw_gid == group.gr_gid and p.pw_name != user.pw_name for p in pwd.getpwall())
            or os.getgrouplist(user.pw_name, user.pw_gid) != [user.pw_gid]
            or user.pw_dir != '/var/lib/rosy-deliberation' or user.pw_shell != '/usr/sbin/nologin'):
        raise ValueError('DEDICATED_ACCOUNT_CONFLICT')
    return user


def trusted_directory(directory):
    for parent in (directory, *directory.parents):
        st = parent.lstat()
        if parent.resolve() != parent or st.st_uid != 0 or st.st_mode & 0o022:
            raise ValueError('UNTRUSTED_INSTALL_PARENT')


def install_file(path, data, mode, gid=0):
    trusted_directory(path.parent)
    if path.exists() or path.is_symlink():
        st = path.lstat()
        if path.is_symlink() or st.st_uid != 0 or st.st_mode & 0o022 or path.read_bytes() != data:
            raise ValueError('EXISTING_INSTALL_CONFLICT')
        if (st.st_mode & 0o777) != mode or st.st_gid != gid:
            raise ValueError('EXISTING_INSTALL_MODE_CONFLICT')
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.rosy-deliberation-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.chown(temporary, 0, gid)
            os.link(temporary, path)
        finally:
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bwrap-sha256', required=True)
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        parser.exit(2, 'LINUX_HOST_REQUIRED\n')
    if os.geteuid() != 0:
        parser.exit(2, 'ADMIN_INSTALL_REQUIRED\n')
    if re.fullmatch('[0-9a-f]{64}', args.bwrap_sha256) is None:
        parser.exit(2, 'INVALID_BWRAP_PIN\n')
    source = Path('/usr/bin/bwrap')
    try:
        st = source.stat()
        data = source.read_bytes()
        if st.st_uid != 0 or st.st_mode & 0o022 or not data.startswith(b'\x7fELF') or hashlib.sha256(data).hexdigest() != args.bwrap_sha256:
            raise ValueError('BWRAP_SOURCE_PIN_MISMATCH')
        subprocess.run(['/usr/sbin/apparmor_parser', '-Q', '-T'], input=PROFILE, check=True, timeout=10)
        user = dedicated_account()
        # Install only under the fixed admin-owned hierarchy, never overwrite a foreign file.
        for directory in (BWRAP.parent.parent, BWRAP.parent):
            trusted_directory(directory.parent)
            created = not directory.exists()
            mode, gid = (0o750, user.pw_gid) if directory == BWRAP.parent else (0o755, 0)
            directory.mkdir(mode=mode, exist_ok=True)
            if created:
                directory.chmod(mode)
                os.chown(directory, 0, gid)
            trusted_directory(directory)
            if directory.stat().st_gid != gid or directory.stat().st_mode & 0o777 != mode:
                raise ValueError('EXISTING_INSTALL_DIRECTORY_CONFLICT')
        install_file(BWRAP, data, 0o750, user.pw_gid)
        install_file(PROFILE_PATH, PROFILE, 0o644)
        subprocess.run(['/usr/sbin/apparmor_parser', '-r', '-T', str(PROFILE_PATH)], check=True, timeout=10)
        subprocess.run(['/usr/bin/loginctl', 'enable-linger', user.pw_name], check=True, timeout=10)
        subprocess.run(['/usr/bin/systemctl', 'start', f'user@{user.pw_uid}.service'], check=True, timeout=20)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'INSTALL_HOLD: {type(exc).__name__}: {exc}\n')
    print('INSTALLED; run deliberation_preflight.py before admitting any provider')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
