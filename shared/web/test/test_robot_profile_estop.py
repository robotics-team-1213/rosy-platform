"""A latched e-stop is never hidden by a caller-supplied caution (robotProfile alarm)."""

from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = """
import {robotProfile} from %s;
const base = {kind: "mobile", id: "r1", estop: true, battery: {percent: 80}};
const a = robotProfile({...base, alarm: {level: "caution", text: "x"}}).alarm;
const b = robotProfile({...base, alarm: {level: "danger", text: "y"}}).alarm;
if (a.level !== "danger" || a.text !== "비상 정지") throw new Error("caution hid the e-stop");
if (b.text !== "y") throw new Error("explicit danger lost");
"""


def test_estop_outranks_a_supplied_caution(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    repo = Path(__file__).resolve().parents[3]
    module = (repo / "applications/fleet/web/shared/robot-profile.js").as_uri()
    register = (repo / "operations/fleet/test/web/register-console-assets.mjs").as_uri()
    (tmp_path / "t.mjs").write_text(SCRIPT % ('"%s"' % module), encoding="utf-8")
    result = subprocess.run([node, "--import", register, str(tmp_path / "t.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
