import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from deploy.ai_pc import deliberation_free_key as key


def info(uid, gid, mode):
    return SimpleNamespace(st_uid=uid, st_gid=gid, st_mode=0o040000 | mode)

@pytest.mark.parametrize('uid,gid', [(0,984),(997,984)])
def test_existing_parent_accepts_root_or_dedicated_home(uid,gid):
    key.validate_parent(Path('/var/lib/rosy-deliberation'), info(uid,gid,0o750),997,984)

@pytest.mark.parametrize('uid,gid,mode', [(1000,984,0o750),(997,1000,0o750),(997,984,0o777),(997,984,0o700)])
def test_parent_rejects_foreign_or_changed_boundary(uid,gid,mode):
    with pytest.raises(ValueError,match='SECRET_PARENT_BOUNDARY_FAILED'):
        key.validate_parent(Path('/var/lib/rosy-deliberation'),info(uid,gid,mode),997,984)


def test_existing_key_idempotent_and_different_key_preserved(tmp_path):
    target=tmp_path/'key.json'; target.write_bytes(b'{"type":"api","key":"existing"}')
    target.chmod(0o600)
    assert key.existing_key(target,target.read_bytes(),os.getuid(),os.getgid())
    with pytest.raises(ValueError,match='EXISTING_SELECTED_KEY_DIFFERS'):
        key.existing_key(target,b'{"type":"api","key":"new"}',os.getuid(),os.getgid())
    assert b'existing' in target.read_bytes()


def test_existing_symlink_rejected(tmp_path):
    original=tmp_path/'original'; original.write_bytes(b'private'); original.chmod(0o600)
    target=tmp_path/'key'; target.symlink_to(original)
    with pytest.raises(ValueError,match='EXISTING_SELECTED_KEY_BOUNDARY_FAILED'):
        key.existing_key(target,b'new',os.getuid(),os.getgid())
    assert original.read_bytes()==b'private'

def test_import_preserves_real_account_owned_home_and_original_budget(tmp_path, monkeypatch):
    from deploy.site import deliberation_install
    home=tmp_path/'home';home.mkdir(mode=0o750)
    budget=home/'smoke';budget.mkdir(mode=0o700)
    marker=budget/'glm-first-review.spent';marker.write_bytes(b'unknown-existing-spend')
    source=tmp_path/'auth.json';source.write_text('{"opencode":{"type":"api","key":"selected"},"google":{"key":"other"}}')
    source.chmod(0o600)
    account=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())
    monkeypatch.setattr(deliberation_install,'validated_account',lambda:account)
    monkeypatch.setattr(key.pwd,'getpwnam',lambda name:account)
    monkeypatch.setattr(key.os,'geteuid',lambda:0)
    monkeypatch.setattr(key,'SOURCE',source)
    monkeypatch.setattr(key,'TARGET',home/'opencode-free.json')
    before=home.stat()
    key.main()
    after=home.stat()
    assert (before.st_uid,before.st_gid,before.st_mode)==(after.st_uid,after.st_gid,after.st_mode)
    assert (home/'opencode-free.json').read_bytes()==b'{"type":"api","key":"selected"}'
    assert (home/'opencode-free.json').stat().st_mode & 0o777==0o600
    assert marker.read_bytes()==b'unknown-existing-spend'
    key.main()
    assert marker.read_bytes()==b'unknown-existing-spend'
