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
import time
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


NO_SSH = "rosy-no-such-ssh-for-test"


def _guard(port: int, env: dict, *extra: str) -> subprocess.CompletedProcess:
    # Tests that are not about ssh must never start the real one.
    if "-SshExe" not in extra:
        extra = (*extra, "-SshExe", NO_SSH)
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


# --- 2026-10-01: device credentials are stored by hostname, pushes name an IP --
# sd/rotate-core-api-credential.ps1 names the DPAPI file after the device
# hostname (rosy-pinky-9dfk.credential.xml), but pushes pass -Robot <ip>. The
# guard used to look only for <ip>.credential.xml and silently skipped the
# check. It now asks the robot its hostname over the push's own strict ssh.

# A native fake: the guard starts ssh as a process (it has to bound its
# wall-clock time), so a .cmd that logs its raw command line exercises the
# real Windows argument quoting. It answers the `hostname` call from a file
# and the HostKeyAlias check with its own exit code.
FAKE_SSH = "\r\n".join([
    "@echo off",
    '>>"%ROSY_FAKE_LOG%" echo(%*',
    'echo(%* | findstr /c:"HostKeyAlias=" >nul',
    "if not errorlevel 1 exit /b %ROSY_FAKE_ALIAS_EXIT%",
    "if defined ROSY_FAKE_SLEEP ping -n %ROSY_FAKE_SLEEP% 127.0.0.1 >nul",
    'if exist "%ROSY_FAKE_ANSWER%" type "%ROSY_FAKE_ANSWER%"',
    "exit /b %ROSY_FAKE_EXIT%",
    "",
])
HOST = "rosy-pinky-9dfk"
# Assembled so the secret scan's high-entropy rule does not read this fake key as a secret.
HOST_KEY = "ssh-ed25519 " + "AAAAC3NzaC1lZDI1NTE5" + "AAAAIFakeHostKeyForGuardTests" + "0" * 19


def _store_credential(tmp_path: Path, name: str, token: str = TOKEN) -> Path:
    path = tmp_path / "Rosy" / "api" / f"{name}.credential.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    script = ("$s = ConvertTo-SecureString $env:T -AsPlainText -Force; "
              "New-Object System.Management.Automation.PSCredential('tok-1|uid-1', $s) | "
              "Export-Clixml -LiteralPath $env:P")
    env = dict(os.environ, T=token, P=str(path))
    subprocess.run([POWERSHELL, "-NoProfile", "-Command", script], check=True, env=env, timeout=60)
    return path


def _known_hosts(tmp_path: Path, *names: str) -> Path:
    path = tmp_path / "Rosy" / "known_hosts"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{name} {HOST_KEY}\n" for name in names), encoding="ascii")
    return path


def _fake_ssh(tmp_path: Path, env: dict, hostname: str = "", exit_code: int = 0,
              alias_exit: int = 0, sleep: int = 0) -> tuple[Path, Path]:
    fake = tmp_path / "fake-ssh.cmd"
    fake.write_bytes(FAKE_SSH.encode("ascii"))
    log = tmp_path / "ssh.log"
    answer = tmp_path / "answer.txt"
    if hostname:
        answer.write_text(hostname.replace("|", "\n") + "\n", encoding="ascii")
    env["ROSY_FAKE_LOG"] = str(log)
    env["ROSY_FAKE_ANSWER"] = str(answer)
    env["ROSY_FAKE_EXIT"] = str(exit_code)
    env["ROSY_FAKE_ALIAS_EXIT"] = str(alias_exit)
    if sleep:
        env["ROSY_FAKE_SLEEP"] = str(sleep)
    return fake, log


def _calls(log: Path) -> list[str]:
    return [line.strip() for line in log.read_text(encoding="ascii").splitlines()] if log.exists() else []


def _resolvable(tmp_path: Path, **fake) -> tuple[dict, Path, Path]:
    """A robot at 127.0.0.1 named rosy-pinky-9dfk, its credential and host key stored."""
    _store_credential(tmp_path, HOST)
    _known_hosts(tmp_path, "127.0.0.1", HOST + ".local")
    env = _env(tmp_path)
    fake, log = _fake_ssh(tmp_path, env, fake.pop("hostname", HOST), **fake)
    return env, fake, log


def test_ip_resolves_to_the_hostname_credential_over_strict_ssh(fake_core, tmp_path):
    env, fake, log = _resolvable(tmp_path)
    done = _guard(fake_core["port"], env, "-SshExe", str(fake))
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert fake_core["auth"] == [f"Bearer {TOKEN}"], out
    assert "no active calibration session" in done.stdout and "SKIPPED" not in out
    calls = _calls(log)
    assert len(calls) == 2, calls
    lookup, alias = calls
    assert lookup.endswith("rosy@127.0.0.1 hostname"), lookup
    assert alias.endswith("rosy@127.0.0.1 true"), alias
    for call in calls:
        for option in ("-n ", "BatchMode=yes", "StrictHostKeyChecking=yes", "ConnectTimeout=5",
                       "ServerAliveInterval=2", "ServerAliveCountMax=2",
                       "UserKnownHostsFile=" + str(tmp_path / "Rosy" / "known_hosts"),
                       "-i " + str(tmp_path / "Rosy" / "ssh" / "rosy-operator-ed25519")):
            assert option in call, call
        assert '"' not in call  # no argument here needs quoting
    assert "HostKeyAlias" not in lookup
    # The real entry is rosy-pinky-9dfk.local: the alias is the stored entry
    # derived from the claimed name, never the IP.
    assert f"HostKeyAlias={HOST}.local" in alias


def test_hostname_credential_still_refuses_an_active_session(fake_core, tmp_path):
    fake_core["reply"] = ACTIVE
    env, fake, _ = _resolvable(tmp_path)
    done = _guard(fake_core["port"], env, "-SshExe", str(fake))
    assert done.returncode == 3, done.stdout + done.stderr
    assert fake_core["auth"] == [f"Bearer {TOKEN}"]


def test_a_claimed_hostname_without_its_host_key_gets_no_token(fake_core, tmp_path):
    # A compromised rosy account can print another robot's name; only that
    # robot's host key can pass the HostKeyAlias check.
    env, fake, log = _resolvable(tmp_path, alias_exit=255)
    done = _guard(fake_core["port"], env, "-SshExe", str(fake))
    out = done.stdout + done.stderr
    flat = "".join(out.split())
    assert done.returncode == 0, out
    assert fake_core["auth"] == [], out
    assert "CALIBRATION CHECK SKIPPED" in out
    assert f"HostKeyAlias={HOST}.local" in _calls(log)[-1]
    assert f"hostkeyof127.0.0.1doesnotmatchtheknown_hostsentryfor{HOST}.local" in flat.lower(), out


def test_a_claimed_hostname_missing_from_known_hosts_gets_no_token(fake_core, tmp_path):
    _store_credential(tmp_path, HOST)
    _known_hosts(tmp_path, "127.0.0.1", "rosy-pinky-8kcn.local")
    env = _env(tmp_path)
    fake, log = _fake_ssh(tmp_path, env, HOST)
    done = _guard(fake_core["port"], env, "-SshExe", str(fake))
    out = done.stdout + done.stderr
    flat = "".join(out.split())
    assert done.returncode == 0, out
    assert fake_core["auth"] == [], out
    assert len(_calls(log)) == 1, "no alias check without a known_hosts entry to check against"
    assert f"known_hostshasnoentryfor{HOST}" in flat, out


@pytest.mark.parametrize("answer", [
    "ROSY-PINKY-9DFK",            # case: Windows would open the lowercase file
    "rosy-pinky-9dfk.local",      # dots are not a device hostname
    "pinky-9dfk",                 # not a ROSY device name
    "rosy-pinky-9dfk|rosy-other", # more than one line
    "rosy-pinky-9dfk;x",
])
def test_a_bad_hostname_answer_is_not_used(fake_core, tmp_path, answer):
    for name in ("rosy-pinky-9dfk", "rosy-pinky-9dfk.local", "pinky-9dfk", "rosy-other"):
        _store_credential(tmp_path, name)
    # Every answer has a matching known_hosts entry, so only the answer check
    # (not the host-key alias lookup) can stop it.
    _known_hosts(tmp_path, "127.0.0.1", "rosy-pinky-9dfk", "ROSY-PINKY-9DFK", "rosy-pinky-9dfk.local",
                 "pinky-9dfk", "rosy-other", "rosy-pinky-9dfk;x")
    env = _env(tmp_path)
    fake, log = _fake_ssh(tmp_path, env, answer)
    done = _guard(fake_core["port"], env, "-SshExe", str(fake))
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert fake_core["auth"] == [], out
    assert "CALIBRATION CHECK SKIPPED" in out
    assert len(_calls(log)) == 1, "a rejected answer must not reach the alias check"


def test_a_failed_ssh_answer_is_not_used(fake_core, tmp_path):
    env, fake, _ = _resolvable(tmp_path, exit_code=255)
    done = _guard(fake_core["port"], env, "-SshExe", str(fake))
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert fake_core["auth"] == [], out
    assert "CALIBRATION CHECK SKIPPED" in out and "ssh exited 255" in out


def test_a_hanging_ssh_is_killed_at_the_wall_clock_limit(fake_core, tmp_path):
    env, fake, _ = _resolvable(tmp_path, sleep=60)
    started = time.monotonic()
    done = _guard(fake_core["port"], env, "-SshExe", str(fake), "-TimeoutSec", "1")
    elapsed = time.monotonic() - started
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert fake_core["auth"] == [], out
    assert "CALIBRATION CHECK SKIPPED" in out and "timed out" in out
    assert elapsed < 30, f"the guard waited {elapsed:.0f}s for a hanging ssh"


def test_no_ssh_skips_and_names_the_files_it_looked_for(fake_core, tmp_path):
    _store_credential(tmp_path, HOST)   # another robot's file: never tried
    done = _guard(fake_core["port"], _env(tmp_path), "-SshExe", NO_SSH)
    out = done.stdout + done.stderr
    flat = "".join(out.split())  # warnings wrap at the console width
    assert done.returncode == 0, out
    assert fake_core["auth"] == [], out
    assert "CALIBRATION CHECK SKIPPED" in out
    assert "127.0.0.1.credential.xml" in flat
    assert "hostname" in out.lower()
    assert f"{HOST}.credential.xml" not in flat


def test_ip_named_credential_wins_without_any_ssh_call(fake_core, tmp_path):
    _store_credential(tmp_path, "127.0.0.1")
    _store_credential(tmp_path, HOST, token="other-robot-token-0002")
    _known_hosts(tmp_path, "127.0.0.1", HOST + ".local")
    env = _env(tmp_path)
    fake, log = _fake_ssh(tmp_path, env, HOST)
    done = _guard(fake_core["port"], env, "-SshExe", str(fake))
    assert done.returncode == 0, done.stdout + done.stderr
    assert fake_core["auth"] == [f"Bearer {TOKEN}"]
    assert not log.exists(), "ssh was called although the IP-named credential exists"


def test_an_explicit_credential_path_switches_the_lookup_off(fake_core, tmp_path):
    env, fake, log = _resolvable(tmp_path)
    missing = tmp_path / "elsewhere.credential.xml"
    done = _guard(fake_core["port"], env, "-SshExe", str(fake), "-CredentialPath", str(missing))
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert fake_core["auth"] == [] and not log.exists(), out
    assert "elsewhere.credential.xml" in "".join(out.split())


def test_an_odd_rosy_user_is_refused_before_ssh(fake_core, tmp_path):
    env, fake, log = _resolvable(tmp_path)
    done = _guard(fake_core["port"], env, "-SshExe", str(fake), "-RosyUser", "Rosy;x")
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert fake_core["auth"] == [] and not log.exists(), out
    assert "RosyUser" in out


def test_a_known_hosts_path_with_whitespace_is_refused_before_ssh(fake_core, tmp_path):
    env, fake, log = _resolvable(tmp_path)
    spaced = tmp_path / "known hosts"
    spaced.write_text(f"{HOST}.local {HOST_KEY}\n", encoding="ascii")
    done = _guard(fake_core["port"], env, "-SshExe", str(fake), "-KnownHosts", str(spaced))
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert fake_core["auth"] == [] and not log.exists(), out
    assert "whitespace" in out


def test_connect_timeout_follows_timeout_sec(fake_core, tmp_path):
    env, fake, log = _resolvable(tmp_path)
    done = _guard(fake_core["port"], env, "-SshExe", str(fake), "-TimeoutSec", "3")
    assert done.returncode == 0, done.stdout + done.stderr
    calls = _calls(log)
    assert calls and all("ConnectTimeout=3 " in call for call in calls), calls


def test_a_key_path_with_a_space_reaches_native_ssh_as_one_argument(fake_core, tmp_path):
    env, fake, log = _resolvable(tmp_path)
    key = tmp_path / "operator key"
    done = _guard(fake_core["port"], env, "-SshExe", str(fake), "-KeyPath", str(key))
    assert done.returncode == 0, done.stdout + done.stderr
    assert fake_core["auth"] == [f"Bearer {TOKEN}"]
    # The raw command line: quoted once, exactly as a Windows native exe parses it.
    assert all(f'-i "{key}" ' in call for call in _calls(log)), _calls(log)


def test_release_push_passes_its_ssh_settings_to_the_guard(fake_core, tmp_path):
    fake_core["reply"] = ACTIVE
    _store_credential(tmp_path, HOST)
    known = _known_hosts(tmp_path, "127.0.0.1", HOST + ".local")
    custom_known = tmp_path / "custom_known_hosts"
    custom_known.write_bytes(known.read_bytes())
    env = _env(tmp_path)
    fake, log = _fake_ssh(tmp_path, env, HOST)
    key = tmp_path / "custom-key"
    done = _ps(PUSH, ["-Robot", "127.0.0.1", "-Rollback", "-ApiPort", str(fake_core["port"]),
                      "-SshExe", str(fake), "-ScpExe", str(fake), "-KeyPath", str(key),
                      "-KnownHosts", str(custom_known), "-RosyUser", "rosyop"], env)
    out = done.stdout + done.stderr
    assert done.returncode != 0, out
    assert "calibration session is active" in out
    calls = _calls(log)
    assert len(calls) == 2 and calls[0].endswith("rosyop@127.0.0.1 hostname"), calls
    for call in calls:
        assert "-i " + str(key) in call and "UserKnownHostsFile=" + str(custom_known) in call


def test_dev_overlay_sync_passes_its_user_to_the_guard():
    text = SYNC.read_text(encoding="utf-8")
    call = text[text.index("rosy-calibration-guard.ps1"):text.index("if ($LASTEXITCODE -eq 3)")]
    assert "-RosyUser $PiUser" in call


def test_server_error_is_reported_as_failed_not_rejected(fake_core, tmp_path):
    fake_core["status"] = 500
    fake_core["reply"] = {"error": {"code": "INTERNAL_ERROR"}}
    done = _guard(fake_core["port"], _env(tmp_path, TOKEN))
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert "CALIBRATION CHECK FAILED" in out and "HTTP 500" in out
    assert "REJECTED" not in out and "UNREACHABLE" not in out
