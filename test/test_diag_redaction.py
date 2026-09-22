"""Redaction for diagnostics that leave the device (D-175 Task 1).

Fixture secrets are assembled at runtime so this file itself stays clean for the
tracked-file secret scan.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "release"))
from secret_scan import scan_text  # noqa: E402


def _module():
    path = ROOT / "deploy/robot/native/rosy_diag_redact.py"
    spec = importlib.util.spec_from_file_location("rosy_diag_redact", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PSK_VALUE = "site" + "-wifi-" + "pass-9384"
TOKEN_VALUE = "Zk3" + "q9LmT2vXw8" + "Ab7Cd1Ef4Gh6Ij0Kl5Mn8Op3Qr"
PEM = "-----BEGIN " + "PRIVATE KEY-----\nMIIBVQIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7AgEAAkEA\n-----END " + "PRIVATE KEY-----"
SECRET_LINES = [
    "psk=" + PSK_VALUE,
    "wifi_" + "passphrase" + '="' + PSK_VALUE + '"',
    '{"console_token": "' + TOKEN_VALUE + '"}',
    "Authorization: Bearer " + TOKEN_VALUE,
    "ROSY_API_TOKEN=" + TOKEN_VALUE,
    "pairing_credential: " + TOKEN_VALUE,
    "leaked " + TOKEN_VALUE + " in a traceback",
    PEM,
]
KEPT_LINES = [
    "[    7.964660] ubuntu recover-release.sh[504]: ModuleNotFoundError: No module named 'signing'",
    "[    8.017850] ubuntu systemd[1]: Dependency failed for rosy-core.service - ROSY native CORE runtime.",
    "image sha256 eaf843c408b1b5678ec7cb68c57785227a97752077cd91598b41ce8a658afd2c",
    "boot 23fe37a5e32a4462bd07ec95dc392a06 release 2026.09.22-002",
    "Registering new address record for 192.168.1.201 on wlan0.IPv4.",
    "token bucket refilled",
]


@pytest.mark.parametrize("line", SECRET_LINES)
def test_secrets_are_removed_and_pass_the_repository_scanner(line):
    redacted = _module().redact(line)

    assert PSK_VALUE not in redacted
    assert TOKEN_VALUE not in redacted
    assert "MIIBVQIBADAN" not in redacted
    assert "<redacted>" in redacted
    assert scan_text("diag/journal.txt", redacted) == []


@pytest.mark.parametrize("line", KEPT_LINES)
def test_ordinary_journal_lines_survive_unchanged(line):
    assert _module().redact(line) == line


def test_a_multiline_journal_excerpt_keeps_its_shape():
    text = "\n".join(KEPT_LINES + SECRET_LINES) + "\n"

    redacted = _module().redact(text)

    assert redacted.splitlines()[: len(KEPT_LINES)] == KEPT_LINES
    assert scan_text("diag/journal.txt", redacted) == []


@pytest.mark.parametrize(
    "path",
    [
        "/etc/NetworkManager/system-connections/rosy-site-sta.nmconnection",
        "/boot/firmware/rosy-provision/provision.json",
        "/etc/rosy/fleet-bootstrap.json",
        "/etc/ssh/ssh_host_ed25519_key",
        "/var/lib/rosy/console_token.txt",
        "/etc/rosy/api.secret",
    ],
)
def test_secret_bearing_paths_are_never_read(path):
    assert _module().is_denied_path(path)


@pytest.mark.parametrize(
    "path",
    ["/var/lib/rosy/provisioning/state.json", "/etc/rosy/runtime.env", "/etc/hostname",
     "/var/log/journal/x/system.journal"],
)
def test_diagnostic_paths_are_allowed(path):
    assert not _module().is_denied_path(path)


HEX_PSK = "ab" * 32
MORE_SECRET_LINES = [
    # Python repr, the most common shape in tracebacks (review M4).
    "{'wifi_" + "passphrase': '" + PSK_VALUE + "', 'wpa_" + "psk': '" + HEX_PSK + "'}",
    'pass' + 'word: "' + PSK_VALUE + ' with spaces"',
    "https://operator:" + PSK_VALUE + "@fleet.example.invalid/api",
    "nmcli con modify rosy-site-sta wifi-sec." + "psk " + PSK_VALUE,
    "Cookie: session=" + TOKEN_VALUE + "; theme=dark",
    '{"sec' + 'ret":' + "123456789012}",
]


@pytest.mark.parametrize("line", MORE_SECRET_LINES)
def test_more_secret_shapes_are_removed(line):
    redacted = _module().redact(line)

    for secret in (PSK_VALUE, TOKEN_VALUE, HEX_PSK, "123456789012", "with spaces"):
        assert secret not in redacted, redacted
    assert scan_text("diag/journal.txt", redacted) == []


@pytest.mark.parametrize("line", ["a." * 24000, "-" * 48000, "x_" * 24000 + "token"],
                         ids=["dotted", "dashes", "word-run"])
def test_long_lines_redact_in_linear_time(line):
    import time

    started = time.perf_counter()
    _module().redact(line)

    assert time.perf_counter() - started < 1.0
