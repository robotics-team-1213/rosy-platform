"""Operator entry point for writing one reviewed plan to its card (D-173).

Release 004 was written through ad-hoc wrappers that pinned a disk number,
hand-assembled every path and renamed attempt logs by hand. The entry point
derives everything from the reviewed plan and the release directory, finds the
card by serial, elevates itself and keeps every attempt's log.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "sd" / "write-card.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
RELEASE = "2026.09.23-004"


@pytest.fixture
def case(tmp_path: Path):
    release = tmp_path / "release"
    release.mkdir()
    (release / f"rosy-os-pinky-pro-{RELEASE}-arm64.img.xz").write_bytes(b"fixture")
    (release / "SHA256SUMS.sig").write_text("sig\n", encoding="ascii")
    evidence = tmp_path / "cards"
    evidence.mkdir()
    plan = evidence / "plan.json"
    plan.write_text(json.dumps({
        "mode": "PLAN_ONLY", "release_id": RELEASE, "image_sha256": "a" * 64,
        "device_name": "rosy-pinky-e4us", "disk_serial": "000000000207", "disk_number": 2,
        "registry_path": str(tmp_path / "registry.json"),
    }), encoding="utf-8")
    return {"release": release, "evidence": evidence, "plan": plan, "tmp": tmp_path}


def _print(case, *extra):
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
               "-PlanPath", str(case["plan"]), "-ReleaseDir", str(case["release"]),
               "-WifiProfile", "site-default", "-PrintArguments", *map(str, extra)]
    return subprocess.run(command, capture_output=True, text=True)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_everything_is_derived_from_the_plan_and_the_release(case):
    completed = _print(case)

    assert completed.returncode == 0, completed.stderr
    resolved = json.loads(completed.stdout)
    arguments = resolved["arguments"]
    assert arguments["DiskSerial"] == "000000000207"
    assert "DiskNumber" not in arguments
    assert Path(arguments["ImagePath"]).name == f"rosy-os-pinky-pro-{RELEASE}-arm64.img.xz"
    assert arguments["ImageSha256"] == "a" * 64
    assert arguments["ReleaseId"] == RELEASE
    assert Path(arguments["ImageSignaturePath"]).name == "SHA256SUMS.sig"
    assert Path(arguments["ReleasePublicKey"]).name == "rosy-release-2026-01.pem"
    assert Path(arguments["RegistryJson"]) == case["tmp"] / "registry.json"
    assert Path(arguments["ReceiptPath"]) == case["evidence"] / f"receipt-{RELEASE}-rosy-pinky-e4us.json"
    assert Path(arguments["PlanPath"]) == case["plan"]
    assert "Confirmation" not in arguments  # typed by the operator in the elevated window
    log = Path(resolved["log"])
    assert log.parent == case["evidence"]
    assert log.name.startswith(f"write-{RELEASE}-rosy-pinky-e4us-") and log.suffix == ".log"
    assert resolved["exit_marker"] == str(log) + ".exit"
    # D-181: the stage file sits next to the log and the writer gets its path.
    assert resolved["progress"] == str(log) + ".progress.jsonl"
    assert arguments["ProgressPath"] == resolved["progress"]
    assert arguments["WriterStallMinutes"] == 5
    assert "ResumeAfterWrite" not in arguments


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_resume_after_write_and_the_stall_limit_are_passed_through(case):
    completed = _print(case, "-ResumeAfterWrite", "-WriterStallMinutes", "7.5")

    assert completed.returncode == 0, completed.stderr
    arguments = json.loads(completed.stdout)["arguments"]
    assert arguments["ResumeAfterWrite"] is True
    assert arguments["WriterStallMinutes"] == 7.5


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_resume_after_write_still_refuses_an_existing_receipt(case):
    (case["evidence"] / f"receipt-{RELEASE}-rosy-pinky-e4us.json").write_text("{}", encoding="utf-8")

    completed = _print(case, "-ResumeAfterWrite")

    assert completed.returncode != 0
    assert "receipt already exists" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_optional_operator_key_and_reprovision_receipt_are_passed_through(case):
    key = case["evidence"] / "operator.pub"
    key.write_text("ssh-ed25519 AAAA test\n", encoding="ascii")
    prior = case["evidence"] / "receipt-old.json"
    prior.write_text("{}", encoding="utf-8")

    completed = _print(case, "-OperatorPublicKey", key, "-ReprovisionReceipt", prior)

    assert completed.returncode == 0, completed.stderr
    arguments = json.loads(completed.stdout)["arguments"]
    assert Path(arguments["OperatorPublicKey"]) == key
    assert Path(arguments["ReprovisionReceipt"]) == prior


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_an_existing_receipt_stops_before_anything_else(case):
    (case["evidence"] / f"receipt-{RELEASE}-rosy-pinky-e4us.json").write_text("{}", encoding="utf-8")

    completed = _print(case)

    assert completed.returncode != 0
    assert "receipt already exists" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_release_directory_without_the_plans_image_is_refused(case):
    (case["release"] / f"rosy-os-pinky-pro-{RELEASE}-arm64.img.xz").unlink()

    completed = _print(case)

    assert completed.returncode != 0
    assert "image for release" in completed.stderr


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_only_a_plan_only_plan_is_accepted(case):
    plan = json.loads(case["plan"].read_text(encoding="utf-8"))
    plan["mode"] = "WRITE"
    case["plan"].write_text(json.dumps(plan), encoding="utf-8")

    completed = _print(case)

    assert completed.returncode != 0
    assert "PLAN_ONLY" in completed.stderr


def test_the_entry_point_elevates_itself_and_keeps_every_attempt():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "-Verb RunAs" in text
    assert "Start-Transcript" in text
    assert "prepare-rosy-sd.ps1" in text
    assert "-DiskNumber" not in text  # the card is found by serial
    assert "Get-Date -Format" in text  # one log per attempt, never renamed by hand


def test_the_operator_is_told_where_progress_is_and_what_state_a_lost_write_left():
    # D-181: release 005's elevated write vanished and its transcript sat at its header.
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'Write-Output "Progress: $progressPath' in text
    assert '$forward += "-ResumeAfterWrite"' in text
    assert "UAC prompt declined or timed out" in text
    assert "last stage=$($last.stage) card_state=$($last.card_state)" in text
