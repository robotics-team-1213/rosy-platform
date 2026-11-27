"""arm_s sessions start on the job's library; a running session on another library is refused, not reused (2026-11-28).

A policy job whose library differs from the session start library was refused at chunk 0 as
"policy jaw_gate conflicts with library grasp_pick geometry": the runner trusts its start library's grasp_pick.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"


def test_policy_jobs_on_arm_s_start_the_session_on_their_library(monkeypatch):
    monkeypatch.syspath_prepend(str(OMX))
    from record_session_baseline import session_job_env

    monkeypatch.delenv("ROSY_SESSION_CHUNKS", raising=False)
    for job in ("cell_policy_drive", "cell_policy_run"):
        env = session_job_env("owner", ["./w"], job, "arm_s", True, {"library": "chunks-arm-s-x.json"})
        assert env["ROSY_SESSION_CHUNKS"] == "chunks-arm-s-x.json" and env["ROSY_SESSION_CHUNKS_STRICT"] == "1"
    assert "ROSY_SESSION_CHUNKS" not in session_job_env("owner", ["./w"], "auto_pick", "arm_s", True, {"library": "x.json"})
    assert "ROSY_SESSION_CHUNKS" not in session_job_env("owner", ["./w"], "cell_policy_drive", "arm_a", True, {"library": "x.json"})


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason="runs the bash wrapper")
@pytest.mark.parametrize("running, strict, expect_rc", [
    ("chunks-arm-s-a.json", "1", 0),
    ("chunks-arm-s-b.json", "1", 2),
    (None, "1", 2),  # unknown start library: refuse, never fail open
    ("chunks-arm-s-b.json", None, 0),  # a fold or recovery reuses any running session
])
def test_reused_arm_s_session_must_match_the_job_library(tmp_path, running, strict, expect_rc):
    home = tmp_path / "home"
    (home / ".config/rosy").mkdir(parents=True)
    (home / ".config/rosy/omx-observation-bridge.env").write_text("")
    (home / "rosy-omx/current-env/bin").mkdir(parents=True)
    (home / "rosy-omx/current-env/bin/python").symlink_to(sys.executable)
    prep = home / "rosy-test/omx-record-prep-20261019"
    (prep / "chunk-io-s").mkdir(parents=True)
    fifo = prep / "chunk-io-s/chunk-cmd"
    os.mkfifo(fifo)
    wrappers = tmp_path / "wrappers"
    wrappers.mkdir()
    shutil.copy(OMX / "session-wrappers/with-session-arm-s-live.sh", wrappers)
    (wrappers / "tools-env.sh").write_text("")
    stubs = tmp_path / "bin"
    stubs.mkdir()
    pgrep = stubs / "pgrep"
    line = f"echo '42 python record_session.py --arm arm_s --chunks {running} --io chunk-io-s --params p.json'" if running else "exit 1"
    pgrep.write_text(f"#!/bin/sh\n{line}\n")
    pgrep.chmod(0o755)
    reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)  # a live session holds the command pipe open
    try:
        out = subprocess.run(
            ["bash", str(wrappers / "with-session-arm-s-live.sh"), "echo", "ran"], capture_output=True, text=True, timeout=30,
            env={"HOME": str(home), "PATH": f"{stubs}:{os.environ['PATH']}", "ROSY_SESSION_CHUNKS": "chunks-arm-s-a.json",
                 **({"ROSY_SESSION_CHUNKS_STRICT": strict} if strict else {})})
    finally:
        os.close(reader)
    assert out.returncode == expect_rc, out.stdout + out.stderr
    assert ("ran" in out.stdout) is (expect_rc == 0)
    if expect_rc:
        assert f"REFUSED: the running arm_s session started with {running or 'an unknown library'}" in out.stdout
