"""Run the actual commissioning writer/rollback over modeled A/B device roots."""
import base64
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
    identity = __import__("json").loads((root_a / "etc/rosy/device-identity.json").read_text())
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
