"""Real TLS CLI body/OpenSSL/IO; root ownership and outer privilege locks are modeled."""
import contextlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from test_native_tls_provision import tls
from test_os_first_boot_state import SERIAL, _provision_a


@pytest.fixture
def device(tmp_path, monkeypatch):
    first, root, other, common, bundle = _provision_a(tmp_path, monkeypatch)
    owner = root.stat().st_uid
    ownership = {}
    monkeypatch.setattr(os, "fchown", lambda *_: None)

    class Store(tls.Store):
        # The test PC is unprivileged. Only root UID/GID and privileged outer
        # locks are modeled; canonical flock, descriptor IO and fsync stay real.
        def check(self, info, **kwargs):
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            if info.st_uid == owner:
                fields["st_uid"] = 0
            return super().check(SimpleNamespace(**fields), **kwargs)

        def read(self, relative, **kwargs):
            record = super().read(relative, **kwargs)
            if record is None:
                return None
            data, meta = record
            uid, gid = ownership.get(str((self.root / relative).resolve()), (0, 0))
            return data, (*meta[:2], uid, gid, *meta[4:])

        def atomic(self, relative, data, uid, gid, mode):
            super().atomic(relative, data, uid, gid, mode)
            ownership[str((self.root / relative).resolve())] = uid, gid

        def ensure_tls_directory(self):
            info = (self.root / tls.TLS).stat()
            assert info.st_uid == owner and info.st_gid == 960 and info.st_mode & 0o7777 == 0o750

        @contextlib.contextmanager
        def lock(self, *_args, **_kwargs):
            yield lambda: None

    store = Store(root, 960, 960)
    return first, store, other, common, bundle


def _apply(store, tmp_path, fence=lambda: None):
    return tls.provision(store, "fixture-holder", "fixture-robot.local", yaml,
                         fence=fence, stage_parent=tmp_path)


def test_actual_tls_owner_publishes_runtime_for_b_and_return_to_a(device, tmp_path):
    first, store, other, common, bundle = device
    assert _apply(store, tmp_path)["ok"]
    expected = (store.root / tls.ENV).read_bytes()
    assert b"ROSY_API_TLS=required\n" in expected
    ca = (common / "tls/ca.pem").read_bytes()
    for root in (other, store.root):
        assert first.FirstBootProvisioner(root=root).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
        assert (root / tls.ENV).read_bytes() == expected
        assert (root / tls.TLS / "ca.pem").read_bytes() == ca


def test_tls_interrupted_file_write_can_resume_without_reissuing_the_ca(device, tmp_path):
    first, store, other, common, bundle = device
    atomic = store.atomic
    lost = False

    def interrupted(relative, *args):
        nonlocal lost
        atomic(relative, *args)
        if relative == tls.TLS + "/ca.key":
            lost = True
            raise OSError("modeled write interruption")

    def fence():
        if lost:
            raise tls.Hold("modeled lost maintenance fence")

    store.atomic = interrupted
    with pytest.raises(tls.Hold):
        _apply(store, tmp_path, fence)
    pending = common / "state/tls-pending.json"
    assert pending.is_file(), "incomplete TLS changes need a durable recovery record"
    ca = (common / "tls/ca.pem").read_bytes()
    writer = first._native_helper("os_state_config")
    with pytest.raises(ValueError, match="TLS.*pending"):
        with writer.configuration_update(store.root):
            pass
    store.atomic = atomic
    assert _apply(store, tmp_path)["ok"]
    assert not pending.exists()
    assert (common / "tls/ca.pem").read_bytes() == ca
    assert first.FirstBootProvisioner(root=other).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    assert b"ROSY_API_TLS=required\n" in (other / tls.ENV).read_bytes()
