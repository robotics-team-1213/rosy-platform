"""A/B boot recovery uses frozen code after projection and factory verification."""
import json
import os
from types import SimpleNamespace

import pytest

from test_os_factory_release import _device, _factory, FACTORY_ID
from test_os_tailnet_state import _serial


def _case(tmp_path, monkeypatch):
    first, root, _, common, private, public, _ = _device(tmp_path, monkeypatch)
    (root / "opt/rosy/current").symlink_to("releases/" + FACTORY_ID)
    return first, root, common, private, public


def test_frozen_recovery_restores_an_interrupted_payload_before_runtime(tmp_path, monkeypatch):
    first, root, common, private, public = _case(tmp_path, monkeypatch)
    descriptor = root / "etc/rosy/os-factory-release.json"
    binding = descriptor.read_bytes()
    candidate = "2026.10.26-004"
    _factory(root, candidate, private, public, signed=True)
    descriptor.write_bytes(binding)
    current = root / "opt/rosy/current"
    current.unlink()
    current.symlink_to("releases/" + candidate)
    manager = first._native_release().NativeReleaseManager(root=root, public_key=root / first.TRUSTED_RELEASE_KEY)
    manager.journal.parent.mkdir(parents=True)
    manager.journal.write_text(json.dumps(dict(schema_version=1, operation="activate", candidate=candidate,
        old_current=FACTORY_ID, old_previous=None, phase="switched")))
    completion = (common / "provisioning/complete.json").read_bytes()
    report = first._native_helper("os_boot_recover").recover(root, run=lambda *_a, **_kw: SimpleNamespace(returncode=0))
    assert report["phase"] == "RECOVERED"
    assert report["release_id"] == FACTORY_ID
    assert current.is_symlink()
    assert current.resolve() == root / "opt/rosy/releases" / FACTORY_ID
    assert not manager.journal.exists()
    assert (common / "provisioning/complete.json").read_bytes() == completion


def test_wrong_board_cannot_enter_payload_recovery(tmp_path, monkeypatch):
    first, root, common, _, _ = _case(tmp_path, monkeypatch)
    module = first._native_helper("os_boot_recover")
    _serial(root, "10000000abcdef02")
    before = os.readlink(root / "opt/rosy/current")
    completion = (common / "provisioning/complete.json").read_bytes()
    with pytest.raises(ValueError):
        module.recover(root, run=lambda *_a, **_kw: pytest.fail("recovery must refuse before commands"))
    assert os.readlink(root / "opt/rosy/current") == before
    assert (common / "provisioning/complete.json").read_bytes() == completion


def test_recovery_requires_a_verified_active_payload(tmp_path, monkeypatch):
    first, root, _, _, _ = _case(tmp_path, monkeypatch)
    (root / "opt/rosy/current").unlink()
    with pytest.raises(ValueError, match="active"):
        first._native_helper("os_boot_recover").recover(root)


def test_failed_unit_reload_holds_boot_recovery(tmp_path, monkeypatch):
    first, root, _, _, _ = _case(tmp_path, monkeypatch)
    module = first._native_helper("os_boot_recover")

    def reconcile(_root, run):
        run(["systemctl", "daemon-reload"])

    monkeypatch.setattr(module, "_reconciler", lambda: SimpleNamespace(reconcile_at_boot=reconcile))
    with pytest.raises(ValueError, match="reload"):
        module.recover(root, run=lambda *_a, **_kw: SimpleNamespace(returncode=1))
