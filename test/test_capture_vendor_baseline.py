"""capture-vendor-baseline.sh read-only contract (pre-G0 card A capture).

The script runs on the vendor stock image before any Rosy OS artifact is
trusted (docs/plans/2026-09-21-pinky-device-commissioning-design.md §7). It
must stay strictly read-only: the only writable location is its own evidence
output directory. These tests pin that property so a future edit cannot
silently turn the baseline capture into a system-mutating tool.

ROS-free and host-safe: it inspects the script text only (plus an optional
``bash -n`` syntax check when a bash is reachable from the host).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "deploy" / "robot" / "pinky_pro" / "capture-vendor-baseline.sh"
)

# Tokens that would let the capture mutate the vendor system. Each entry is a
# regex; none of them may occur anywhere in the script (comments included —
# a "documented" mutation is still a mutation).
FORBIDDEN_PATTERNS = [
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\binsmod\b",
    r"\bmodprobe\b",
    r"\brm\s+-",
    r"\bsystemctl\s+(start|stop|restart|enable|disable|mask|kill|isolate)\b",
    r"\bpip3?\s+install\b",
    r"\bapt(?:-get)?\s+(install|remove|purge|upgrade|full-upgrade)\b",
    r"\buser(?:add|mod|del)\b",
    r"\bpasswd\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\btee\b",
    r"\bcrontab\s+-[re]\b",
    r"\bwpa_passphrase\b",  # writes key material; provisioning is NOT this script's job
]


@pytest.fixture(scope="module")
def script_text() -> str:
    assert SCRIPT.is_file(), f"missing script: {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def test_script_declares_read_only_intent(script_text: str) -> None:
    assert script_text.startswith("#!/usr/bin/env bash")
    assert "READ-ONLY" in script_text
    assert "set -u" in script_text
    assert "SHA256SUMS.txt" in script_text  # capture integrity manifest


def test_script_contains_no_mutating_commands(script_text: str) -> None:
    for pattern in FORBIDDEN_PATTERNS:
        hits = re.findall(pattern, script_text)
        assert not hits, f"forbidden pattern {pattern!r} matched {hits!r}"


def test_all_redirections_target_the_evidence_directory(script_text: str) -> None:
    redirects = re.findall(r"(>>?)\s*([^\s|;&)]+)", script_text)
    assert redirects, "expected at least one redirect (the cap helper)"
    for op, target in redirects:
        if target == "&1":  # 2>&1 stderr merge inside cap()
            continue
        assert target.startswith(('"$OUT', "$OUT")), (
            f"redirect {op} {target!r} writes outside the evidence directory"
        )


def test_i2c_probe_is_opt_in_only(script_text: str) -> None:
    lines = script_text.splitlines()
    guard_idx = [
        i for i, line in enumerate(lines) if 'PROBE_I2C:-0' in line and line.startswith("if ")
    ]
    assert guard_idx, "expected an opt-in PROBE_I2C guard for the i2c bus probe"
    probe_lines = [
        i for i, line in enumerate(lines) if "i2cdetect" in line and not line.lstrip().startswith("#")
    ]
    assert probe_lines, "expected the guarded i2cdetect probes to be present"
    fi_lines = [i for i, line in enumerate(lines) if line.strip() == "fi"]
    for probe in probe_lines:
        assert any(g < probe < f for g in guard_idx for f in fi_lines), (
            "i2cdetect must only run inside the PROBE_I2C guard block"
        )


def test_wsl_bash_syntax_check() -> None:
    """Best-effort `bash -n` (WSL bash on Windows, native bash elsewhere)."""
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash on host")
    path = str(SCRIPT)
    # The system32 launcher enters WSL and needs /mnt/<drive>. Git Bash accepts
    # the native Windows path directly, so converting it would point elsewhere.
    if "windows\\system32" in bash.lower() and re.fullmatch(r"[A-Za-z]:\\.*", path):
        drive = path[0].lower()
        path = f"/mnt/{drive}{path[2:].replace(chr(92), '/')}"
    result = subprocess.run(
        [bash, "-n", path], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"bash -n failed: {result.stderr}"
