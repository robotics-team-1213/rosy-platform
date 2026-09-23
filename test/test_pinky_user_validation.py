"""Operator-facing, stationary Pinky validation contracts."""

import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest


ROOT = Path(__file__).resolve().parents[1]
EVALUATOR = ROOT / "deploy" / "robot" / "pinky_validation.py"
WINDOWS_VALIDATOR = ROOT / "deploy" / "robot" / "verify" / "validate-pinky-from-windows.ps1"
RUNBOOK = ROOT / "docs" / "deployment" / "pinky-pro-first-device-runbook.md"
DESIGN = ROOT / "docs" / "plans" / "2026-09-21-pinky-user-validation-design.md"


def test_user_validation_entrypoints_exist():
    assert EVALUATOR.is_file()
    assert WINDOWS_VALIDATOR.is_file()
    assert DESIGN.is_file()


def _module():
    spec = importlib.util.spec_from_file_location("pinky_validation", EVALUATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _go_evidence():
    revision = "a" * 40
    connection = {
        "schema_version": 1,
        "outcome": "GO",
        "network": {"interface": "eth0", "address": "192.0.2.41"},
    }
    readback = {
        "schema_version": 1,
        "device": {
            "hostname": "pinky-01",
            "model": "Raspberry Pi 5 Model B Rev 1.0",
            "architecture": "arm64",
        },
        "identity": {
            "robot_number": "1",
            "ros_domain_id": "41",
            "namespace": "rosy_01",
            "runtime_mode": "core",
        },
        "activation": {"runtime_mode": "core"},
        "artifact": {"git_revision": revision},
        "gates": {"device_runtime": "GO", "field": "HOLD"},
    }
    return connection, readback, revision


def test_stationary_go_names_the_next_safe_gate_without_authorizing_motion():
    connection, readback, revision = _go_evidence()

    summary = _module().build_summary(
        connection,
        readback,
        expected_robot_number=1,
        expected_revision=revision,
    )

    assert summary["outcome"] == "GO"
    assert summary["scope"] == "STATIONARY_DEVICE_PREFLIGHT"
    assert summary["motion_authorized"] is False
    assert summary["next_gate"] == "G3_SENSOR_ONLY"
    assert summary["dashboard_url"] == "http://192.0.2.41:8080/dashboard"
    assert all(check["outcome"] == "GO" for check in summary["checks"])


def test_revision_or_field_scope_mismatch_is_an_actionable_hold():
    connection, readback, revision = _go_evidence()
    readback["artifact"]["git_revision"] = "b" * 40
    readback["gates"]["field"] = "GO"

    summary = _module().build_summary(
        connection,
        readback,
        expected_robot_number=1,
        expected_revision=revision,
    )

    assert summary["outcome"] == "HOLD"
    assert summary["motion_authorized"] is False
    assert summary["next_gate"] == "REMEDIATE_HOLD"
    assert summary["failed_checks"] == ["source_revision", "field_hold_preserved"]
    assert summary["operator_message"] == "HOLD: fix the named checks; do not enable motors."


def test_dashboard_url_uses_the_verified_api_port():
    connection, readback, revision = _go_evidence()

    summary = _module().build_summary(
        connection,
        readback,
        expected_robot_number=1,
        expected_revision=revision,
        api_port=18080,
    )

    assert summary["dashboard_url"] == "http://192.0.2.41:18080/dashboard"


def test_missing_device_readback_still_produces_a_fail_closed_summary():
    connection = {
        "schema_version": 1,
        "outcome": "HOLD",
        "network": {"interface": None, "address": None},
    }

    summary = _module().build_summary(
        connection,
        None,
        expected_robot_number=1,
        expected_revision="a" * 40,
    )

    assert summary["outcome"] == "HOLD"
    assert summary["motion_authorized"] is False
    assert summary["device_readback_available"] is False
    assert "lan_peer" in summary["failed_checks"]
    assert "device_runtime" in summary["failed_checks"]


def test_evaluator_cli_writes_a_go_summary_without_replacing_evidence(tmp_path):
    connection, readback, revision = _go_evidence()
    connection_path = tmp_path / "connection.json"
    readback_path = tmp_path / "readback.json"
    output_path = tmp_path / "summary.json"
    connection_path.write_text(json.dumps(connection), encoding="utf-8")
    readback_path.write_text(json.dumps(readback), encoding="utf-8")

    command = [
        sys.executable,
        str(EVALUATOR),
        "--connection", str(connection_path),
        "--readback", str(readback_path),
        "--expected-robot-number", "1",
        "--expected-revision", revision,
        "--output", str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert json.loads(output_path.read_text(encoding="utf-8"))["outcome"] == "GO"
    second = subprocess.run(command, capture_output=True, text=True, check=False)
    assert second.returncode != 0
    assert "refusing to replace" in second.stderr.lower()


def test_evaluator_cli_records_hold_when_readback_was_not_collected(tmp_path):
    connection_path = tmp_path / "connection.json"
    output_path = tmp_path / "summary.json"
    connection_path.write_text(
        json.dumps({"schema_version": 1, "outcome": "HOLD", "network": {}}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(EVALUATOR),
            "--connection", str(connection_path),
            "--expected-robot-number", "1",
            "--expected-revision", "a" * 40,
            "--output", str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2, result.stderr
    summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert summary["outcome"] == "HOLD"
    assert summary["device_readback_available"] is False


def test_windows_validator_collects_only_stationary_evidence_and_hashes_it():
    script = WINDOWS_VALIDATOR.read_text(encoding="utf-8")

    for required in (
        "ExpectedRobotNumber",
        "ExpectedRevision",
        "EvidenceDirectory",
        "verify-from-windows.ps1",
        "device-readback.sh --json",
        "pinky_validation.py",
        "Get-FileHash",
        "SHA256SUMS.txt",
        "motion_authorized",
    ):
        assert required in script
    for forbidden in (
        "runtime-mode.sh up",
        "runtime-mode.sh down",
        "verify-motors.sh",
        "deploy-from-windows.ps1",
        "StrictHostKeyChecking=no",
        "password",
        "token",
    ):
        assert forbidden.lower() not in script.lower()


def test_windows_validator_keeps_actionable_hold_evidence_when_ssh_fails(tmp_path):
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if not powershell:
        pytest.skip("PowerShell is required for the Windows operator flow")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "ssh.cmd").write_text("@echo off\r\nexit /b 1\r\n", encoding="ascii")
    evidence = tmp_path / "evidence"
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", str(WINDOWS_VALIDATOR),
            "-PiHost", "pinky.invalid",
            "-ExpectedRobotNumber", "1",
            "-ExpectedRevision", "a" * 40,
            "-EvidenceDirectory", str(evidence),
            "-ConnectTimeoutSec", "1",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    summary = json.loads((evidence / "user-validation-summary.json").read_text(encoding="utf-8"))
    assert summary["outcome"] == "HOLD"
    assert summary["device_readback_available"] is False
    assert not (evidence / "G2-device-readback.json").exists()
    hashes = (evidence / "SHA256SUMS.txt").read_text(encoding="ascii")
    assert "G0-connection.json" in hashes
    assert "user-validation-summary.json" in hashes


def test_windows_validator_runs_the_complete_stationary_go_path(tmp_path):
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if not powershell:
        pytest.skip("PowerShell is required for the Windows operator flow")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    revision = "a" * 40
    _, readback, _ = _go_evidence()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "readback.json").write_text(json.dumps(readback), encoding="utf-8")
    (fake_bin / "fake_ssh.py").write_text(
        """import pathlib, sys
command = sys.argv[-1]
if command == 'ip -4 -o addr show dev eth0 scope global':
    print('2: eth0    inet 127.0.0.1/8 scope global eth0')
    raise SystemExit(0)
if command == 'sudo -n /opt/rosy/deploy/robot/verify/device-readback.sh --json':
    print((pathlib.Path(__file__).parent / 'readback.json').read_text(encoding='utf-8'))
    raise SystemExit(0)
raise SystemExit(1)
""",
        encoding="utf-8",
    )
    (fake_bin / "ssh.cmd").write_text(
        '@echo off\r\npython "%~dp0fake_ssh.py" %*\r\n',
        encoding="ascii",
    )
    evidence = tmp_path / "go-evidence"
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    try:
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", str(WINDOWS_VALIDATOR),
                "-PiHost", "127.0.0.1",
                "-NetworkInterface", "eth0",
                "-ApiPort", str(server.server_port),
                "-ExpectedRobotNumber", "1",
                "-ExpectedRevision", revision,
                "-EvidenceDirectory", str(evidence),
                "-ConnectTimeoutSec", "2",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
            timeout=15,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    summary = json.loads((evidence / "user-validation-summary.json").read_text(encoding="utf-8"))
    assert summary["outcome"] == "GO"
    assert summary["motion_authorized"] is False
    assert summary["dashboard_url"] == f"http://127.0.0.1:{server.server_port}/dashboard"
    assert (evidence / "G2-device-readback.json").is_file()
    hashes = (evidence / "SHA256SUMS.txt").read_text(encoding="ascii")
    assert hashes.count("\n") == 3


def test_runbook_has_a_copyable_user_validation_command_and_scope():
    runbook = RUNBOOK.read_text(encoding="utf-8")

    for phrase in (
        "validate-pinky-from-windows.ps1",
        "-ExpectedRobotNumber",
        "-ExpectedRevision",
        "user-validation-summary.json",
        "SHA256SUMS.txt",
        "motion_authorized",
        "G3_SENSOR_ONLY",
    ):
        assert phrase in runbook
    assert "GO != motion authorization" in runbook
