"""Physical recovery trust pages retain every fingerprint digit and hide stale codes."""
import importlib
import json
import os
from pathlib import Path

import pytest

from test_rosy_face import _display, _info_screen, _loop, _status

NATIVE = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"
PIN = "0123456789ABCDEF" * 4


@pytest.fixture
def display(monkeypatch):
    monkeypatch.syspath_prepend(str(NATIVE))
    module = importlib.import_module("recovery_display")
    monkeypatch.setattr(module, "OWNER_UID", os.getuid())
    return module


@pytest.fixture
def handoff(tmp_path, display):
    path = tmp_path / "run/rosy-boot/recovery-display.txt"
    path.parent.mkdir(parents=True)
    text = ("DEVICE=rosy-pinky-e4us\nURL=https://10.42.0.1:8443\nCODE=ABCD-2345\n"
            + "SHA256=" + ":".join(PIN[index:index + 2] for index in range(0, 64, 2))
            + "\nEXPIRES_MONOTONIC=1600\nBOOT_ID=boot-1\nAP_EPOCH=ap-1\n")
    path.write_text(text)
    path.chmod(0o640)
    boot = tmp_path / "proc/sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text("boot-1\n")
    view = {"device_name": "rosy-pinky-e4us", "stage": "FAILED:rosy-first-boot",
            "network": {"mode": "ap", "address": "10.42.0.1", "epoch": "ap-1"}}
    return tmp_path, path, text, view


def test_three_five_second_phases_keep_code_fingerprint_and_original_ap_card(display, handoff):
    root, _, _, view = handoff
    code = display.read_page(root, view, 1000)
    fingerprint = display.read_page(root, view, 1005)
    assert code["title"] == "Wi-Fi recovery 1/3"
    assert "ABCD-2345" in " ".join(code["lines"])
    assert "https://10.42.0.1:8443" in code["lines"]
    assert "Compare SHA256 first" in code["lines"]
    assert fingerprint["title"] == "SHA256 2/3"
    assert "".join(fingerprint["lines"]) == PIN
    assert len(fingerprint["lines"]) == 4 and all(len(line) == 16 for line in fingerprint["lines"])
    assert display.read_page(root, view, 1010) is None
    assert display.read_page(root, view, 1015) == code
    assert all(len(page["lines"]) <= 5 for page in (code, fingerprint))


@pytest.mark.parametrize("change", [
    {"stage": "CORE_READY"}, {"stage": "PROVISIONED"}, {"stage": "SETUP"},
    {"device_name": "rosy-pinky-abcd"}, {"network": {"mode": "sta"}},
    {"network": {"mode": "ap", "address": "10.42.0.1", "epoch": "ap-2"}},
    {"network": {"mode": "ap", "address": "10.43.0.1", "epoch": "ap-1"}},
])
def test_display_refuses_stale_or_completed_recovery(display, handoff, change):
    root, _, _, view = handoff
    assert display.read_page(root, dict(view, **change), 1000) is None


@pytest.mark.parametrize("old,new", [
    ("CODE=ABCD-2345", "CODE=ABCD-2345\nCODE=ABCD-2345"),
    ("CODE=ABCD-2345", "CODE=secret-value"), ("EXPIRES_MONOTONIC=1600", "EXPIRES_MONOTONIC=nan"),
    ("EXPIRES_MONOTONIC=1600", "EXPIRES_MONOTONIC=999"),
    ("BOOT_ID=boot-1", "BOOT_ID=boot-old"), ("BOOT_ID=boot-1", "BOOT_ID="),
    ("SHA256=01:23", "SHA256=01"),
])
def test_malformed_and_expired_handoff_is_hidden(display, handoff, old, new):
    root, path, text, view = handoff
    path.write_text(text.replace(old, new))
    assert display.read_page(root, view, 1000) is None


def test_display_refuses_symlink_oversize_and_wrong_permissions(display, handoff):
    root, path, text, view = handoff
    elsewhere = root / "outside"
    elsewhere.write_text(text)
    elsewhere.chmod(0o640)
    path.unlink()
    path.symlink_to(elsewhere)
    assert display.read_page(root, view, 1000) is None
    path.unlink()
    path.write_text(text + "x" * 4096)
    path.chmod(0o640)
    assert display.read_page(root, view, 1000) is None
    path.write_text(text)
    path.chmod(0o666)
    assert display.read_page(root, view, 1000) is None


def test_actual_face_poll_rotates_pages_and_does_not_log_code(display, handoff):
    root, _, _, view = handoff
    module = _display()
    _status(root, view["stage"])
    (root / "run/rosy-boot/network.json").write_text(json.dumps(view["network"]))
    loop, _, clock, _, rendered, logs = _loop(module, root)
    assert loop.step()
    first = rendered[-1]["screen"]
    assert first["row"] == "network_recovery"
    assert first["recovery_page"]["title"] == "Wi-Fi recovery 1/3"
    clock.now += 5
    assert loop.step()
    assert rendered[-1]["screen"]["recovery_page"]["title"] == "SHA256 2/3"
    clock.now += 5
    assert loop.step()
    assert rendered[-1]["screen"]["row"] == "failed"
    assert "recovery_page" not in rendered[-1]["screen"]
    loop.shutting_down = True
    loop.step()
    assert rendered[-1]["screen"]["kind"] == "shutdown"
    assert "ABCD-2345" not in " ".join(logs)


def test_emergency_screen_is_not_replaced_by_recovery(display, handoff, monkeypatch):
    root, _, _, view = handoff
    module = _display()
    loop, _, clock, _, _, _ = _loop(module, root)
    monkeypatch.setattr(loop, "_core", lambda: {"estop": True, "robot_mode": "EMERGENCY"})
    screen = loop.screen_of(dict(view, stage="BOOTING"), clock.now)
    assert screen["kind"] == "stopped"


def test_panel_renderer_keeps_all_hex_digits_without_font_truncation(display, handoff, monkeypatch):
    root, _, _, view = handoff
    module = _display()
    info = _info_screen()
    fit = info._fit
    fitted = []
    def capture(draw, text, size, width):
        result = fit(draw, text, size, width)
        fitted.append((text, result[1]))
        return result
    monkeypatch.setattr(info, "_fit", capture)
    render = module.card_renderer(info)
    for now in (1000, 1005):
        page = display.read_page(root, view, now)
        image = render({"screen": {"kind": "status", "row": "network_recovery", "recovery_page": page}})
        assert image.size == (320, 240)
        assert all(before == after for before, after in fitted)
    assert "".join(text for text, _ in fitted if len(text) == 16 and all(c in "0123456789ABCDEF" for c in text)) == PIN
