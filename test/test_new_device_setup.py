"""Moved SD cards expose a setup-only LAN page while CORE stays gated."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
FIRST_BOOT = ROOT / "deploy/image/first-boot"


def _module():
    path = FIRST_BOOT / "rosy-new-device-setup.py"
    spec = importlib.util.spec_from_file_location("rosy_new_device_setup", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setup_page_is_read_only_and_operational_api_stays_unavailable(tmp_path):
    module = _module()
    status = tmp_path / "boot-status.json"
    status.write_text(json.dumps({
        "stage": "SETUP",
        "device_name": "rosy-pinky-k7m4",
        "ipv4": ["192.0.2.10"],
    }), encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.handler(status))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/dashboard", timeout=2) as response:
            body = response.read().decode()
            assert response.status == 200
            assert "rosy-pinky-k7m4" in body
            assert "registration" in body.lower()
            assert response.headers["Cache-Control"] == "no-store"
            assert "192.0.2.10" not in body
        for path in ("/api/v1", "/api/v1/robot/state"):
            try:
                urlopen(base + path, timeout=2)
            except HTTPError as exc:
                assert exc.code == 503
                assert json.loads(exc.read())["state"] == "NEW_DEVICE_SETUP"
            else:
                raise AssertionError(f"{path} must not look like a working CORE API")
        try:
            urlopen(Request(base + "/dashboard", method="POST", data=b"x"), timeout=2)
        except HTTPError as exc:
            assert exc.code == 405
        else:
            raise AssertionError("setup page must not accept changes")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_setup_server_requires_setup_state_and_keeps_old_identity_private(tmp_path):
    module = _module()
    status = tmp_path / "boot-status.json"
    status.write_text(json.dumps({
        "stage": "FAILED:rosy-first-boot",
        "device_name": "<script>alert(1)</script>",
        "prior_device_uid": "old-device-secret",
    }), encoding="utf-8")
    code, _headers, body = module.response("/dashboard", status)
    assert code == 503
    assert b"old-device-secret" not in body
    assert b"<script>" not in body


def test_setup_server_starts_only_for_a_moved_card_and_is_in_the_image():
    first_boot_unit = (FIRST_BOOT / "rosy-first-boot.service").read_text(encoding="utf-8")
    setup_unit = (FIRST_BOOT / "rosy-new-device-setup.service").read_text(encoding="utf-8")
    payload = (ROOT / "deploy/image/build-native-payload.sh").read_text(encoding="utf-8")
    customizer = (ROOT / "deploy/image/customize-rootfs.sh").read_text(encoding="utf-8")
    assert "OnFailure=rosy-new-device-setup.service" in first_boot_unit
    assert "ConditionPathExists=/var/lib/rosy/provisioning/new-device-setup.json" in setup_unit
    assert "User=rosy" in setup_unit
    assert "rosy-new-device-setup.service" in payload
    assert "rosy-new-device-setup.py" in setup_unit
    assert 'chroot "$ROOT" python3 -B /opt/rosy/first-boot/rosy-new-device-setup.py --help' in customizer
