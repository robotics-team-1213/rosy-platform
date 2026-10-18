"""D-805: updaters run only when nothing freezes updates; anything uncertain skips (fail closed)."""
from pathlib import Path
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "deploy/hosts/common/host-state/rosy-update-gate"
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell fake git")


def gate(tmp_path, *, git_script=None, local=False, home_freeze=False):
    env = {**os.environ, "ROSY_HOST_STATE_ROOT": str(tmp_path / "root"), "HOME": str(tmp_path / "home")}
    if git_script is not None:
        fake = tmp_path / "git"
        fake.write_text("#!/bin/sh\n" + git_script)
        fake.chmod(0o755)
        env["ROSY_UPDATE_GATE_GIT"] = str(fake)
    else:
        env["ROSY_UPDATE_GATE_GIT"] = str(tmp_path / "no-such-git")
    if local:
        (tmp_path / "root/etc/rosy").mkdir(parents=True)
        (tmp_path / "root/etc/rosy/update-freeze").write_text("")
    if home_freeze:
        (tmp_path / "home/.config/rosy").mkdir(parents=True)
        (tmp_path / "home/.config/rosy/update-freeze").write_text("")
    done = subprocess.run([sys.executable, "-I", str(GATE)], env=env, capture_output=True, text=True, timeout=30)
    return done.returncode, done.stdout


def test_no_tag_lets_the_updater_run(tmp_path):
    assert gate(tmp_path, git_script="exit 0\n") == (0, "rosy-update-gate: run: no freeze\n")


def test_the_site_tag_freezes(tmp_path):
    code, out = gate(tmp_path, git_script="echo 'abc123\trefs/tags/ops-update-freeze'\n")
    assert code == 1 and "frozen by tag" in out


@pytest.mark.parametrize("script", ["exit 128\n", "sleep 30\n"])
def test_an_uncheckable_tag_skips_the_run(tmp_path, script):
    code, out = gate(tmp_path, git_script=script)
    assert code == 1 and "failing closed" in out


def test_missing_git_skips_the_run(tmp_path):
    code, out = gate(tmp_path)
    assert code == 1 and "failing closed" in out


@pytest.mark.parametrize("where", ["local", "home_freeze"])
def test_a_local_freeze_file_wins_without_asking_the_network(tmp_path, where):
    code, out = gate(tmp_path, git_script="exit 0\n", **{where: True})
    assert code == 1 and "frozen by" in out and "update-freeze" in out


def test_every_gated_unit_and_drop_in_points_at_the_installed_gate():
    dropin = (ROOT / "deploy/hosts/common/host-state/10-update-gate.conf").read_text()
    assert "ExecCondition=/bin/sh -c 'exec /usr/local/bin/rosy-update-gate'" in dropin
    for unit in ("deploy/robot/omx/rosy-omx-autoupdate.service", "deploy/model_pc/rosy-review-release-update.service",
                 "deploy/site/rosy-model-code-update.service"):
        assert "ExecCondition=/bin/sh -c 'exec /usr/local/bin/rosy-update-gate'" in (ROOT / unit).read_text(), unit
    common = (ROOT / "deploy/hosts/common/host-state/manifest").read_text()
    assert "safe file /usr/local/bin/rosy-update-gate common/rosy-update-gate 0755" in common
    for manifest, units in (("site", ("rosy-site-autoupdate", "rosy-docker-upgrade", "rosy-nightly-reboot")),
                            ("model_pc", ("rosy-nightly-reboot", "rosy-model-watch")),
                            ("ai_pc", ("rosy-nightly-reboot",))):
        text = (ROOT / f"deploy/{manifest}/host-state/manifest").read_text()
        for unit in units:
            assert (f"safe file /etc/systemd/system/{unit}.service.d/10-update-gate.conf "
                    "common/10-update-gate.conf") in text, (manifest, unit)
