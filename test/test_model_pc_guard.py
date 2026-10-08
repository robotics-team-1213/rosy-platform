"""Model PC hang guard: the site check reboots only after repeated bad answers (deploy/site)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "deploy" / "site" / "rosy-model-guard-check"
REMOTE = ROOT / "deploy" / "site" / "rosy-model-guard-remote"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt", reason="needs a POSIX shell")


def _check(tmp_path, answer, *, runs=1, exit_code=0, quiet="00:00-00:01"):
    """Run the check with a stub ssh that answers ``health`` and records ``reboot``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "calls"
    (bin_dir / "ssh").write_text(
        "#!/bin/sh\n"
        f'eval "last=\\${{$#}}"; echo "$last" >> {calls}\n'
        f'[ "$last" = reboot ] && exit 0\n'
        f"echo '{answer}'; exit {exit_code}\n")
    (bin_dir / "ssh").chmod(0o755)
    (bin_dir / "logger").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "logger").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GUARD_STATE": str(tmp_path / "state"),
           "GUARD_QUIET": quiet}
    for _ in range(runs):
        subprocess.run(["bash", str(CHECK)], env=env, check=True, capture_output=True, timeout=30)
    return calls.read_text().split() if calls.exists() else []


def test_a_healthy_pc_is_never_rebooted(tmp_path):
    assert _check(tmp_path, "60 5 1.2 24 7200", runs=5) == ["health"] * 5


def test_three_bad_answers_in_a_row_reboot_once(tmp_path):
    calls = _check(tmp_path, "2 95 3.0 24 7200", runs=3)
    assert calls == ["health", "health", "health", "reboot"]


def test_an_overloaded_cpu_counts_as_bad(tmp_path):
    assert _check(tmp_path, "50 10 120.0 24 7200", runs=3)[-1] == "reboot"


def test_a_pc_that_just_booted_is_left_alone(tmp_path):
    assert "reboot" not in _check(tmp_path, "2 95 3.0 24 600", runs=4)


def test_an_unreachable_pc_is_only_logged(tmp_path):
    assert _check(tmp_path, "", runs=4, exit_code=255) == ["health"] * 4


def test_nothing_runs_in_the_nightly_reboot_window(tmp_path):
    assert _check(tmp_path, "2 95 3.0 24 7200", runs=3, quiet="00:00-23:59") == []


def test_the_forced_command_answers_health_and_refuses_anything_else(tmp_path):
    ok = subprocess.run(["sh", str(REMOTE)], env={**os.environ, "SSH_ORIGINAL_COMMAND": "health"},
                        capture_output=True, text=True, timeout=10)
    fields = ok.stdout.split()
    assert ok.returncode == 0 and len(fields) == 5 and all(f.replace(".", "").isdigit() for f in fields)
    refused = subprocess.run(["sh", str(REMOTE)], env={**os.environ, "SSH_ORIGINAL_COMMAND": "rm -rf /"},
                             capture_output=True, text=True, timeout=10)
    assert refused.returncode == 2
