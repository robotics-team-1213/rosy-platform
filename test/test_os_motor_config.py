"""Run the actual commissioning writer/rollback over modeled A/B device roots."""
import base64
import json
from pathlib import Path
import re

import pytest

from test_os_first_boot_state import SERIAL, _provision_a

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/robot/pinky_pro/native"
SCRIPT = ROOT / "deploy/robot/pinky_pro/sd/enable-motor-commissioning.ps1"


def _run_block(name, root, uid, backup):
    source = re.search(r"\$" + name + r" = @'\n(.*?)\n'@", SCRIPT.read_text(), re.S).group(1)
    source = source.replace("__UID__", uid).replace("__BACKUP__", base64.b64encode(backup).decode())
    source = source.replace("Path('/etc/rosy/runtime.env')", repr(root / "etc/rosy/runtime.env"))
    source = source.replace("Path('/')", repr(root))
    source = source.replace("'/opt/rosy/native-runtime'", repr(str(NATIVE)))
    exec(compile(source, str(SCRIPT) + ":" + name, "exec"), {"PosixPath": type(root)})


@pytest.mark.parametrize("restore", [False, True])
def test_commissioning_enable_and_rollback_survive_slot_change(tmp_path, monkeypatch, restore):
    first, root_a, root_b, _, bundle = _provision_a(tmp_path, monkeypatch)
    original = (root_a / "etc/rosy/runtime.env").read_bytes()
    identity = json.loads((root_a / "etc/rosy/device-identity.json").read_text())
    _run_block("edit", root_a, identity["device_uid"], original)
    enabled = (root_a / "etc/rosy/runtime.env").read_bytes()
    assert b"ROSY_RUNTIME_MODE=motor\n" in enabled
    if restore:
        _run_block("restore", root_a, identity["device_uid"], original)
    expected = original if restore else enabled
    assert first.FirstBootProvisioner(root=root_b).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    assert (root_b / "etc/rosy/runtime.env").read_bytes() == expected
    assert first.FirstBootProvisioner(root=root_a).apply(bundle=bundle, hardware_serial=SERIAL)["ok"]
    assert (root_a / "etc/rosy/runtime.env").read_bytes() == expected


def test_commissioning_rollback_refuses_to_erase_a_later_runtime_change(tmp_path, monkeypatch):
    first, root, _, common, _ = _provision_a(tmp_path, monkeypatch)
    target = root / "etc/rosy/runtime.env"
    original = target.read_bytes()
    uid = json.loads((root / "etc/rosy/device-identity.json").read_text())["device_uid"]
    _run_block("edit", root, uid, original)
    enabled = target.read_bytes()
    later = enabled + b"ROSY_API_TLS=required\n"
    first._native_helper("os_state_config").commit_runtime(root, later, expected=enabled)
    pointer = (common / "state/current.json").read_bytes()
    with pytest.raises(SystemExit, match="runtime changed before rollback"):
        _run_block("restore", root, uid, original)
    assert target.read_bytes() == later
    assert (common / "state/current.json").read_bytes() == pointer


def test_stale_runtime_publication_does_not_replace_the_current_generation(tmp_path, monkeypatch):
    first, root, _, common, _ = _provision_a(tmp_path, monkeypatch)
    original = (root / "etc/rosy/runtime.env").read_bytes()
    writer = first._native_helper("os_state_config")
    writer.commit_runtime(root, original + b"ROSY_API_TLS=required\n", expected=original)
    pointer = (common / "state/current.json").read_bytes()
    with pytest.raises(ValueError, match="runtime changed before publication"):
        writer.commit_runtime(root, original, expected=original)
    assert (common / "state/current.json").read_bytes() == pointer


def test_legacy_commissioning_keeps_its_existing_write_and_restore_path(tmp_path):
    target = tmp_path / "etc/rosy/runtime.env"
    target.parent.mkdir(parents=True)
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc/cmdline").write_text("root=LABEL=writable\n")
    original = b"ROSY_DEVICE_UID=fixture-uid\nROSY_RUNTIME_MODE=core\n"
    target.write_bytes(original)
    _run_block("edit", tmp_path, "fixture-uid", original)
    assert b"ROSY_IO_DRIVE_ENABLED=true\n" in target.read_bytes()
    _run_block("restore", tmp_path, "fixture-uid", original)
    assert target.read_bytes() == original
