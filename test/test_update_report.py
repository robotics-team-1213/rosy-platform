"""D-871: rosy-update-report sends each update channel's step and release, never log text."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPORT = Path(__file__).resolve().parents[1] / "deploy/hosts/common/rosy-update-report"
pytestmark = pytest.mark.skipif(shutil.which("sh") is None or os.name == "nt", reason="needs a POSIX shell")

JOURNAL = {
    "rosy-omx-devices-autoupdate.service": [
        '1000.0 host python3[1]: {"step": "switched", "release": "d0d7f7367b4d", "previous": "61addd56955e"}',
        '1100.0 host python3[1]: {"step": "deferred", "release": "e1e1e1e1e1e1", "reason": "follower_torque_not_off"}',
    ],
    "rosy-review-release-update.service": [
        "900.0 host python3[2]: already active: model-code-31-3cdfd40ac2ab",
        "950.0 host python3[2]: waiting for model-code update or learning job",
        "960.0 host python3[2]: Traceback (most recent call last): secret /home/rosy/private.json",
    ],
}


def run(tmp_path, gate_rc=0):
    bin_dir, units = tmp_path / "bin", tmp_path / "home/.config/systemd/user"
    bin_dir.mkdir()
    (units / "timers.target.wants").mkdir(parents=True)
    for unit in (*JOURNAL, "rosy-situation.service", "pinky-backend-update.service"):
        (units / unit).write_text("")
    (units / "rosy-omx-devices-autoupdate.timer").write_text("")
    (units / "timers.target.wants/rosy-omx-devices-autoupdate.timer").write_text("")
    for unit, lines in JOURNAL.items():
        (tmp_path / unit).write_text("\n".join(lines) + "\n")
    (bin_dir / "journalctl").write_text(f'#!/bin/sh\ncat "{tmp_path}/$3"\n')  # --user -u <unit> ...
    (bin_dir / "gate").write_text(f"#!/bin/sh\nexit {gate_rc}\n")
    for name in ("journalctl", "gate"):
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path / "home"), "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "ROSY_UPDATE_GATE": str(bin_dir / "gate"), "ROSY_SITE_AUTOUPDATE_STATE": str(tmp_path / "none.json")}
    done = subprocess.run([sys.executable, str(REPORT)], env=env, capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


def test_each_updater_reports_its_timer_last_step_and_last_healthy_time(tmp_path):
    body = run(tmp_path)
    assert body["schema"] == "rosy.update-report/1" and body["gate"] == "open"
    rows = {row["unit"]: row for row in body["updaters"]}
    assert set(rows) == {"rosy-omx-devices-autoupdate.service", "rosy-review-release-update.service"}
    devices = rows["rosy-omx-devices-autoupdate.service"]
    assert devices["timer"] == "enabled" and devices["healthy_at"] == 1000.0
    assert devices["last"] == {"step": "deferred", "release": "e1e1e1e1e1e1", "reason": "follower_torque_not_off",
                               "at": 1100.0}
    review = rows["rosy-review-release-update.service"]
    assert review["timer"] == "none" and review["healthy_at"] == 900.0
    assert review["last"]["step"] == "waiting" and review["last"]["release"] is None


def test_no_log_text_leaves_the_pc_and_a_closed_gate_reads_frozen(tmp_path):
    body = run(tmp_path, gate_rc=1)
    assert body["gate"] == "frozen"
    text = json.dumps(body)
    assert "Traceback" not in text and "/home/rosy" not in text and "previous" not in text
