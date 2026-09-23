from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import threading

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "robot" / "verify" / "verify-from-windows.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


class _Handler(BaseHTTPRequestHandler):
    paths: list[str] = []

    def do_GET(self):  # noqa: N802 - stdlib callback name
        type(self).paths.append(self.path)
        if self.path in {"/api/v1", "/dashboard"}:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, _format, *_args):
        return


@pytest.fixture
def rosy_http():
    _Handler.paths = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, _Handler.paths
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _fake_ssh(
    directory: Path, *, fail: bool = False, malformed_route: bool = False
) -> Path:
    directory.mkdir()
    if os.name == "nt":
        path = directory / "ssh.cmd"
        if fail:
            body = "@echo off\necho LEAKED_REMOTE_BANNER 1>&2\nexit /b 255\n"
        else:
            route = "route-without-interface" if malformed_route else "default via 127.0.0.1 dev eth0"
            body = (
                "@echo off\n"
                "echo %* | %SystemRoot%\\System32\\findstr.exe /C:\"ip -4 route show default\" >nul\n"
                f"if not errorlevel 1 (echo {route}& exit /b 0)\n"
                "echo 2: eth0    inet 127.0.0.1/8 scope global eth0\n"
            )
    else:
        path = directory / "ssh"
        if fail:
            body = "#!/bin/sh\necho LEAKED_REMOTE_BANNER >&2\nexit 255\n"
        else:
            route = "route-without-interface" if malformed_route else "default via 127.0.0.1 dev eth0"
            body = (
                "#!/bin/sh\n"
                "case \"$*\" in\n"
                f"  *'ip -4 route show default'*) echo '{route}' ;;\n"
                "  *) echo '2: eth0    inet 127.0.0.1/8 scope global eth0' ;;\n"
                "esac\n"
            )
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return path


def _run(
    tmp_path: Path,
    port: int,
    *,
    fail_ssh: bool = False,
    malformed_route: bool = False,
    network_interface: str = "auto",
    evidence: Path | None = None,
):
    if POWERSHELL is None:
        pytest.skip("PowerShell is required for the Windows verifier process test")
    bin_dir = tmp_path / "bin"
    _fake_ssh(bin_dir, fail=fail_ssh, malformed_route=malformed_route)
    evidence = evidence or tmp_path / "connection-evidence.json"
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    command = [
        POWERSHELL,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        "-PiHost",
        "127.0.0.1",
        "-PiUser",
        "rosy",
        "-NetworkInterface",
        network_interface,
        "-ApiPort",
        str(port),
        "-ConnectTimeoutSec",
        "2",
        "-BatchMode",
        "-EvidencePath",
        str(evidence),
    ]
    return subprocess.run(command, capture_output=True, text=True, env=env), evidence


def test_success_writes_atomic_machine_readable_connection_evidence(tmp_path, rosy_http):
    port, paths = rosy_http

    result, evidence = _run(tmp_path, port)

    assert result.returncode == 0, result.stderr
    record = json.loads(evidence.read_text(encoding="utf-8-sig"))
    assert record["schema_version"] == 1
    assert record["outcome"] == "GO"
    assert record["target"] == {"host": "127.0.0.1", "user": "rosy"}
    assert record["network"] == {"interface": "eth0", "address": "127.0.0.1"}
    assert record["failure"] is None
    assert [check["name"] for check in record["checks"]] == [
        "ssh_route",
        "ssh_address",
        "http_api",
        "http_dashboard",
    ]
    assert all(check["outcome"] == "GO" for check in record["checks"])
    assert paths == ["/api/v1", "/dashboard"]
    assert not list(tmp_path.glob(".connection-evidence.json.*.tmp"))


def test_ssh_failure_writes_redacted_hold_evidence_and_exits_nonzero(tmp_path, rosy_http):
    port, paths = rosy_http

    result, evidence = _run(tmp_path, port, fail_ssh=True)

    assert result.returncode != 0
    record = json.loads(evidence.read_text(encoding="utf-8-sig"))
    assert record["outcome"] == "HOLD"
    assert record["failure"]["code"] == "SSH_ROUTE"
    assert record["checks"] == [{"name": "ssh_route", "outcome": "HOLD"}]
    assert "LEAKED_REMOTE_BANNER" not in json.dumps(record)
    assert paths == []


def test_semantically_invalid_route_is_hold_not_a_successful_ssh_route(tmp_path, rosy_http):
    port, paths = rosy_http

    result, evidence = _run(tmp_path, port, malformed_route=True)

    assert result.returncode != 0
    record = json.loads(evidence.read_text(encoding="utf-8-sig"))
    assert record["failure"]["code"] == "ROUTE_INTERFACE"
    assert record["checks"] == [{"name": "ssh_route", "outcome": "HOLD"}]
    assert paths == []


def test_explicit_interface_is_not_misreported_as_a_verified_default_route(tmp_path, rosy_http):
    port, _paths = rosy_http

    result, evidence = _run(tmp_path, port, network_interface="eth0")

    assert result.returncode == 0, result.stderr
    record = json.loads(evidence.read_text(encoding="utf-8-sig"))
    assert [check["name"] for check in record["checks"]] == [
        "interface_selected",
        "ssh_address",
        "http_api",
        "http_dashboard",
    ]


def test_existing_evidence_is_never_replaced(tmp_path, rosy_http):
    port, _paths = rosy_http
    evidence = tmp_path / "connection-evidence.json"
    evidence.write_text("keep-this-evidence\n", encoding="utf-8")

    result, _ = _run(tmp_path, port, evidence=evidence)

    assert result.returncode != 0
    assert evidence.read_text(encoding="utf-8") == "keep-this-evidence\n"


def test_verifier_uses_bounded_optional_batch_ssh_without_unsafe_host_key_bypass():
    script = SCRIPT.read_text(encoding="utf-8")

    for required in (
        '[int]$ApiPort = 8080',
        '[int]$ConnectTimeoutSec = 5',
        '[switch]$BatchMode',
        '[string]$EvidencePath = ""',
        '"ConnectTimeout=$ConnectTimeoutSec"',
        '"ConnectionAttempts=1"',
    ):
        assert required in script
    assert "StrictHostKeyChecking=no" not in script
