"""Publication interruptions and stale writers through real firstboot consumers."""
import json

import pytest

from test_os_first_boot_state import SERIAL, _provision_a

POLICY = "etc/rosy/network-policy.json"


def _update(first, root, relative, value, *, expected=None):
    module = first._native_helper("os_state_config")
    with module.configuration_update(root, expected_generation=expected) as update:
        update.stage(relative, json.dumps(value).encode("utf-8") if value is not None else None, 0o600)
        update.commit()


@pytest.mark.parametrize("point", ["before_pointer", "before_completion"])
def test_interrupted_revision_keeps_a_proven_old_or_new_generation(tmp_path, monkeypatch, point):
    first, root_a, root_b, common, bundle = _provision_a(tmp_path, monkeypatch)
    previous = json.loads((common / "state/current.json").read_text())
    module = first._native_helper("os_state_config" if point == "before_pointer" else "os_state_firstboot")
    write = module._json_atomic
    target = (root_a / "var/lib/rosy-device/state/current.json" if point == "before_pointer" else
              root_a / "var/lib/rosy/provisioning/complete.json")

    def interrupted(path, payload, mode):
        if path == target:
            raise OSError("modeled configuration publication interruption")
        return write(path, payload, mode)

    monkeypatch.setattr(module, "_json_atomic", interrupted)
    expected_error = OSError if point == "before_pointer" else ValueError
    with pytest.raises(expected_error, match="modeled configuration"):
        _update(first, root_a, POLICY, {"mode": "off"})
    assert (common / "state/config-publishing.json").exists()
    assert first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    current = json.loads((common / "state/current.json").read_text())
    if point == "before_pointer":
        assert current == previous
        assert not (root_b / POLICY).exists()
    else:
        assert current != previous
        assert json.loads((root_b / POLICY).read_text())["mode"] == "off"
    completion = json.loads((common / "provisioning/complete.json").read_text())
    assert completion["os_state"]["generation"] == current["generation"]
    assert not (common / "state/config-publishing.json").exists()


def test_a_stale_revision_does_not_project_or_publish_from_another_root(tmp_path, monkeypatch):
    first, root_a, root_b, common, _ = _provision_a(tmp_path, monkeypatch)
    previous = json.loads((common / "state/current.json").read_text())["generation"]
    _update(first, root_a, POLICY, {"mode": "off"})
    current = (common / "state/current.json").read_bytes()
    with pytest.raises(ValueError, match="revision changed"):
        _update(first, root_b, POLICY, {"mode": "relay"}, expected=previous)
    assert not (root_b / POLICY).exists()
    assert (common / "state/current.json").read_bytes() == current


def test_a_committed_deletion_removes_cached_files_in_b_and_then_a(tmp_path, monkeypatch):
    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    _update(first, root_a, POLICY, {"mode": "off"})
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    assert (root_b / POLICY).exists()
    _update(first, root_a, POLICY, None)
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    first.FirstBootProvisioner(root=root_a).apply(bundle=bundle, hardware_serial=SERIAL)
    assert not (root_a / POLICY).exists()
    assert not (root_b / POLICY).exists()


def test_timezone_deletion_removes_the_derived_cached_timezone_too(tmp_path, monkeypatch):
    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    for root in (root_a, root_b):
        for name in ("Asia/Seoul", "Etc/UTC"):
            zone = root / "usr/share/zoneinfo" / name
            zone.parent.mkdir(parents=True, exist_ok=True)
            zone.write_bytes(b"TZif synthetic zone payload")
    _update(first, root_a, "etc/rosy/timezone.json", {"schema_version": 1, "timezone": "Asia/Seoul"})
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    _update(first, root_a, "etc/rosy/timezone.json", None)
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    for root in (root_a, root_b):
        assert str((root / "etc/localtime").readlink()) == "/usr/share/zoneinfo/Etc/UTC"
        assert not (root / "etc/rosy/timezone.json").exists()


def test_an_interrupted_revision_cannot_recover_using_a_forged_completion_proof(tmp_path, monkeypatch):
    first, root_a, root_b, common, bundle = _provision_a(tmp_path, monkeypatch)
    state = first._native_helper("os_state_firstboot")
    write = state._json_atomic

    def interrupted(path, value, mode):
        if path == root_a / "var/lib/rosy/provisioning/complete.json":
            raise OSError("modeled publication interruption")
        return write(path, value, mode)

    monkeypatch.setattr(state, "_json_atomic", interrupted)
    with pytest.raises(ValueError, match="modeled publication"):
        _update(first, root_a, POLICY, {"mode": "off"})
    journal = common / "state/config-publishing.json"
    record = json.loads(journal.read_text())
    record["previous_completion_sha256"] = "0" * 64
    journal.write_text(json.dumps(record), encoding="utf-8")
    completion = (common / "provisioning/complete.json").read_bytes()
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    assert not (root_b / "etc/hostname").exists()
    assert (common / "provisioning/complete.json").read_bytes() == completion
