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
    # D-187: the stage file sits next to the log and the writer gets its path.
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
    # D-187: release 005's elevated write vanished and its transcript sat at its header.
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'Write-Output "Progress: $progressPath' in text
    assert '$forward += "-ResumeAfterWrite"' in text
    assert "UAC prompt declined or timed out" in text
    assert "last stage=$($last.stage) card_state=$($last.card_state)" in text


# --- D-188: detached launch, UAC failure, status command --------------------
# Release 005: a write launched from an agent session vanished with it, a
# declined UAC prompt left no trace, and nothing measured progress, so the
# operating agent repeatedly gave wrong completion times.

import time
from datetime import datetime, timedelta, timezone

STATUS = ROOT / "deploy" / "sd" / "card-write-status.ps1"

FAKE_LAUNCHER = r'''param([string[]]$ArgumentList, [switch]$Elevate, [switch]$Wait)
$record = [ordered]@{ arguments = @($ArgumentList); elevate = [bool]$Elevate; wait = [bool]$Wait }
$record | ConvertTo-Json -Compress | Set-Content -LiteralPath "{record}" -Encoding UTF8
if ("{mode}" -eq "decline") { throw "The operation was canceled by the user." }
# A launcher asked to wait would sit here as long as the write window is open.
if ($Wait) { Start-Sleep -Seconds 60 }
'''


def _launcher(case, mode):
    record = case["tmp"] / f"launch-{mode}.json"
    script = case["tmp"] / f"fake-launcher-{mode}.ps1"
    script.write_text(FAKE_LAUNCHER.replace("{record}", str(record)).replace("{mode}", mode), encoding="utf-8")
    return script, record


def _launch(case, launcher, *extra):
    log = case["evidence"] / "write-attempt.log"
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
               "-PlanPath", str(case["plan"]), "-ReleaseDir", str(case["release"]),
               "-WifiProfile", "site-default", "-LogPath", str(log),
               "-ElevationLauncher", str(launcher), *map(str, extra)]
    started = time.monotonic()
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    return completed, time.monotonic() - started, log


def _progress_lines(log):
    path = Path(str(log) + ".progress.jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_detach_starts_one_window_and_returns_at_once(case):
    launcher, record = _launcher(case, "accept")

    completed, elapsed, log = _launch(case, launcher, "-Detach", "-ReadbackStallMinutes", "7", "-AcceptSlowMedia")

    assert completed.returncode == 0, completed.stderr
    assert elapsed < 45, "the launcher waited for the write window"
    launched = json.loads(record.read_text(encoding="utf-8-sig"))
    assert launched["wait"] is False
    arguments = launched["arguments"]
    assert arguments[0] == "-NoExit"  # the window stays open with its result
    assert "-Detach" not in arguments  # the window runs the write itself
    assert f'"{log}"' in arguments
    assert arguments[arguments.index("-ReadbackStallMinutes") + 1] == "7"
    assert "-AcceptSlowMedia" in arguments
    for label in ("Log: ", "Progress: ", "Exit marker: ", "Status: "):
        assert label in completed.stdout
    assert "card-write-status.ps1" in completed.stdout and f'-LogPath "{log}"' in completed.stdout
    # The launcher creates the progress file as the operator, before elevation.
    lines = _progress_lines(log)
    assert (lines[0]["stage"], lines[0]["card_state"]) == ("launch", "untouched")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_declined_uac_prompt_is_recorded_as_untouched(case):
    launcher, _record = _launcher(case, "decline")

    completed, _elapsed, log = _launch(case, launcher, "-Detach")

    assert completed.returncode != 0
    rendered = " ".join(completed.stderr.split())
    assert "UAC prompt declined or timed out" in rendered
    assert "card_state=untouched" in rendered and "next: re-run and approve the UAC prompt" in rendered
    failed = _progress_lines(log)[-1]
    assert (failed["stage"], failed["card_state"]) == ("failed", "untouched")
    assert "re-run and approve the UAC prompt" in failed["next"]
    assert "canceled by the user" in failed["detail"]


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_the_new_limits_are_passed_to_the_writer(case):
    completed = _print(case, "-ReadbackStallMinutes", "8", "-MinReadMBps", "12", "-AssumedWriteMBps", "9",
                       "-AcceptSlowMedia")

    assert completed.returncode == 0, completed.stderr
    resolved = json.loads(completed.stdout)
    arguments = resolved["arguments"]
    assert (arguments["ReadbackStallMinutes"], arguments["MinReadMBps"], arguments["AssumedWriteMBps"]) == (8, 12, 9)
    assert arguments["AcceptSlowMedia"] is True
    assert resolved["status"].endswith(f'-LogPath "{resolved["log"]}"')


# --- the status command -----------------------------------------------------

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
RAW = 8_170_000_000  # release 005 raw image size


def _ts(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def _preflight(minutes_ago):
    return [
        {"ts": _ts(minutes_ago), "stage": "preflight", "card_state": "untouched"},
        {"ts": _ts(minutes_ago), "stage": "preflight", "card_state": "untouched", "detail": "measured",
         "read_mbps": 20.0, "raw_bytes": RAW, "assumed_write_mbps": 16.0, "assumed_readback_mbps": 20.0,
         "predicted_write_seconds": 511, "predicted_readback_seconds": 409, "predicted_total_seconds": 920,
         "min_read_mbps": 10},
    ]


def _status(tmp_path, lines, *extra, exit_code=None):
    log = tmp_path / "write.log"
    Path(str(log) + ".progress.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    if exit_code is not None:
        Path(str(log) + ".exit").write_text(f"{exit_code}\n", encoding="ascii")
    base = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(STATUS),
            "-LogPath", str(log), "-NowUtc", NOW.isoformat(), *map(str, extra)]
    text = subprocess.run(base, capture_output=True, text=True)
    as_json = subprocess.run(base + ["-Json"], capture_output=True, text=True)
    assert text.returncode == 0, text.stderr
    assert as_json.returncode == 0, as_json.stderr
    return " ".join(text.stdout.split()), json.loads(as_json.stdout)


def _readback_in_progress(last_beat_minutes_ago=1):
    lines = [{"ts": _ts(30), "stage": "launch", "card_state": "untouched"},
             {"ts": _ts(29), "stage": "verify-signature", "card_state": "untouched"},
             {"ts": _ts(28), "stage": "select-disk", "card_state": "untouched"},
             *_preflight(28),
             {"ts": _ts(27), "stage": "confirm", "card_state": "untouched"},
             {"ts": _ts(26), "stage": "write", "card_state": "writing", "total": RAW},
             {"ts": _ts(12), "stage": "readback", "card_state": "written-unverified", "total": RAW}]
    # 10 MB/s: 600 MB per minute, one heartbeat a minute.
    for minute in range(1, 12):
        at = 12 - minute
        if at < last_beat_minutes_ago:
            break
        lines.append({"ts": _ts(at), "stage": "readback", "card_state": "written-unverified",
                      "detail": "heartbeat", "bytes": minute * 600_000_000})
    return lines


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_status_of_a_readback_in_progress_gives_the_rate_and_an_eta(tmp_path):
    text, status = _status(tmp_path, _readback_in_progress())

    assert status["result"] == "in-progress" and status["stage"] == "readback"
    assert status["card_state"] == "written-unverified"
    assert status["bytes_total"] == RAW and status["bytes_done"] == 11 * 600_000_000
    assert status["rate_mbps"] == 10.0  # 600 MB per minute
    remaining = (RAW - status["bytes_done"]) / 1e6 / 10.0
    assert abs(status["stage_eta_seconds"] - remaining) <= 1
    assert status["job_eta_seconds"] == status["stage_eta_seconds"]
    assert status["last_heartbeat_age_seconds"] == 60
    assert status["stalled"] is False
    assert status["preflight"]["read_mbps"] == 20.0
    assert "Stage: readback" in text and "Rate: 10.0 MB/s" in text
    assert "ETA this stage:" in text and "ETA whole job:" in text
    assert "STALLED" not in text


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_status_during_the_write_adds_the_predicted_readback(tmp_path):
    lines = _readback_in_progress()[:7]  # up to and including the write stage line
    for minute in range(1, 6):
        lines.append({"ts": _ts(26 - minute), "stage": "write", "card_state": "writing",
                      "detail": "heartbeat", "bytes": minute * 900_000_000})  # 15 MB/s
    _text, status = _status(tmp_path, lines)

    assert status["stage"] == "write" and status["rate_mbps"] == 15.0
    readback = RAW / 1e6 / 20.0  # at the pre-flight read rate
    assert abs(status["job_eta_seconds"] - (status["stage_eta_seconds"] + readback)) <= 2


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_status_says_stalled_when_the_bytes_stop_rising(tmp_path):
    lines = _readback_in_progress(last_beat_minutes_ago=9)

    text, status = _status(tmp_path, lines)

    assert status["stalled"] is True
    assert "no new bytes in the readback stage" in status["stall_reason"]
    assert "-ResumeAfterWrite" in status["next"]
    assert "STALLED:" in text and "next:" in text


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_status_of_a_failed_write_shows_the_reason_and_the_next_step(tmp_path):
    lines = _readback_in_progress() + [{
        "ts": _ts(0.5), "stage": "failed", "card_state": "written-unverified", "kind": "io",
        "detail": "readback: the card could not be read during readback (stalled, kind io)",
        "next": "reinsert the card (or use another reader), then re-run the same command with -ResumeAfterWrite"}]

    text, status = _status(tmp_path, lines, exit_code=1)

    assert status["result"] == "failed" and status["exit_code"] == 1
    assert status["stalled"] is False and status["job_eta_seconds"] is None
    assert status["next"].startswith("reinsert the card")
    assert "Result: FAILED" in text and "next: reinsert the card" in text


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_status_of_a_finished_write(tmp_path):
    lines = _readback_in_progress() + [
        {"ts": _ts(0.9), "stage": "bundle", "card_state": "verified-no-bundle"},
        {"ts": _ts(0.8), "stage": "bundle-writing", "card_state": "bundle-partial"},
        {"ts": _ts(0.7), "stage": "receipt", "card_state": "complete"},
        {"ts": _ts(0.6), "stage": "done", "card_state": "complete",
         "next": "the card is ready: put it in the Pinky and power on"}]

    text, status = _status(tmp_path, lines, exit_code=0)

    assert status["result"] == "complete" and status["card_state"] == "complete"
    assert "Result: COMPLETE" in text and "next: the card is ready" in text


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_status_waits_for_the_operator_instead_of_calling_it_stalled(tmp_path):
    lines = _readback_in_progress()[:6] + [{"ts": _ts(30), "stage": "confirm", "card_state": "untouched"}]

    text, status = _status(tmp_path, lines)

    assert status["stalled"] is False and "ERASE confirmation" in status["waiting_for"]
    assert status["job_eta_seconds"] == 920  # the pre-flight prediction
    assert "Waiting for:" in text


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_status_flags_a_launch_that_never_started(tmp_path):
    text, status = _status(tmp_path, [{"ts": _ts(12), "stage": "launch", "card_state": "untouched"}])

    assert status["stalled"] is True and "UAC prompt" in status["stall_reason"]
    assert "STALLED" in text


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_status_without_a_progress_file_says_so(tmp_path):
    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(STATUS),
         "-LogPath", str(tmp_path / "missing.log"), "-Json"],
        capture_output=True, text=True,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["result"] == "unreadable"


def test_the_status_command_needs_no_elevation():
    text = STATUS.read_text(encoding="utf-8")

    assert "RunAs" not in text and "#Requires -RunAsAdministrator" not in text
    assert "[IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete" in text


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_relative_paths_are_made_absolute_before_the_elevated_window(case):
    # D-188 review: the elevated window starts in C:\Windows\System32.
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
               "-PlanPath", str(case["plan"]), "-ReleaseDir", str(case["release"]),
               "-WifiProfile", "site-default", "-LogPath", r"logs\attempt.log",
               "-RpiImager", r"tools\rpi-imager.exe", "-PythonExe", r"py\python.exe", "-PrintArguments"]
    completed = subprocess.run(command, capture_output=True, text=True, cwd=case["tmp"])

    assert completed.returncode == 0, completed.stderr
    resolved = json.loads(completed.stdout)
    log = case["tmp"] / "logs" / "attempt.log"
    assert Path(resolved["log"]) == log
    assert Path(resolved["progress"]) == Path(str(log) + ".progress.jsonl")
    assert Path(resolved["exit_marker"]) == Path(str(log) + ".exit")
    assert Path(resolved["arguments"]["RpiImager"]) == case["tmp"] / "tools" / "rpi-imager.exe"
    assert Path(resolved["arguments"]["PythonExe"]) == case["tmp"] / "py" / "python.exe"


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_a_bare_python_name_stays_a_path_lookup(case):
    completed = _print(case)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["arguments"]["PythonExe"] == "python"
