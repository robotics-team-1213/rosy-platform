"""Owned release path and inert import-root fixtures; no ARM import proof."""
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core_common.runtime_python import activate_core_auxiliary


class AuxiliaryLoader(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'releases'
        self.release=self.root/'2026.10.05-001'
        self.entry=self.release/'install/lib/python3.12/site-packages/core/main.py'
        self.entry.parent.mkdir(parents=True);self.entry.write_text('# inert fixture entry\n')
        self.aux=self.release/'runtime-python'
        for name in ('cryptography','cffi','pycparser'):(self.aux/name).mkdir(parents=True)
        self.previous=list(sys.path);self.addCleanup(lambda:sys.path.__setitem__(slice(None),self.previous))
        self.crypto_before=sys.modules.get('cryptography')

    def load(self):
        # CI fixtures are owned by the runner, unlike signed /opt releases.
        # Adapt UID alone to root; actual path/symlink/type/mode remain observed.
        original=Path.lstat
        def root_owned(path):
            value=original(path)
            return SimpleNamespace(st_uid=0,st_mode=value.st_mode)
        with patch.object(Path,'lstat',root_owned):
            return activate_core_auxiliary(self.entry,releases_root=self.root)

    def test_owned_release_is_the_only_added_path_without_executing_packages(self):
        self.assertEqual(self.aux,self.load())
        self.assertEqual(str(self.aux),sys.path[0])
        self.assertEqual(self.previous,sys.path[1:])
        self.assertIs(self.crypto_before,sys.modules.get('cryptography'))

    def test_outside_install_and_wrong_release_root_fail(self):
        outside=Path(self.tmp.name)/'source.py';outside.write_text('# source fixture\n')
        with self.assertRaises(RuntimeError):activate_core_auxiliary(outside,releases_root=self.root)
        with self.assertRaises(RuntimeError):activate_core_auxiliary(self.entry,releases_root=self.root/'other')

    def test_startup_hook_and_foreign_package_never_enter_sys_path(self):
        hook=self.aux/'cryptography/startup.pth';hook.write_text('raise AssertionError("must never execute")')
        with self.assertRaises(RuntimeError):self.load()
        hook.unlink();(self.aux/'foreign').mkdir()
        with self.assertRaises(RuntimeError):self.load()
        self.assertEqual(self.previous,sys.path)

    def test_symlink_and_writable_metadata_are_rejected(self):
        target=self.aux/'cryptography'
        original=Path.is_symlink
        # Windows CI cannot create symlinks without OS privilege; the branch is
        # exercised via an explicit metadata fixture, not claimed live filesystem proof.
        with patch.object(Path,'is_symlink',lambda path:path==target or original(path)):
            with self.assertRaises(RuntimeError):self.load()
        if os.name=='posix':
            target.chmod(0o777)
            with self.assertRaises(RuntimeError):self.load()
            target.chmod(0o755)
            original_stat=Path.lstat
            with patch.object(Path,'lstat',lambda p:SimpleNamespace(st_uid=1001,st_mode=original_stat(p).st_mode)):
                with self.assertRaises(RuntimeError):activate_core_auxiliary(self.entry,releases_root=self.root)


def test_allowlist_matches_the_shipped_receiver_crypto_pins():
    # 2026.10.07-050 shipped cryptography 50 while CORE only allowed 49 dist-info and crash-looped.
    import re
    from core_common.runtime_python import TOP
    req = Path(__file__).resolve().parents[3] / 'deploy/robot/pinky_pro/image/receiver-crypto-requirements.txt'
    pins = re.findall(r'^([a-z0-9_-]+)==(\S+)', req.read_text(encoding='utf-8'), re.M)
    assert {name for name, _ in pins} == {'cffi', 'cryptography', 'pycparser'}
    for name, version in pins:
        assert TOP.fullmatch(f'{name}-{version}.dist-info'), f'{name} {version} not allowed by runtime_python.TOP'
