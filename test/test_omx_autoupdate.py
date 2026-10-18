"""The OMX updater switches to a green main release only while the cell is idle, and rolls back."""
import importlib.util
import os
from pathlib import Path
import sys

import pytest


def module():
    directory = Path(__file__).parents[1] / "deploy/robot/omx"
    spec = importlib.util.spec_from_file_location("omx_autoupdate", directory / "omx_autoupdate.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


m = module()
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl/symlink host tool")


class FakeHost:
    def __init__(self, head="a" * 40, checks=None):
        self.head = head
        self.check_runs = {"ci-result": ("completed", "success")} if checks is None else checks
        self.busy = self.in_use = False
        self.torque_off = True
        self.smoke_ok = {}
        self.archived = []

    def remote_head(self):
        return self.head

    def checks(self, sha):
        return self.check_runs

    def archive(self, sha, paths, target):
        self.archived.append(sha)
        (target / "deploy").mkdir()

    def smoke(self, release):
        return self.smoke_ok.get(Path(os.path.realpath(release)).name.replace(".tmp", ""), True)

    def session_busy(self):
        return self.busy

    def device_in_use(self):
        return self.in_use

    def follower_torque_off(self, release):
        return self.torque_off


def updater(tmp_path, host):
    cfg = {"root": str(tmp_path), "required_checks": ["ci-result"], "paths": ["deploy"], "keep": 3}
    return m.Updater(cfg, host)


def current(tmp_path):
    return os.readlink(tmp_path / "current")


def test_a_green_release_is_prepared_switched_and_recorded(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host)
    assert u.run() == "switched"
    assert current(tmp_path) == str(Path("releases") / ("a" * 12))
    assert (tmp_path / "releases" / ("a" * 12) / "RELEASE").read_text().strip() == "a" * 40
    assert u.state()["current"] == "a" * 12 and u.run() == "up_to_date"


@pytest.mark.parametrize("checks, result", [
    ({}, "waiting_ci"),
    ({"ci-result": ("in_progress", None)}, "waiting_ci"),
    ({"ci-result": ("completed", "failure")}, "ci_failed"),
])
def test_nothing_is_fetched_until_ci_passed(tmp_path, checks, result):
    host = FakeHost(checks=checks)
    assert updater(tmp_path, host).run() == result
    assert host.archived == [] and not (tmp_path / "current").exists()


@pytest.mark.parametrize("busy, reason", [
    ({"busy": True}, "session_running"), ({"in_use": True}, "device_in_use"),
    ({"torque_off": False}, "follower_torque_not_off"),
])
def test_a_busy_cell_defers_the_switch_and_keeps_the_prepared_release(tmp_path, busy, reason, capsys):
    host = FakeHost()
    for key, value in busy.items():
        setattr(host, key, value)
    u = updater(tmp_path, host)
    assert u.run() == "deferred" and reason in capsys.readouterr().out
    assert (tmp_path / "releases" / ("a" * 12)).is_dir() and not (tmp_path / "current").exists()
    for key in busy:
        setattr(host, key, {"busy": False, "in_use": False, "torque_off": True}[key])
    assert u.run() == "switched" and host.archived == ["a" * 40]  # not fetched twice


def test_a_release_that_fails_through_current_rolls_back_to_the_previous(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host)
    u.run()
    host.head = "b" * 40
    calls = {"n": 0}

    def smoke(release):  # passes in staging, fails once switched in
        calls["n"] += 1
        return calls["n"] == 1

    host.smoke = smoke
    assert u.run() == "rolled_back"
    assert current(tmp_path) == str(Path("releases") / ("a" * 12)) and u.state()["current"] == "a" * 12


def test_a_broken_first_install_leaves_no_current(tmp_path):
    host = FakeHost()
    calls = {"n": 0}

    def smoke(release):
        calls["n"] += 1
        return calls["n"] == 1

    host.smoke = smoke
    assert updater(tmp_path, host).run() == "rolled_back"
    assert not (tmp_path / "current").exists() and not (tmp_path / "current").is_symlink()


def test_a_release_failing_its_smoke_check_is_discarded(tmp_path):
    host = FakeHost()
    host.smoke_ok["a" * 12] = False
    assert updater(tmp_path, host).run() == "smoke_failed"
    assert not (tmp_path / "releases" / ("a" * 12)).exists()


def test_old_releases_are_pruned_but_current_and_previous_stay(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host)
    for letter in "abcde":
        host.head = letter * 40
        assert u.run() == "switched"
        os.utime(tmp_path / "releases" / (letter * 12), (0, "abcde".index(letter)))
    kept = sorted(p.name for p in (tmp_path / "releases").iterdir())
    assert len(kept) == 3 and "e" * 12 in kept and "d" * 12 in kept


def test_a_manual_rollback_needs_an_idle_cell(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host)
    u.run()
    host.head = "b" * 40
    u.run()
    host.in_use = True
    assert u.rollback() == "deferred"
    host.in_use = False
    assert u.rollback() == "rolled_back" and u.state()["current"] == "a" * 12


def test_the_config_needs_its_sources_and_two_kept_releases(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text('{"repo_url": "u", "github_repo": "o/r", "python": "p", "devices": ["d"], "keep": 1}')
    with pytest.raises(SystemExit):
        m.load_config(path)
    path.write_text('{"repo_url": "u", "github_repo": "o/r", "python": "p", "devices": ["d"]}')
    assert m.load_config(path)["required_checks"] == ["ci-result"]
