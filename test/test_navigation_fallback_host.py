"""SLAM fallback host half on a device tree with no real system calls (2026-11-18: the switch is automatic)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"))
import navigation_fallback_host as host  # noqa: E402

RUNTIME = "ROSY_RUNTIME_MODE=hardware\nROSY_NAVIGATION_BACKEND=slam\nROSY_MAP=/var/lib/rosy/maps/site.yaml\n"
COMMIT = "<the commit step>"


def pgm(width=8, height=6):
    return f"P5\n{width} {height}\n255\n".encode() + bytes([254]) * (width * height)


class Ops:
    def __init__(self, root, fail=None, active_after_restart=True):
        self.root, self.calls, self.commits, self.spawned = root, [], [], []
        self.fail, self.units, self.active_after_restart = fail, set(), active_after_restart
        self.t, self.boot = 1000.0, "boot-a"

    def run(self, *argv, timeout=120):
        self.calls.append(argv)
        failed = self.fail is not None and self.fail in " ".join(map(str, argv))
        if not failed and argv[:2] == ("systemctl", "restart") and self.active_after_restart:
            self.units.add(argv[2])
        return subprocess.CompletedProcess(argv, 1 if failed else 0, "", "boom" if failed else "")

    def now(self):
        return self.t

    def wall(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds

    def boot_id(self):
        return self.boot

    def spawn(self, action, *arguments):
        self.spawned.append((action, *arguments))
        return subprocess.CompletedProcess([], 0, "", "")

    def active(self, unit):
        return unit in self.units

    def commit(self, root, new, old):  # the only writer of runtime.env, as in the real SystemOps
        if self.fail == COMMIT:
            self.fail = None
            raise ValueError("commit failed")
        assert (root / host.RUNTIME).read_bytes() == old
        self.commits.append(new)
        (root / host.RUNTIME).write_bytes(new)

    def restarts(self):
        return [c for c in self.calls if c[:2] == ("systemctl", "restart")]


def spool(root, content=None, version=3, **meta):
    content = pgm() if content is None else content
    folder = root / host.SPOOL
    folder.mkdir(parents=True, exist_ok=True)
    (folder / host.SPOOL_IMAGE).write_bytes(content)
    (folder / host.SPOOL_META).write_text(json.dumps({
        "map_id": "site-a", "version": version, "resolution": 0.025, "origin": [-0.1, -0.1, 0.0],
        "sha256": hashlib.sha256(content).hexdigest(), **meta}), encoding="utf-8")


def stopped(root, ops, zero_for=2.5, goal_active=False, age=0.5, boot=None):
    (root / host.STOP_EVIDENCE).parent.mkdir(parents=True, exist_ok=True)
    (root / host.STOP_EVIDENCE).write_text(json.dumps({
        "written_at": ops.t - age, "zero_since": None if zero_for is None else ops.t - age - zero_for,
        "goal_active": goal_active, "boot_id": boot or ops.boot}), encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    (tmp_path / "etc/rosy").mkdir(parents=True)
    (tmp_path / host.RUNTIME).write_text(RUNTIME, encoding="utf-8")
    return tmp_path


@pytest.fixture
def ready(root):
    ops = Ops(root)
    spool(root)
    host.stage(root, ops)
    stopped(root, ops)
    return root, ops


def test_stage_installs_a_loadable_pair_under_the_wall_name_and_never_touches_site_yaml(root):
    ops = Ops(root)
    spool(root)
    assert host.stage(root, ops) == {"staged": "wall_site-a_v3"}
    maps = root / host.MAPS
    assert host._loadable(maps / "wall_site-a_v3.yaml") and not (maps / "site.yaml").exists()
    assert host._wall_map(root)["yaml"].endswith("/wall_site-a_v3.yaml")


def test_stage_keeps_the_last_good_map_and_drops_older_ones(root):
    ops = Ops(root)
    for version in (1, 2, 3):
        spool(root, version=version)
        host.stage(root, ops)
    names = sorted(p.name for p in (root / host.MAPS).glob("wall_*"))
    assert names == ["wall_site-a_v2.pgm", "wall_site-a_v2.yaml", "wall_site-a_v3.pgm", "wall_site-a_v3.yaml"]


@pytest.mark.parametrize("meta,content", [({"sha256": "0" * 64}, None), ({"map_id": "../x"}, None),
                                          ({}, b"P6\n8 6\n255\n" + bytes(144)), ({}, pgm()[:-1]),
                                          ({"resolution": 0}, None), ({"resolution": 0.5}, None),
                                          ({"origin": [float("inf"), 0.0, 0.0]}, None),
                                          ({"origin": [float("nan"), 0.0, 0.0]}, None), ({"origin": [5000.0, 0.0, 0.0]}, None)])
def test_stage_refuses_a_map_that_does_not_check_out(root, meta, content):
    spool(root, content, **meta)
    with pytest.raises(ValueError, match="wall map refused"):
        host.stage(root, Ops(root))
    assert not (root / host.MAPS / host.POINTER).exists()


def test_switch_is_refused_while_the_robot_is_not_confirmed_stopped(ready):
    root, ops = ready
    for kwargs in ({"zero_for": 1.0}, {"zero_for": None}, {"goal_active": True}, {"age": 5.0}, {"age": -1.0},
                   {"boot": "boot-other"}):
        stopped(root, ops, **kwargs)
        with pytest.raises(ValueError, match="not confirmed stopped"):
            host.request_switch(root, ops, "slam_lost")
    (root / host.STOP_EVIDENCE).unlink()
    with pytest.raises(ValueError, match="not confirmed stopped"):
        host.request_switch(root, ops, "slam_lost")
    assert ops.spawned == [] and ops.commits == []


def test_switch_is_refused_without_a_staged_map_or_with_a_changed_image(ready):
    root, ops = ready
    pointer = host._wall_map(root)
    (root / host.MAPS / f"{pointer['stem']}.pgm").write_bytes(pgm(8, 6)[:-1] + b"\x00")  # same size, other bytes
    with pytest.raises(ValueError, match="matching sha256"):
        host.request_switch(root, ops, "slam_lost")
    (root / host.MAPS / host.POINTER).unlink()
    with pytest.raises(ValueError, match="matching sha256"):
        host.request_switch(root, ops, "slam_lost")
    assert ops.spawned == []


def test_there_is_no_switch_back_and_no_switch_from_a_localization_backend(ready):
    root, ops = ready
    (root / host.RUNTIME).write_text(RUNTIME.replace("=slam", "=localization"), encoding="utf-8")
    with pytest.raises(ValueError, match="never back to slam"):
        host.request_switch(root, ops, "slam_lost")
    assert ops.spawned == []


def test_a_switch_commits_through_commit_runtime_and_restarts_only_navigation(ready):
    root, ops = ready
    host.request_switch(root, ops, "slam_lost")
    assert ops.spawned == [("switch", "slam_lost")] and host.status(root, ops)["phase"] == "SWITCHING"
    host.switch(root, ops, "slam_lost")
    env = (root / host.RUNTIME).read_text(encoding="utf-8")
    assert "ROSY_NAVIGATION_BACKEND=localization" in env and "ROSY_RUNTIME_MODE=hardware" in env
    assert f"ROSY_MAP=/{host.MAPS}/wall_site-a_v3.yaml" in env and "ROSY_ENABLE_LOC_ASSIST=true" in env
    assert len(ops.commits) == 1 and ops.restarts() == [("systemctl", "restart", "rosy-navigation.service")]
    assert host.status(root, ops)["phase"] == "SWITCHED"


def test_a_failed_restart_rolls_back_to_the_slam_runtime(ready):
    root, ops = ready
    ops.fail = "restart rosy-navigation"
    host.switch(root, ops, "slam_lost")
    assert (root / host.RUNTIME).read_text(encoding="utf-8") == RUNTIME and len(ops.commits) == 2
    state = host.status(root, ops)
    assert state["phase"] == "FAILED" or state["phase"] == "ROLLED_BACK"
    assert "boom" in json.loads((root / host.STATE).read_text(encoding="utf-8"))["reason"] or state["phase"] == "FAILED"


def test_a_navigation_that_never_becomes_active_rolls_back(ready):
    root, ops = ready
    ops.active_after_restart = False
    host.switch(root, ops, "slam_lost")
    assert (root / host.RUNTIME).read_text(encoding="utf-8") == RUNTIME
    assert host.status(root, ops)["phase"] == "ROLLED_BACK" and len(ops.restarts()) == 2


def test_a_failed_commit_leaves_the_runtime_untouched(ready):
    root, ops = ready
    ops.fail = COMMIT
    host.switch(root, ops, "slam_lost")
    assert (root / host.RUNTIME).read_text(encoding="utf-8") == RUNTIME and ops.commits == []
    assert host.status(root, ops)["phase"] == "ROLLED_BACK"


def test_one_attempt_per_boot_even_after_a_rollback_until_a_person_resets(ready):
    root, ops = ready
    ops.fail = COMMIT
    host.switch(root, ops, "slam_lost")
    stopped(root, ops)
    with pytest.raises(ValueError, match="already attempted in this boot"):
        host.request_switch(root, ops, "slam_lost")
    ops.boot = "boot-b"
    stopped(root, ops)  # the evidence is of the boot it is read in
    host.request_switch(root, ops, "slam_lost")  # a new boot is a new chance
    ops.boot = "boot-a"
    host.reset(root)
    stopped(root, ops)
    host.request_switch(root, ops, "slam_lost")


def test_a_second_request_is_refused_while_a_switch_runs(ready):
    root, ops = ready
    host.request_switch(root, ops, "slam_lost")
    with pytest.raises(ValueError, match="already running"):
        host.request_switch(root, ops, "slam_lost")


def test_the_unit_rechecks_the_stop_evidence_itself(ready):
    root, ops = ready
    host.request_switch(root, ops, "slam_lost")
    ops.t += 10.0  # the evidence is old by the time the unit starts: the robot may be moving again
    host.switch(root, ops, "slam_lost")
    assert ops.commits == [] and host.status(root, ops)["phase"] == "REFUSED"


def test_a_unit_that_ended_without_a_result_reads_as_failed(ready):
    root, ops = ready
    host.request_switch(root, ops, "slam_lost")
    ops.t += host.UNIT_START_S + 1
    assert host.status(root, ops)["phase"] == "FAILED"


def test_a_switch_left_running_by_another_boot_is_failed_and_not_busy(ready):
    root, ops = ready
    host.request_switch(root, ops, "slam_lost")
    ops.boot = "boot-b"  # the machine rebooted under the unit
    assert host.status(root, ops)["phase"] == "FAILED"
    stopped(root, ops)
    host.request_switch(root, ops, "slam_lost")  # not "already running": a new boot is a new chance (the gate still decides)


def test_the_evidence_must_be_a_plain_file_that_cannot_be_forged_by_a_link_or_a_size(ready):
    root, ops = ready
    evidence = root / host.STOP_EVIDENCE
    evidence.write_bytes(evidence.read_bytes() + b" " * host.EVIDENCE_MAX)  # too large
    with pytest.raises(ValueError, match="not confirmed stopped"):
        host.request_switch(root, ops, "slam_lost")
    stopped(root, ops)
    real = evidence.with_name("real.json")
    evidence.rename(real)
    try:
        os.symlink(real, evidence)
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    with pytest.raises(ValueError, match="not confirmed stopped"):
        host.request_switch(root, ops, "slam_lost")
    evidence.unlink()
    real.rename(evidence)
    if os.name == "posix":
        evidence.chmod(0o666)  # writable by anyone
        with pytest.raises(ValueError, match="not confirmed stopped"):
            host.request_switch(root, ops, "slam_lost")
        evidence.chmod(0o644)
    host.request_switch(root, ops, "slam_lost")


def test_a_refused_unit_still_counts_as_the_attempt_of_this_boot(ready):
    root, ops = ready
    host.request_switch(root, ops, "slam_lost")
    ops.t += 10.0  # the evidence is old by the time the unit starts
    host.switch(root, ops, "slam_lost")
    state = json.loads((root / host.STATE).read_text(encoding="utf-8"))
    assert state["phase"] == "REFUSED" and state["attempt_boot_id"] == "boot-a"
    stopped(root, ops)
    with pytest.raises(ValueError, match="already attempted in this boot"):
        host.request_switch(root, ops, "slam_lost")
    assert host.status(root, ops)["attempted_this_boot"] is True


def test_the_state_file_never_holds_runtime_env_and_the_backup_goes_away_with_the_attempt(ready):
    root, ops = ready
    host.request_switch(root, ops, "slam_lost")
    state_path, backup = root / host.STATE, root / host.RUNTIME_BACKUP
    host.switch(root, ops, "slam_lost")
    assert "ROSY_RUNTIME_MODE" not in state_path.read_text(encoding="utf-8") and not backup.exists()
    if os.name == "posix":
        assert state_path.stat().st_mode & 0o777 == 0o600
    ops2 = Ops(root, active_after_restart=False)  # restarts fine but never becomes active: rolled back
    stopped(root, ops2)
    (root / host.RUNTIME).write_text(RUNTIME, encoding="utf-8")
    host.reset(root)
    host.switch(root, ops2, "slam_lost")
    assert json.loads(state_path.read_text(encoding="utf-8"))["phase"] == "ROLLED_BACK"
    assert not backup.exists() and "ROSY_RUNTIME_MODE" not in state_path.read_text(encoding="utf-8")
    assert (root / host.RUNTIME).read_text(encoding="utf-8") == RUNTIME  # rolled back to the saved bytes


@pytest.mark.parametrize("reason", ["", "Slam Lost", "slam_lost; reboot", "-x", "x" * 80])
def test_the_reason_must_be_an_identifier(ready, reason):
    root, ops = ready
    with pytest.raises(ValueError, match="identifier"):
        host.request_switch(root, ops, reason)
    assert ops.spawned == []


def test_the_unit_is_started_with_dashes_before_its_arguments(root):
    seen = []

    class Recording(host.SystemOps):
        def run(self, *argv, timeout=120):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

    Recording().spawn("switch", "slam_lost")
    argv = seen[0]
    assert argv[-3:] == ("switch", "--", "slam_lost") and argv[0] == "systemd-run"
    args = host.argparse.ArgumentParser()
    commands = args.add_subparsers(dest="command")
    run = commands.add_parser("run")
    run.add_argument("action")
    run.add_argument("arguments", nargs="*")
    assert args.parse_args(["run", "switch", "--", "-x"]).arguments == ["-x"]


def test_stage_is_refused_while_a_switch_runs(ready):
    root, ops = ready
    host.request_switch(root, ops, "slam_lost")
    spool(root, version=9)
    with pytest.raises(ValueError, match="switch is running"):
        host.stage(root, ops)
    assert host._wall_map(root)["stem"] == "wall_site-a_v3"


def test_stage_never_deletes_the_map_the_runtime_names_even_after_many_pushes(root):
    ops = Ops(root)
    for version in (1, 2):
        spool(root, version=version)
        host.stage(root, ops)
    (root / host.RUNTIME).write_text(RUNTIME.replace("/var/lib/rosy/maps/site.yaml", f"/{host.MAPS}/wall_site-a_v2.yaml"),
                                     encoding="utf-8")
    for version in (3, 4, 5):  # Fleet pushes again whenever the active site map version changes
        spool(root, version=version)
        host.stage(root, ops)
    names = sorted(p.name for p in (root / host.MAPS).glob("wall_*"))
    assert "wall_site-a_v2.pgm" in names and "wall_site-a_v2.yaml" in names
    assert "wall_site-a_v1.pgm" not in names and "wall_site-a_v3.pgm" not in names and "wall_site-a_v5.pgm" in names


def test_stage_does_not_change_bytes_under_the_running_map_and_does_nothing_when_nothing_changed(root):
    ops = Ops(root)
    spool(root, version=2)
    host.stage(root, ops)
    image = root / host.MAPS / "wall_site-a_v2.pgm"
    before = image.stat().st_mtime_ns
    spool(root, version=2)
    host.stage(root, ops)  # identical: nothing is rewritten
    assert image.stat().st_mtime_ns == before
    (root / host.RUNTIME).write_text(RUNTIME.replace("/var/lib/rosy/maps/site.yaml", f"/{host.MAPS}/wall_site-a_v2.yaml"),
                                     encoding="utf-8")
    spool(root, pgm(9, 6), version=2)  # same name, other bytes, while the running navigation uses it
    with pytest.raises(ValueError, match="running navigation uses this name"):
        host.stage(root, ops)
    assert image.read_bytes() == pgm()
    assert not [p for p in (root / host.MAPS).iterdir() if p.name.startswith("tmp")]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlinks here")
def test_stage_refuses_a_spool_that_is_a_link_or_too_big(root):
    ops = Ops(root)
    spool(root)
    target = root / "elsewhere.pgm"
    target.write_bytes(pgm())
    image = root / host.SPOOL / host.SPOOL_IMAGE
    image.unlink()
    try:
        os.symlink(target, image)
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    with pytest.raises(ValueError, match="wall map refused"):
        host.stage(root, ops)
    image.unlink()
    (root / host.SPOOL / host.SPOOL_META).write_bytes(b" " * (host.META_MAX + 1))
    image.write_bytes(pgm())
    with pytest.raises(ValueError, match="wall map refused"):
        host.stage(root, ops)
