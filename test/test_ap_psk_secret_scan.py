"""The readable AP passphrase and its Wi-Fi QR payload are still secrets to the scanner.

Samples are generated or assembled at runtime so the tracked-file scan
(test_release_boundary_guards) sees no literal: the scheme and the P: field
of a QR payload never share a source line here.
"""

from __future__ import annotations

from network import generate_setup_psk  # via test/conftest.py
from secret_scan import scan_text  # via test/conftest.py

PW = "pass" + "word"
WPA = "p" + "sk"
QR_HEAD = "WIFI" + ":"


def _kinds(text: str) -> list[str]:
    return [finding.kind for finding in scan_text("planted.txt", text)]


def test_a_generated_passphrase_assigned_to_a_secret_name_is_reported():
    value = generate_setup_psk()

    assert _kinds(f'ap_{PW} = "{value}"') == ["credential"]
    assert _kinds(f"  {PW}: '{value}'") == ["credential"]
    assert _kinds(f"{WPA}={value}") == ["wifi-psk"]


def test_a_wifi_qr_payload_is_reported():
    value = generate_setup_psk()

    assert _kinds(QR_HEAD + f"T:WPA;S:rosy-pinky-e4us;P:{value};;") == ["wifi-qr"]
    # Escaped separators inside the passphrase still count.
    assert _kinds(QR_HEAD + "S:lab\\;net;T:WPA;P:ab\\;cdefgh;;") == ["wifi-qr"]


def test_a_documented_qr_shape_is_a_placeholder():
    assert _kinds(QR_HEAD + "T:WPA;S:<ssid>;P:<psk>;;") == []
