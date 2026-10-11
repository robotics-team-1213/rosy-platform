import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from deploy.site.deliberation_install import PROFILE, BWRAP


def test_profile_allows_only_dedicated_sandbox_path(tmp_path):
    profile = tmp_path / 'profile'
    profile.write_bytes(PROFILE)
    parsed = subprocess.run(['/sbin/apparmor_parser', '-Q', '-T', str(profile)],
        capture_output=True, text=True, timeout=10)
    assert parsed.returncode == 0, parsed.stderr
    assert str(BWRAP).encode() in PROFILE and b'/usr/bin/bwrap' not in PROFILE
    assert b'userns,' in PROFILE


def test_installer_refuses_non_admin_before_changes():
    import os
    if os.geteuid() == 0:
        pytest.skip('checks real unprivileged refusal')
    result = subprocess.run([sys.executable, '-m', 'deploy.site.deliberation_install',
        '--bwrap-sha256', hashlib.sha256(b'fixture').hexdigest()],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'ADMIN_INSTALL_REQUIRED' in result.stderr
