"""The arm's safety outlives a lost link (2026-10-31: the site PC dropped off mid-carry): the motors' own bus watchdog
is cleared and set at every session start, and the session runs in its own process session, not the caller's."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

OMX = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import bus_watchdog
finally:
    sys.path.remove(str(OMX))


def test_the_watchdog_is_cleared_then_set_on_every_motor_and_a_failed_write_refuses():
    bus = SimpleNamespace(motors={"shoulder_pan": SimpleNamespace(id=11), "gripper": SimpleNamespace(id=16)})
    writes = []
    assert bus_watchdog.arm(bus, 0, write=lambda i, v: writes.append((i, v)) or (0, 0)) == {} and writes == []
    assert bus_watchdog.arm(bus, 1000, write=lambda i, v: writes.append((i, v)) or (0, 0)) == {"shoulder_pan": 50, "gripper": 50}
    assert writes == [(11, 0), (11, 50), (16, 0), (16, 50)]  # 0 first: only 0 clears a tripped (-1) watchdog
    assert (bus_watchdog.units(10), bus_watchdog.units(9999)) == (1, 127)
    with pytest.raises(ValueError, match="gripper"):
        bus_watchdog.arm(bus, 1000, write=lambda i, v: (0, 0) if i == 11 else (-1001, 0))


@pytest.mark.skipif(shutil.which("setsid") is None or os.name != "posix", reason="needs setsid (Linux)")
def test_the_session_starts_in_its_own_process_session_and_is_reused(tmp_path):
    omx = tmp_path / "omx"
    omx.mkdir()
    # a stand-in session: answers start, then stays up like the real one
    (omx / "record_session.py").write_text(
        "import json, os, pathlib, time\n"
        "io = pathlib.Path('chunk-io'); io.mkdir(exist_ok=True)\n"
        "with (io / 'chunk-status.jsonl').open('a') as f:\n"
        "    f.write(json.dumps({'command': 'start', 'ok': True, 'sid': os.getsid(0)}) + '\\n')\n"
        "time.sleep(30)\n")
    env = {**os.environ, "OMX": str(omx), "OMX_PYTHON": sys.executable, "OMX_SESSION_ARGS": "", "OMX_SESSION_WAIT_S": "20"}
    script = str(OMX / "omx_session.sh")
    try:
        first = subprocess.run(["bash", script, sys.executable, "-c", "import os; print(os.getsid(0))"], cwd=tmp_path,
                               env=env, capture_output=True, text=True, timeout=60)
        assert first.returncode == 0, first.stderr
        import json

        rows = [json.loads(line) for line in (tmp_path / "chunk-io/chunk-status.jsonl").read_text().splitlines()]
        assert len(rows) == 1 and rows[0]["sid"] != int(first.stdout)  # not the caller's session: a lost link spares it
        second = subprocess.run(["bash", script, "--status"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
        assert second.stdout.startswith("session running")
        subprocess.run(["bash", script, "true"], cwd=tmp_path, env=env, check=True, timeout=60)
        assert len((tmp_path / "chunk-io/chunk-status.jsonl").read_text().splitlines()) == 1  # reused, not a second one
    finally:
        pid = tmp_path / "chunk-io/session.pid"
        if pid.exists():
            subprocess.run(["kill", pid.read_text().strip()], check=False)
