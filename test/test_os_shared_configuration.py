"""Real config application must survive A→B→A, including prior cached files."""
import json
from pathlib import Path

import pytest

from os_state_boot_fakes import shared_roots
from test_os_first_boot_state import SERIAL, _provision_a
from test_first_boot_provisioning import _bundle, _module as firstboot_module
from test_rosy_config_apply import _module as config_module


def _card(root, text):
    path = root / "run/rosy-provision-boot/rosy-config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("schema_version: 1\n" + text, encoding="utf-8")
    # Older roots may retain their own boot file; it must not override the shared input on fallback.
    legacy = root / "boot/firmware/rosy-config.yaml"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(path.read_bytes())
    return path


@pytest.mark.parametrize('relative', ['etc/rosy/ir_calibration.yaml', 'etc/rosy/line_observer_overrides.yaml'])
def test_operator_overlay_changes_and_deletion_survive_fallback(tmp_path, monkeypatch, relative):
    from os_state_config import configuration_update

    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch, protocol=2)
    with configuration_update(root_a) as update:
        update.stage(relative, b'calibration: first\n', 0o644)
        update.commit()
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    assert (root_b / relative).read_bytes() == b'calibration: first\n'
    with configuration_update(root_b) as update:
        update.stage(relative, b'calibration: replacement\n', 0o644)
        update.commit()
    first.FirstBootProvisioner(root=root_a).apply(bundle=bundle, hardware_serial=SERIAL)
    assert (root_a / relative).read_bytes() == b'calibration: replacement\n'
    with configuration_update(root_b) as update:
        update.stage(relative, None, 0o644)
        update.commit()
    first.FirstBootProvisioner(root=root_a).apply(bundle=bundle, hardware_serial=SERIAL)
    assert not (root_a / relative).exists()


def test_host_lane_change_and_restart_rollback_publish_canonical_overlay(tmp_path, monkeypatch):
    from host_lane_perception import LanePerceptionConfig
    from os_state_config import configuration_update
    from test_lane_perception_host import idle

    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch, protocol=2)
    relative = 'etc/rosy/line_observer_overrides.yaml'
    original = b'/**/line_observer_node:\n  ros__parameters:\n    camera_lane_mode: keep\n'
    with configuration_update(root_a) as update:
        update.stage(relative, original, 0o644)
        update.commit()
    status = tmp_path / 'status.json'
    status.write_text(json.dumps(idle()))
    config = LanePerceptionConfig(root=root_a, overlay=root_a / relative, status_inputs=status,
                                  model_check=lambda: 'fixture-model', overlay_check=lambda _: None)
    assert config.set('denoise')['applied'] is True
    accepted = config.overlay.read_bytes()
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    assert (root_b / relative).read_bytes() == accepted
    calls = []

    def fail_first_restart():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('fixture camera restart failed')

    config.root, config.overlay, config.restart = root_b, root_b / relative, fail_first_restart
    with pytest.raises(RuntimeError, match='fixture camera'):
        config.set('threshold')
    assert len(calls) == 2
    first.FirstBootProvisioner(root=root_a).apply(bundle=bundle, hardware_serial=SERIAL)
    assert config.overlay.read_bytes() == (root_a / relative).read_bytes() == accepted


def test_actual_config_changes_and_applied_digest_survive_b_and_return_to_a(tmp_path, monkeypatch):
    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    card_a = _card(root_a, "ap:\n  mode: off\nlogin:\n  boot_code: off\n")
    applied = config_module().apply(root_a, lambda _: "")
    assert applied["state"] == "applied", applied
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    for relative in ("etc/rosy/network-policy.json", "etc/rosy/login-policy.json",
                     "var/lib/rosy/config/applied.json"):
        target = root_b / relative
        assert target.is_file(), f"config owner did not publish {relative} for B"
        assert target.read_bytes() == (root_a / relative).read_bytes()
    _card(root_b, "ap:\n  mode: relay\nlogin:\n  boot_code: operator\n")
    assert config_module().apply(root_b, lambda _: "")["state"] == "applied"
    first.FirstBootProvisioner(root=root_a).apply(bundle=bundle, hardware_serial=SERIAL)
    assert json.loads((root_a / "etc/rosy/network-policy.json").read_text())["mode"] == "relay"
    # The old card file is still present in A: the committed applied digest must be current too.
    assert card_a.exists()
    assert (root_a / "var/lib/rosy/config/applied.json").read_bytes() == (
        root_b / "var/lib/rosy/config/applied.json").read_bytes()
    assert config_module().apply(root_a, lambda _: "")["state"] == "unchanged"


@pytest.mark.parametrize('race', ['geometry', 'movement'])
def test_host_lane_rechecks_snapshot_and_stopped_state_at_publication(tmp_path, monkeypatch, race):
    import contextlib
    import os_state_config
    from host_lane_perception import LanePerceptionConfig
    from test_lane_perception_host import idle

    _, root, _, _, _ = _provision_a(tmp_path, monkeypatch, protocol=2)
    relative = 'etc/rosy/line_observer_overrides.yaml'
    initial = b'/**/line_observer_node:\n  ros__parameters:\n    camera_lane_mode: keep\n    camera_height_m_override: 0.059\n'
    changed = initial.replace(b'0.059', b'0.061')
    publication = os_state_config.configuration_update
    with publication(root) as update:
        update.stage(relative, initial, 0o644)
        update.commit()
    status = tmp_path / 'status.json'
    status.write_text(json.dumps(idle()))

    def overlay_check(_):
        if race == 'geometry':
            with publication(root) as update:
                update.stage(relative, changed, 0o644)
                update.commit()
        return None

    if race == 'movement':
        @contextlib.contextmanager
        def delayed_lock(*args, **kwargs):
            with publication(*args, **kwargs) as update:
                status.write_text(json.dumps({**idle(), 'velocity_linear': 0.1}))
                yield update
        monkeypatch.setattr(os_state_config, 'configuration_update', delayed_lock)
    config = LanePerceptionConfig(root=root, overlay=root / relative, status_inputs=status,
                                  model_check=lambda: 'fixture-model', overlay_check=overlay_check)
    with pytest.raises(ValueError, match='changed|moving'):
        config.set('denoise')
    assert config.overlay.read_bytes() == (changed if race == 'geometry' else initial)


def test_config_during_initialization_is_not_overwritten_by_the_first_bundle(tmp_path, monkeypatch):
    root_a, root_b, _, _ = shared_roots(tmp_path, monkeypatch)
    _card(root_a, "ap:\n  mode: off\nlogin:\n  boot_code: off\n")
    assert config_module().apply(root_a, lambda _: "")["state"] == "applied"
    bundle = root_a / "run/rosy-provision-boot/rosy-provision/provision.json"
    bundle.parent.mkdir()
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    first = firstboot_module()
    assert first.FirstBootProvisioner(root=root_a, network_activate=lambda _: True).apply(
        bundle=bundle, hardware_serial=SERIAL)["ok"]
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    path = root_b / "etc/rosy/network-policy.json"
    assert path.is_file(), "initial config must enter the first committed generation"
    assert json.loads(path.read_text())["mode"] == "off"


def test_timezone_is_root_specific_projection_of_the_same_committed_setting(tmp_path, monkeypatch):
    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    for root in (root_a, root_b):
        zone = root / "usr/share/zoneinfo/Asia/Seoul"
        zone.parent.mkdir(parents=True)
        zone.write_bytes(b"TZif synthetic zone payload")
    _card(root_a, "timezone: Asia/Seoul\n")
    assert config_module().apply(root_a, lambda _: "")["state"] == "applied"
    first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)
    target = root_b / "etc/localtime"
    assert target.is_symlink(), "timezone must be projected without running timedatectl on the test host"
    assert target.readlink() == Path("/usr/share/zoneinfo/Asia/Seoul")


def test_card_password_is_not_scrubbed_when_canonical_publication_fails(tmp_path, monkeypatch):
    from test_rosy_config_apply import AP_VALUE, PW

    first, root_a, _, common, _ = _provision_a(tmp_path, monkeypatch)
    card = _card(root_a, f"ap:\n  mode: fallback\n  {PW}: {AP_VALUE}\n")
    previous = (common / "state/current.json").read_bytes()
    state = first._native_helper("os_state_firstboot")

    def interrupted(*_args, **_kwargs):
        raise OSError("modeled publication failure before card scrub")

    monkeypatch.setattr(state.FirstBootState, "stage_generation", interrupted)
    with pytest.raises(OSError, match="modeled publication"):
        config_module().apply(root_a, lambda _: "")
    assert AP_VALUE in card.read_text(), "the only source of a new password must survive failed publication"
    assert (common / "state/current.json").read_bytes() == previous


def test_an_unchanged_config_does_not_rewrite_derived_timezone_files(tmp_path, monkeypatch):
    _, root_a, _, _, _ = _provision_a(tmp_path, monkeypatch)
    _card(root_a, "ap:\n  mode: off\n")
    module = config_module()
    assert module.apply(root_a, lambda _: "")["state"] == "applied"
    paths = [root_a / "etc/localtime", root_a / "etc/timezone"]
    before = [(p.lstat().st_ino, p.lstat().st_mtime_ns, p.lstat().st_ctime_ns) for p in paths]
    assert module.apply(root_a, lambda _: "")["state"] == "unchanged"
    after = [(p.lstat().st_ino, p.lstat().st_mtime_ns, p.lstat().st_ctime_ns) for p in paths]
    assert after == before


def test_initial_configuration_cannot_publish_a_record_larger_than_its_reader_limit(tmp_path, monkeypatch):
    root_a, _, common, _ = shared_roots(tmp_path, monkeypatch)
    module = firstboot_module()._native_helper("os_state_config")
    with pytest.raises(ValueError, match="record exceeds"):
        with module.configuration_update(root_a) as update:
            for path in ("etc/rosy/network-policy.json", "etc/rosy/login-policy.json"):
                update.stage(path, json.dumps({"padding": "x" * 40000}).encode("utf-8"), 0o600)
            update.commit()
    assert not (common / "state/config-initializing.json").exists()
    assert not (root_a / "etc/rosy/network-policy.json").exists()
