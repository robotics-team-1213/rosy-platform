"""Windows puller for L2 diagnostics with a card fallback (D-175 Task 5).

``collect-rosy-diagnostics.ps1`` runs ``rosy-diag collect`` over key-only,
BatchMode SSH with a pinned known_hosts file and copies the bundle into
``evidence/<device>/<boot_id>/`` without overwriting. When SSH is unreachable
it copies the FAT32 ``rosy-diag/`` black box off the card without elevation and
points at the elevated ext4 reader for the journal. Fake ``ssh``/``scp``
executables stand in for the device; ``-PrintPlan`` shows the resolved calls.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "robot" / "collect-rosy-diagnostics.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
BOOT_ID = "23fe37a5e32a4462bd07ec95dc392a06"
# /proc/sys/kernel/random/boot_id is a dashed UUID; evidence folders use journald's 32-hex form.
PROC_BOOT_ID = "23fe37a5-e32a-4462-bd07-ec95dc392a06"
BUNDLE = f"rosy-diag-rosy-pinky-e4us-{BOOT_ID[:8]}-20260923T010203Z.tar.gz"
needs_windows_powershell = pytest.mark.skipif(POWERSHELL is None or os.name != "nt",
                                              reason="Windows PowerShell is required")

FAKE_SSH = r'''
import json, os, sys
log = os.environ["FAKE_LOG"]
with open(log, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"tool": "ssh", "argv": sys.argv[1:]}) + "\n")
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "unreachable":
    sys.stderr.write("ssh: connect to host rosy-pinky-e4us.local port 22: Connection timed out\n")
    sys.exit(255)
command = sys.argv[-1]
if "collect" in command:
    print(json.dumps({"bundle": "/tmp/rosy-diag.Ab12Cd/" + os.environ["FAKE_BUNDLE"], "bytes": 6,
                      "boot_id": os.environ["FAKE_BOOT_ID"], "device_name": "rosy-pinky-e4us",
                      "release_id": "2026.09.23-004"}))
sys.exit(0)
'''

FAKE_SCP = r'''
import json, os, sys
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"tool": "scp", "argv": sys.argv[1:]}) + "\n")
with open(sys.argv[-1], "wb") as target:
    target.write(b"bundle")
'''


@pytest.fixture
def case(tmp_path: Path):
    tools = tmp_path / "tools"
    tools.mkdir()
    for name, body in (("ssh", FAKE_SSH), ("scp", FAKE_SCP)):
        (tools / f"fake_{name}.py").write_text(body, encoding="utf-8")
        (tools / f"{name}.cmd").write_text(f'@"{sys.executable}" "%~dp0fake_{name}.py" %*\r\n', encoding="ascii")
    key = tmp_path / "id_ed25519"
    key.write_text("fixture key file\n", encoding="ascii")
    env = {**os.environ, "FAKE_LOG": str(tmp_path / "calls.log"), "FAKE_BUNDLE": BUNDLE, "FAKE_BOOT_ID": PROC_BOOT_ID}
    return {"tmp": tmp_path, "tools": tools, "key": key, "env": env,
            "evidence": tmp_path / "evidence", "known_hosts": tmp_path / "Rosy" / "known_hosts"}


def _run(case, *extra, mode: str = "ok"):
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
               "-Host", "rosy-pinky-e4us.local", "-IdentityFile", str(case["key"]),
               "-EvidenceRoot", str(case["evidence"]), "-KnownHostsFile", str(case["known_hosts"]),
               "-SshExe", str(case["tools"] / "ssh.cmd"), "-ScpExe", str(case["tools"] / "scp.cmd"),
               *map(str, extra)]
    return subprocess.run(command, capture_output=True, text=True, env={**case["env"], "FAKE_MODE": mode})


def _calls(case) -> list[dict]:
    log = Path(case["env"]["FAKE_LOG"])
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


@needs_windows_powershell
def test_print_plan_shows_key_only_batch_ssh_with_a_pinned_host_key(case):
    completed = _run(case, "-PrintPlan")

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    ssh = plan["ssh_arguments"]
    for option in ("BatchMode=yes", "StrictHostKeyChecking=accept-new", "PasswordAuthentication=no",
                   "KbdInteractiveAuthentication=no", "IdentitiesOnly=yes",
                   f"UserKnownHostsFile={case['known_hosts']}"):
        assert option in ssh, option
    assert ssh[ssh.index("-i") + 1] == str(case["key"])
    assert plan["target"] == "rosy@rosy-pinky-e4us.local"
    assert "/opt/rosy/native-runtime/rosy-diag collect --out" in plan["remote_command"]
    assert Path(plan["evidence_root"]) == case["evidence"]
    assert _calls(case) == []  # nothing ran
    assert not case["known_hosts"].exists()


@needs_windows_powershell
def test_the_default_known_hosts_file_lives_under_local_app_data(case):
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
               "-Host", "rosy-pinky-e4us.local", "-IdentityFile", str(case["key"]), "-PrintPlan"]
    completed = subprocess.run(command, capture_output=True, text=True, env=case["env"])

    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    assert Path(plan["known_hosts"]) == Path(os.environ["LOCALAPPDATA"]) / "Rosy" / "known_hosts"


@needs_windows_powershell
def test_a_bundle_lands_under_device_and_boot_id(case):
    completed = _run(case)

    assert completed.returncode == 0, completed.stderr
    target = case["evidence"] / "rosy-pinky-e4us" / BOOT_ID / BUNDLE
    assert target.read_bytes() == b"bundle"
    assert str(target) in completed.stdout
    calls = _calls(case)
    assert [call["tool"] for call in calls] == ["ssh", "scp", "ssh"]
    assert calls[1]["argv"][-2] == f"rosy@rosy-pinky-e4us.local:/tmp/rosy-diag.Ab12Cd/{BUNDLE}"
    assert calls[2]["argv"][-1] == "rm -rf /tmp/rosy-diag.Ab12Cd"
    for call in calls:
        assert "BatchMode=yes" in call["argv"]
        assert f"UserKnownHostsFile={case['known_hosts']}" in call["argv"]
    assert case["known_hosts"].parent.is_dir()


@needs_windows_powershell
def test_an_existing_bundle_is_never_overwritten(case):
    target = case["evidence"] / "rosy-pinky-e4us" / BOOT_ID / BUNDLE
    target.parent.mkdir(parents=True)
    target.write_bytes(b"earlier")

    completed = _run(case)

    assert completed.returncode != 0
    assert "will not overwrite" in completed.stderr
    assert target.read_bytes() == b"earlier"
    assert [call["tool"] for call in _calls(case)] == ["ssh", "ssh"]  # collect, then remote cleanup only


@needs_windows_powershell
def test_unreachable_ssh_without_a_card_fails_with_the_card_hint(case):
    completed = _run(case, mode="unreachable")

    assert completed.returncode != 0
    assert "-CardDisk" in completed.stderr


@needs_windows_powershell
def test_unreachable_ssh_falls_back_to_the_card_black_box_only(case):
    card = case["tmp"] / "card"
    (card / "rosy-diag").mkdir(parents=True)
    (card / "rosy-diag" / "latest.txt").write_text(
        "ROSY boot black box\ndevice:   rosy-pinky-e4us\nstage:    FAILED: rosy-release-recover\n"
        f"boot_id:  {PROC_BOOT_ID}\n", encoding="utf-8")
    (card / "rosy-diag" / "boot-000001-23fe37a5.json").write_text("{}", encoding="utf-8")
    (card / "rosy-provision").mkdir()
    (card / "rosy-provision" / "provision.json").write_text("{}", encoding="utf-8")

    completed = _run(case, "-CardDisk", "000000000207", "-CardBootPath", card, mode="unreachable")

    assert completed.returncode == 0, completed.stderr
    copied = case["evidence"] / "rosy-pinky-e4us" / BOOT_ID / "card-rosy-diag"
    assert (copied / "latest.txt").is_file()
    assert (copied / "boot-000001-23fe37a5.json").is_file()
    assert not list(case["evidence"].rglob("provision.json"))
    assert "read-card-diagnostics.py" in completed.stdout
    assert "administrator" in completed.stdout

    again = _run(case, "-CardDisk", "000000000207", "-CardBootPath", card, mode="unreachable")
    assert again.returncode != 0
    assert "will not overwrite" in again.stderr


def test_the_script_never_weakens_host_keys_or_elevates():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "StrictHostKeyChecking=no" not in text
    assert "UserKnownHostsFile=/dev/null" not in text and "UserKnownHostsFile=NUL" not in text
    assert "-Verb RunAs" not in text
    assert "sshpass" not in text.lower()
    assert "Get-Disk" in text and "SerialNumber" in text  # the card is found by serial
    assert "rosy-provision" not in text.replace("never rosy-provision", "")
    assert text.isascii()  # Windows PowerShell 5.1 reads BOM-less scripts as ANSI
