"""Protected installation never treats user staging or foreign root paths as approval."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'deploy/ai_pc/install-status-broker.py'


def test_installer_requires_admin_before_mutation(tmp_path):
    import os
    if os.geteuid()==0:pytest.skip('requires an unprivileged test account')
    result=subprocess.run([sys.executable,str(SCRIPT),str(tmp_path),str(tmp_path/'manifest'),
        str(tmp_path/'key'),'--manifest-sha256','a'*64],capture_output=True,text=True,timeout=5,
        env={**os.environ,'PYTHONPATH':str(SCRIPT.parents[2])})
    assert result.returncode!=0 and 'root installation required' in result.stderr
    assert list(tmp_path.iterdir())==[]


def test_managed_replacement_rejects_foreign_target_and_symlink(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('status_install',SCRIPT)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'trusted_directory',lambda _:None)
    target=tmp_path/'foreign';target.write_bytes(b'untouched')
    for path in (target,tmp_path/'link'):
        if path!=target:path.symlink_to(target)
        with pytest.raises(ValueError,match='FOREIGN_INSTALL_FILE_REFUSED'):
            module.replace_owned(path,b'changed',0o644,0,'a'*40,validate=lambda _:False)
    assert target.read_bytes()==b'untouched'
    assert not list(tmp_path.glob('*.before-*'))
