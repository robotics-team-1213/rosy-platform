"""D-321 addendum: CORE-restarting operator tools refuse to interrupt a calibration.

A release push and a CORE restart from another session once cut a calibration
drive short. `rosy-calibration-guard.ps1` asks CORE for the calibration session
lease; `rosy-release-push.ps1` and `dev/sync-core-dev.ps1` call it before they
touch the robot. The guard is soft: when it cannot ask (no token, CORE down) it
warns loudly and lets the operator proceed. A fake CORE on localhost stands in
for the robot, so nothing here reaches a device.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PINKY = ROOT / "deploy" / "robot" / "pinky_pro"
GUARD = PINKY / "rosy-calibration-guard.ps1"
PUSH = PINKY / "rosy-release-push.ps1"
SYNC = PINKY / "dev" / "sync-core-dev.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
TOKEN = "guard-test-token-0001"

ACTIVE = {"session": {"id": "cal-1", "kind": "drive", "label": "drive-cal",
                      "owner": {"id": "tok-a", "role": "operator", "label": "laptop"},
                      "started_at": "2026-10-01T09:00:00+00:00", "ttl_s": 30.0,
                      "elapsed_s": 12.0, "remaining_s": 21.5}}
IDLE = {"session": None}

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")


@pytest.fixture
def fake_core():
    state = {"reply": IDLE, "auth": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            state["auth"].append(self.headers.get("Authorization"))
            if self.path != "/api/v1/calibration/session":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(state["reply"]).encode("utf-8")
            self.send_response(state.get("status", 200))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["port"] = server.server_address[1]
    yield state
    server.shutdown()
    server.server_close()


def _env(tmp_path, token=None):
    env = dict(os.environ)
    env.pop("ROSY_API_TOKEN", None)
    env["LOCALAPPDATA"] = str(tmp_path)          # no stored device credential
    if token:
        env["ROSY_API_TOKEN"] = token
    return env


def _ps(script: Path, args: list[str], env: dict) -> subprocess.CompletedProcess:
    command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    return subprocess.run(command, capture_output=True, text=True, timeout=90, env=env)


def _guard(port: int, env: dict, *extra: str) -> subprocess.CompletedProcess:
    return _ps(GUARD, ["-Robot", "127.0.0.1", "-ApiPort", str(port), "-Action", "the test", *extra], env)


def test_active_session_is_refused_with_exit_3(fake_core, tmp_path):
    fake_core["reply"] = ACTIVE
    done = _guard(fake_core["port"], _env(tmp_path, TOKEN))
    assert done.returncode == 3, done.stdout + done.stderr
    assert "REFUSED" in done.stderr and "drive-cal" in done.stderr and "laptop" in done.stderr
    assert fake_core["auth"] == [f"Bearer {TOKEN}"]


def test_force_proceeds_with_a_loud_warning(fake_core, tmp_path):
    fake_core["reply"] = ACTIVE
    done = _guard(fake_core["port"], _env(tmp_path, TOKEN), "-Force")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "-Force" in done.stdout + done.stderr and "interrupted" in done.stdout + done.stderr


def test_no_session_passes_quietly(fake_core, tmp_path):
    done = _guard(fake_core["port"], _env(tmp_path, TOKEN))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "no active calibration session" in done.stdout


def test_explicit_token_wins_over_the_environment(fake_core, tmp_path):
    _guard(fake_core["port"], _env(tmp_path, "env-token-xxxxxxxx"), "-ApiToken", TOKEN)
    assert fake_core["auth"] == [f"Bearer {TOKEN}"]


def test_unreachable_core_warns_but_does_not_block(tmp_path):
    done = _guard(1, _env(tmp_path, TOKEN), "-TimeoutSec", "2")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "CALIBRATION CHECK UNREACHABLE" in done.stdout + done.stderr


def test_missing_token_warns_but_does_not_block(fake_core, tmp_path):
    done = _guard(fake_core["port"], _env(tmp_path))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "CALIBRATION CHECK SKIPPED" in done.stdout + done.stderr
    assert fake_core["auth"] == []


def test_release_push_refuses_before_any_remote_step(fake_core, tmp_path):
    fake_core["reply"] = ACTIVE
    # A real (non-preview) rollback run: if the guard let it through, the first
    # remote step would try to start this nonexistent ssh and fail differently.
    done = _ps(PUSH, ["-Robot", "127.0.0.1", "-Rollback", "-ApiPort", str(fake_core["port"]),
                      "-SshExe", "rosy-no-such-ssh-for-test"], _env(tmp_path, TOKEN))
    out = done.stdout + done.stderr
    assert done.returncode != 0
    assert "calibration session is active" in out
    assert "+ rosy-no-such-ssh-for-test" not in out, "a remote step ran after the refusal"


def test_release_push_with_force_goes_on_to_the_remote_plan(fake_core, tmp_path):
    fake_core["reply"] = ACTIVE
    done = _ps(PUSH, ["-Robot", "127.0.0.1", "-Rollback", "-ApiPort", str(fake_core["port"]),
                      "-SshExe", "rosy-no-such-ssh-for-test", "-Force"], _env(tmp_path, TOKEN))
    out = done.stdout + done.stderr
    assert "+ rosy-no-such-ssh-for-test" in out, out
    assert "calibration session is active" not in out


def test_print_commands_never_calls_the_guard(fake_core, tmp_path):
    fake_core["reply"] = ACTIVE
    done = _ps(PUSH, ["-Robot", "127.0.0.1", "-Rollback", "-PrintCommands",
                      "-ApiPort", str(fake_core["port"])], _env(tmp_path, TOKEN))
    assert done.returncode == 0, done.stderr
    assert fake_core["auth"] == []


def test_dev_overlay_sync_runs_the_guard_before_uploading():
    text = SYNC.read_text(encoding="utf-8")
    guard_at = text.index("rosy-calibration-guard.ps1")
    assert guard_at < text.index("& scp") and guard_at < text.index("& ssh $remote")
    assert "[switch]$Force" in text


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_token_is_reported_apart_from_unreachable(fake_core, tmp_path, status):
    fake_core["status"] = status
    fake_core["reply"] = {"error": {"code": "UNAUTHORIZED"}}
    done = _guard(fake_core["port"], _env(tmp_path, TOKEN))
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert "CALIBRATION CHECK REJECTED" in out and f"HTTP {status}" in out
    assert "UNREACHABLE" not in out


def test_unexpected_reply_shape_warns_instead_of_aborting(fake_core, tmp_path):
    fake_core["reply"] = {"something": "else"}
    done = _guard(fake_core["port"], _env(tmp_path, TOKEN))
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert "UNEXPECTED REPLY" in out


def test_session_without_owner_fields_is_still_refused(fake_core, tmp_path):
    fake_core["reply"] = {"session": {"id": "cal-2", "kind": "camera"}}
    done = _guard(fake_core["port"], _env(tmp_path, TOKEN))
    assert done.returncode == 3, done.stdout + done.stderr
    assert "REFUSED" in done.stderr and "owner unknown" in done.stderr


def test_skill_prefers_environment_or_dpapi_over_a_command_line_token():
    text = (ROOT / ".claude" / "skills" / "rosy-release-push" / "SKILL.md").read_text(encoding="utf-8")
    assert "ROSY_API_TOKEN" in text and "DPAPI" in text
    assert "last resort" in text


def test_server_error_is_reported_as_failed_not_rejected(fake_core, tmp_path):
    fake_core["status"] = 500
    fake_core["reply"] = {"error": {"code": "INTERNAL_ERROR"}}
    done = _guard(fake_core["port"], _env(tmp_path, TOKEN))
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert "CALIBRATION CHECK FAILED" in out and "HTTP 500" in out
    assert "REJECTED" not in out and "UNREACHABLE" not in out
