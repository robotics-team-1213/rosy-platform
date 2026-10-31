"""LOCAL native dispatch captures, without ROS, SPI, live credentials or devices."""

import importlib.util
import os
from pathlib import Path

from PIL import Image
import pytest

from emotion import info_screen as I


@pytest.mark.skipif(not os.environ.get("ROSY_FACE_CAPTURE_DIR"), reason="opt-in LOCAL LCD captures")
def test_native_dispatch_cards_and_panel_packing():
    root = Path(__file__).resolve().parents[4]
    path = root / "deploy/robot/pinky_pro/native/face_card_renderer.py"
    spec = importlib.util.spec_from_file_location("lcd_capture_consumer", path)
    consumer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(consumer)
    render = consumer.card_renderer(I)
    base = {"device_name": "fixture", "release_id": "fixture-release", "ipv4": ["192.0.2.7"],
            "battery_percent": 73, "battery_voltage": 12.1, "network": {"mode": "sta"}}
    ap_key = "fixture-" + "ap-key"
    ap = {**base, "stage": "CORE_READY", "network": {"mode": "ap", "ssid": "RosyFixture", "address": "192.0.2.1"},
          "ap_login": ap_key}
    cases = {
        "boot-bright": {**base, "stage": "BOOTING", "frame": 0},
        "boot-dim": {**base, "stage": "BOOTING", "frame": 1},
        "ready": {**base, "stage": "CORE_READY", "state_line": "Ready", "todo": "Select this robot"},
        "failed": {**base, "stage": "FAILED", "failed_unit": "fixture-long-failed-service-name.service"},
        "provisioned": {**base, "stage": "PROVISIONED", "detail": "fixture-detail-" * 8},
        "ap-qr": ap,
        "ap-text-fallback": {**ap, "network": {**ap["network"], "ssid": "s" * 32}, "ap_login": "k" * 63},
        "stopped": {**base, "screen": {"kind": "stopped", "cause": "Operator confirmation required", "release": "Release only after checking"}},
        "stopped-long": {**base, "device_name": "fixture-name-" * 8, "screen": {"kind": "stopped", "cause": "fixture-cause-" * 8, "release": "fixture-release-" * 8}},
        "update-bright": {**base, "screen": {"kind": "update", "release": "fixture-next-release"}},
        "update-dim": {**base, "frame": 1, "screen": {"kind": "update", "release": "fixture-next-release"}},
        "shutdown": {**base, "screen": {"kind": "shutdown"}},
        "recovery": {**base, "screen": {"row": "network_recovery", "recovery_page": {"title": "Network recovery", "lines": ["Connect to the robot AP", "Open the operator page", "Wait for connection"]}}},
        "peer": {**base, "screen": {"row": "peer_request", "peer": {"requests": [
            {"display_code": "2345", "approval_code": "234567"},
            {"display_code": "6789", "approval_code": "6789AB"},
            {"display_code": "ABCD", "approval_code": "ABCDEF"}], "tls_ca_sha256": "123456789abcdef0" * 4}}},
        "light": {**base, "screen": {"kind": "light"}},
    }
    for level, value in [("ok", 73), ("caution", 30), ("danger", 15), ("ok", None)]:
        cases[f"bar-{level}-{value}"] = {"screen": {"kind": "face", "overlay": {"payload": {"kind": "drive", "mode": "MANUAL"}}},
                                       "bar": ("fixture-status-" * 8, level, value, False)}
    out = Path(os.environ["ROSY_FACE_CAPTURE_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    for name, payload in cases.items():
        image = render(payload)
        assert image.size == (320, 240) and image.mode == "RGB", name
        assert any(low != high for low, high in image.getextrema()), name
        packed = I.to_panel(image)
        assert packed.shape == (320, 240, 2) and str(packed.dtype) == "uint8", name
        image.save(out / f"native-{name}.png")
    assert I.ap_qr(cases["ap-qr"]) is not None
    assert I.ap_qr(cases["ap-text-fallback"]) is None
    white = I._QR_LIGHT
    assert white in set(Image.open(out / "native-ap-qr.png").getdata())
    assert white not in set(Image.open(out / "native-ap-text-fallback.png").getdata())
