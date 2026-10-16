import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from deploy.site.deliberation_install import PROFILE, BWRAP


@pytest.mark.skipif(not Path('/sbin/apparmor_parser').exists(),
                    reason='needs the host AppArmor parser (the CI container and Windows have none)')
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


def test_install_refuses_untrusted_parent_before_writing(tmp_path):
    from deploy.site.deliberation_install import install_file
    destination = tmp_path / 'must-not-exist'
    with pytest.raises(ValueError, match='UNTRUSTED_INSTALL_PARENT'):
        install_file(destination, b'fixture', 0o755)
    assert not destination.exists()


def test_installer_does_not_adopt_existing_operator_account(monkeypatch):
    import grp
    import pwd
    from types import SimpleNamespace
    from deploy.site.deliberation_install import dedicated_account
    monkeypatch.setattr(pwd, 'getpwnam', lambda name: SimpleNamespace(pw_uid=1000, pw_gid=1000))
    monkeypatch.setattr(grp, 'getgrnam', lambda name: SimpleNamespace(gr_gid=1000, gr_mem=[]))
    with pytest.raises(ValueError, match='DEDICATED_ACCOUNT_CONFLICT'):
        dedicated_account()


@pytest.mark.parametrize('primary_member', [False, True])
def test_readonly_account_check_rejects_group_drift(monkeypatch, primary_member):
    import grp
    import pwd
    from types import SimpleNamespace
    from deploy.site.deliberation_install import validated_account
    user = SimpleNamespace(pw_uid=990, pw_gid=990, pw_name='rosy-deliberation',
        pw_dir='/var/lib/rosy-deliberation', pw_shell='/usr/sbin/nologin')
    monkeypatch.setattr(pwd, 'getpwnam', lambda name: user)
    monkeypatch.setattr(grp, 'getgrnam', lambda name: SimpleNamespace(
        gr_gid=990, gr_mem=[] if primary_member else ['operator']))
    monkeypatch.setattr(pwd, 'getpwall', lambda: [user, SimpleNamespace(pw_gid=990, pw_name='operator')])
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail('read-only check spawned a command'))
    with pytest.raises(ValueError, match='DEDICATED_ACCOUNT_CONFLICT'):
        validated_account()
