"""Admin provisioning for one dedicated bubblewrap path; never changes global sysctls."""
import argparse
import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

BWRAP = Path('/usr/local/libexec/rosy-deliberation/bwrap')
PROFILE_PATH = Path('/etc/apparmor.d/rosy-deliberation-bwrap')
PROFILE = b'''abi <abi/4.0>,
include <tunables/global>
profile rosy-deliberation-bwrap /usr/local/libexec/rosy-deliberation/bwrap flags=(unconfined) {
  userns,
}
'''


def install_file(path, data, mode):
    for parent in (path.parent, *path.parent.parents):
        st = parent.stat()
        if parent.resolve() != parent or st.st_uid != 0 or st.st_mode & 0o022:
            raise ValueError('UNTRUSTED_INSTALL_PARENT')
    if path.exists() or path.is_symlink():
        st = path.lstat()
        if path.is_symlink() or st.st_uid != 0 or st.st_mode & 0o022 or path.read_bytes() != data:
            raise ValueError('EXISTING_INSTALL_CONFLICT')
        if (st.st_mode & 0o777) != mode:
            raise ValueError('EXISTING_INSTALL_MODE_CONFLICT')
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.rosy-deliberation-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.link(temporary, path)
        finally:
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bwrap-sha256', required=True)
    args = parser.parse_args(argv)
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
        # Install only under the fixed admin-owned hierarchy, never overwrite a foreign file.
        for directory in (BWRAP.parent.parent, BWRAP.parent):
            directory.mkdir(mode=0o755, exist_ok=True)
        install_file(BWRAP, data, 0o755)
        install_file(PROFILE_PATH, PROFILE, 0o644)
        subprocess.run(['/usr/sbin/apparmor_parser', '-r', '-T', str(PROFILE_PATH)], check=True, timeout=10)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'INSTALL_HOLD: {type(exc).__name__}: {exc}\n')
    print('INSTALLED; run deliberation_preflight.py before admitting any provider')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
