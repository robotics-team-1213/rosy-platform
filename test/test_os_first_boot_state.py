"""Firstboot consumers must prepare each root, even when common completion exists."""
import json

import pytest

from os_state_boot_fakes import shared_roots
from test_first_boot_provisioning import _bundle, _module

SERIAL = "10000000abcdef01"


def _provision_a(tmp_path, monkeypatch):
    root_a, root_b, common, boot = shared_roots(tmp_path, monkeypatch)
    bundle = root_a / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    module = _module()
    first = module.FirstBootProvisioner(root=root_a, network_activate=lambda _: True)
    report = first.apply(bundle=bundle, hardware_serial=SERIAL)
    assert report["state"] == "PROVISIONED", report
    assert not bundle.exists()
    assert (root_b / "var/lib/rosy/provisioning/complete.json").exists()
    return module, root_a, root_b, common, bundle


def test_committed_identity_and_runtime_are_projected_before_b_is_already_provisioned(tmp_path, monkeypatch):
    module, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    report = module.FirstBootProvisioner(root=root_b, network_activate=lambda _: True).apply(
        bundle=bundle, hardware_serial=SERIAL)
    assert report["ok"] is True, report
    for name in ("etc/rosy/device-identity.json", "etc/rosy/runtime.env", "etc/hostname"):
        target = root_b / name
        assert target.is_file(), f"common completion did not prepare B: {name}"
        assert target.read_bytes() == (root_a / name).read_bytes()
    assert not bundle.exists(), "B must recover from committed state without a new card bundle"


def test_common_completion_without_its_committed_generation_is_a_hold(tmp_path, monkeypatch):
    module, _, root_b, common, bundle = _provision_a(tmp_path, monkeypatch)
    (common / "state/current.json").unlink(missing_ok=True)
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        module.FirstBootProvisioner(root=root_b, network_activate=lambda _: True).apply(
            bundle=bundle, hardware_serial=SERIAL)


def test_another_identity_cached_in_b_does_not_gain_common_completion(tmp_path, monkeypatch):
    module, _, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    identity = _bundle()["device_identity"]
    identity["device_uid"] = "118cc587-047a-455d-babe-75573533a736"
    (root_b / "etc/rosy/device-identity.json").write_text(json.dumps(identity), encoding="ascii")
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        module.FirstBootProvisioner(root=root_b, network_activate=lambda _: True).apply(
            bundle=bundle, hardware_serial=SERIAL)


def test_bind_fixture_does_not_allow_an_unmanaged_core_symlink(tmp_path, monkeypatch):
    root_a, _, common, boot = shared_roots(tmp_path, monkeypatch)
    external = tmp_path / "unmanaged-core"
    external.mkdir()
    (common / "core/.rosy").symlink_to(external, target_is_directory=True)
    bundle = root_a / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    with pytest.raises(ValueError, match="symlink|not a directory|OS_STATE_HOLD"):
        _module().FirstBootProvisioner(root=root_a, network_activate=lambda _: True).apply(
            bundle=bundle, hardware_serial=SERIAL)
    assert list(external.iterdir()) == []


def test_missing_factory_marker_is_not_inferred_as_a_new_card(tmp_path, monkeypatch):
    root_a, _, common, boot = shared_roots(tmp_path, monkeypatch)
    (common / "state/factory.json").unlink()
    bundle = root_a / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        _module().FirstBootProvisioner(root=root_a).apply(bundle=bundle, hardware_serial=SERIAL)
    assert not (root_a / "etc/rosy/device-identity.json").exists()
    assert bundle.exists()


def test_interruption_after_generation_commit_recovers_before_consuming_bundle(tmp_path, monkeypatch):
    root_a, root_b, common, boot = shared_roots(tmp_path, monkeypatch)
    bundle = root_a / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    module = _module()
    write = module._json_atomic

    def interrupted(path, value, mode):
        if path == root_a / "var/lib/rosy/provisioning/complete.json":
            raise OSError("modeled interruption before completion")
        return write(path, value, mode)

    monkeypatch.setattr(module, "_json_atomic", interrupted)
    with pytest.raises(OSError, match="modeled interruption"):
        module.FirstBootProvisioner(root=root_a, network_activate=lambda _: True).apply(
            bundle=bundle, hardware_serial=SERIAL)
    assert (common / "state/current.json").exists()
    assert not (common / "provisioning/complete.json").exists()
    assert bundle.exists()
    report = module.FirstBootProvisioner(root=root_b, network_activate=lambda _: True).apply(
        bundle=root_b / "run/rosy-provision-boot/rosy-provision/provision.json", hardware_serial=SERIAL)
    assert report["ok"] is True
    assert (root_b / "etc/rosy/runtime.env").is_file()
    assert not bundle.exists()


def test_interrupted_unpublished_generation_does_not_prevent_same_bundle_retry(tmp_path, monkeypatch):
    root_a, _, common, boot = shared_roots(tmp_path, monkeypatch)
    bundle = root_a / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    module = _module()
    state = module._native_helper("os_state_firstboot")
    write = state._write_atomic

    def interrupted(path, content, mode):
        if "/generations/" in str(path):
            raise OSError("modeled generation interruption")
        return write(path, content, mode)

    monkeypatch.setattr(state, "_write_atomic", interrupted)
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        module.FirstBootProvisioner(root=root_a, network_activate=lambda _: True).apply(
            bundle=root_a / "run/rosy-provision-boot/rosy-provision/provision.json", hardware_serial=SERIAL)
    assert bundle.exists()
    assert not (common / "state/current.json").exists()
    abandoned = json.loads((common / "state/initializing.json").read_text())["generation"]
    monkeypatch.setattr(state, "_write_atomic", write)
    report = module.FirstBootProvisioner(root=root_a, network_activate=lambda _: True).apply(
        bundle=root_a / "run/rosy-provision-boot/rosy-provision/provision.json", hardware_serial=SERIAL)
    assert report["ok"] is True
    current = json.loads((common / "state/current.json").read_text())["generation"]
    assert current != abandoned
    assert not bundle.exists()


def test_corrupt_generation_is_rejected_before_any_b_projection(tmp_path, monkeypatch):
    module, _, root_b, common, bundle = _provision_a(tmp_path, monkeypatch)
    pointer = json.loads((common / "state/current.json").read_text())
    blob = common / "state/generations" / pointer["generation"] / "etc__rosy__runtime.env"
    blob.write_text("ROSY_DEVICE_UID=corrupt\n", encoding="ascii")
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        module.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    assert not (root_b / "etc/hostname").exists()


@pytest.mark.parametrize("change", ["missing", "wrong_subpath", "read_only"])
@pytest.mark.parametrize("point", ["/var/lib/rosy/provisioning", "/var/lib/rosy/core",
                                   "/etc/NetworkManager/system-connections", "/var/lib/rosy/ssh",
                                   "/home/rosy/.ssh"])
def test_root_local_or_wrong_shared_provisioning_is_refused_before_identity(tmp_path, monkeypatch, change, point):
    root_a, _, _, _ = shared_roots(tmp_path, monkeypatch)
    for name in ("proc/1/mountinfo", "proc/self/mountinfo"):
        table = root_a / name
        lines = table.read_text().splitlines(keepends=True)
        for index, line in enumerate(lines):
            if f" {point} " in line:
                lines[index] = ("" if change == "missing" else
                                " ".join([*line.split()[:3], "/foreign", *line.split()[4:]]) + "\n"
                                if change == "wrong_subpath" else
                                line.replace(" rw -", " ro -"))
        table.write_text("".join(lines), encoding="ascii")
    bundle = root_a / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        _module().FirstBootProvisioner(root=root_a, network_activate=lambda _: True).apply(
            bundle=bundle, hardware_serial=SERIAL)
    assert not (root_a / "etc/rosy/device-identity.json").exists()
    assert bundle.exists()


def test_projection_repairs_a_cached_runtime_file_with_excessive_read_permissions(tmp_path, monkeypatch):
    module, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    target = root_b / "etc/rosy/runtime.env"
    target.write_bytes((root_a / "etc/rosy/runtime.env").read_bytes())
    target.chmod(0o644)
    report = module.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    assert report["ok"] is True
    assert target.stat().st_mode & 0o777 == 0o640


def test_cli_default_selects_the_admitted_boot_a_bundle(tmp_path, monkeypatch, capsys):
    root_a, _, _, _ = shared_roots(tmp_path, monkeypatch)
    bundle = root_a / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    module = _module()
    monkeypatch.setattr(module, "_default_network_activate", lambda _: True)
    code = module._main(["--root", str(root_a), "--hardware-serial", SERIAL])
    assert code == 0, capsys.readouterr().out
    assert not bundle.exists()


def test_cli_check_rejects_bad_storage_before_loading_cached_network(tmp_path, monkeypatch, capsys):
    root_a, _, _, _ = shared_roots(tmp_path, monkeypatch)
    (root_a / "etc/rosy/os-slot.json").write_text("{}", encoding="ascii")
    profile = root_a / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection"
    profile.write_text("[connection]\nid=rosy-site-sta\n", encoding="ascii")
    module = _module()
    calls = []
    monkeypatch.setattr(module, "_nmcli", lambda *args: calls.append(args) or (0, ""))
    monkeypatch.setattr(module, "site_wifi_up", lambda _: False)
    assert module._main(["--root", str(root_a), "--hardware-serial", SERIAL, "--network", "check"]) == 1
    assert calls == [], "invalid storage must not load a cached profile"
    assert "OS_STATE_HOLD" in capsys.readouterr().out


def test_cli_check_rejects_a_bundle_on_the_other_boot_before_network(tmp_path, monkeypatch, capsys):
    root_a, _, _, _ = shared_roots(tmp_path, monkeypatch)
    profile = root_a / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection"
    profile.write_text("[connection]\nid=rosy-site-sta\n", encoding="ascii")
    module = _module()
    calls = []
    monkeypatch.setattr(module, "_nmcli", lambda *args: calls.append(args) or (0, ""))
    monkeypatch.setattr(module, "site_wifi_up", lambda _: False)
    wrong = root_a / "boot/firmware/rosy-provision/provision.json"
    assert module._main(["--root", str(root_a), "--bundle", str(wrong),
                         "--hardware-serial", SERIAL, "--network", "check"]) == 1
    assert calls == []
    assert "OS_STATE_HOLD" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["missing_factory", "invalid_factory", "invalid_initialization"])
def test_cli_check_validates_common_phase_before_network(tmp_path, monkeypatch, capsys, change):
    root_a, _, common, _ = shared_roots(tmp_path, monkeypatch)
    if change == "missing_factory":
        (common / "state/factory.json").unlink()
    elif change == "invalid_factory":
        (common / "state/factory.json").write_text("{}", encoding="ascii")
    else:
        (common / "state/initializing.json").write_text("{}", encoding="ascii")
    profile = root_a / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection"
    profile.write_text("[connection]\nid=rosy-site-sta\n", encoding="ascii")
    module = _module()
    calls = []
    monkeypatch.setattr(module, "_nmcli", lambda *args: calls.append(args) or (0, ""))
    monkeypatch.setattr(module, "site_wifi_up", lambda _: False)
    assert module._main(["--root", str(root_a), "--hardware-serial", SERIAL, "--network", "check"]) == 1
    assert calls == []
    assert "OS_STATE_HOLD" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["core_uid", "operator_gid", "alias_uid", "missing_group"])
def test_account_mismatch_is_refused_before_shared_home_or_identity_changes(tmp_path, monkeypatch, change):
    root_a, _, common, _ = shared_roots(tmp_path, monkeypatch)
    passwd, group = root_a / "etc/passwd", root_a / "etc/group"
    if change == "core_uid":
        passwd.write_text(passwd.read_text().replace("rosy-core:x:960:", "rosy-core:x:970:"), encoding="ascii")
    elif change == "operator_gid":
        passwd.write_text(passwd.read_text().replace("rosy:x:1001:1001:", "rosy:x:1001:1002:"), encoding="ascii")
    elif change == "alias_uid":
        passwd.write_text(passwd.read_text() + "foreign:x:960:1005::/nonexistent:/bin/false\n", encoding="ascii")
    else:
        group.write_text(group.read_text().replace("rosy-core:x:960:\n", ""), encoding="ascii")
    bundle = root_a / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        _module().FirstBootProvisioner(root=root_a, network_activate=lambda _: True).apply(
            bundle=bundle, hardware_serial=SERIAL)
    assert not (root_a / "etc/rosy/device-identity.json").exists()
    assert not (common / "core/.rosy").exists()
    assert bundle.exists()


@pytest.mark.parametrize("change", ["uid", "gid", "permissions"])
def test_foreign_shared_home_is_not_reowned_by_firstboot(tmp_path, monkeypatch, change):
    import os
    from types import SimpleNamespace

    root_a, _, common, _ = shared_roots(tmp_path, monkeypatch)
    target = root_a / "var/lib/rosy/core"
    if change == "permissions":
        target.chmod(0o777)
    else:
        original = os.stat

        def foreign_home(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if not isinstance(path, int) and os.fspath(path) == str(target):
                fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
                fields["st_" + change] = 970
                return SimpleNamespace(**fields)
            return info

        monkeypatch.setattr(os, "stat", foreign_home)
    bundle = root_a / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    with pytest.raises(ValueError, match="OS_STATE_HOLD"):
        _module().FirstBootProvisioner(root=root_a, network_activate=lambda _: True).apply(
            bundle=bundle, hardware_serial=SERIAL)
    assert not (common / "core/.rosy").exists()
    assert not (common / "state/current.json").exists()
    assert bundle.exists()
