"""The OMX updater switches to a trusted green main release only while the cell is idle, and rolls back."""
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
GREEN = {"ci-result": ("completed", "success", "github-actions")}


class FakeHost:
    def __init__(self, head="a" * 40, checks=None):
        self.head = head
        self.check_runs = dict(GREEN) if checks is None else checks
        self.busy = self.in_use = False
        self.torque_off = True
        self.descendant = self.signed = True
        self.lock_text = "lerobot==0.4.4\n"
        self.smoke_ok = {}
        self.archived, self.envs_built = [], []
        self.restarts, self.healthy = [], True
        self.stopped = set()

    def remote_head(self):
        return self.head

    def checks(self, sha):
        return self.check_runs

    def descends(self, base, head):
        return self.descendant

    def verified(self, sha):
        return self.signed

    def archive(self, sha, paths, target):
        self.archived.append(sha)
        lock = target / m.LOCK
        lock.parent.mkdir(parents=True)
        lock.write_text(self.lock_text)

    def build_env(self, lock, target):
        self.envs_built.append(lock.read_text() if lock else None)
        (target / "bin").mkdir(parents=True)
        (target / "bin" / "python").write_text("")

    def smoke(self, release, python):
        assert Path(os.path.realpath(python)).exists() or str(python).endswith("python")
        return self.smoke_ok.get(Path(os.path.realpath(release)).name.replace(".tmp", ""), True)

    def hold_session(self):
        if self.busy:
            return None
        host = self

        class Held:
            def close(self):
                host.held = False

        self.held = True
        return Held()

    def device_in_use(self):
        return self.in_use

    def running(self, units):
        return [u for u in units if u not in self.stopped]

    def restart(self, units):
        self.restarts.append(list(units))
        return self.healthy or not units

    def follower_torque_off(self, release, python):
        assert self.held, "the idle check runs while the session lock is held"
        return self.torque_off


def updater(tmp_path, host, **cfg):
    return m.Updater({"root": str(tmp_path), "required_checks": ["ci-result"], "paths": ["deploy"], "keep": 3,
                      **cfg}, host)


def current(tmp_path, link="current"):
    return os.readlink(tmp_path / link)


def test_a_green_release_is_prepared_with_its_environment_and_switched(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host)
    assert u.run() == "switched"
    assert current(tmp_path) == str(Path("releases") / ("a" * 12))
    assert current(tmp_path, "current-env").startswith("envs")
    assert (tmp_path / "releases" / ("a" * 12) / "RELEASE").read_text().strip() == "a" * 40
    state = u.state()
    assert state["current"] == "a" * 12 and state["current_sha"] == "a" * 40 and u.run() == "up_to_date"


@pytest.mark.parametrize("checks, result", [
    ({}, "waiting_ci"),
    ({"ci-result": ("in_progress", None, "github-actions")}, "waiting_ci"),
    ({"ci-result": ("completed", "failure", "github-actions")}, "ci_failed"),
    ({"ci-result": ("completed", "success", "someone-elses-app")}, "ci_failed"),  # not reported by Actions
])
def test_nothing_is_fetched_until_actions_reported_a_green_ci(tmp_path, checks, result):
    host = FakeHost(checks=checks)
    assert updater(tmp_path, host).run() == result
    assert host.archived == [] and not (tmp_path / "current").exists()


def test_a_commit_that_does_not_descend_from_the_installed_one_is_refused(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host)
    u.run()
    host.head, host.descendant = "b" * 40, False
    assert u.run() == "not_descendant" and host.archived == ["a" * 40]


def test_verified_commits_can_be_required(tmp_path):
    host = FakeHost()
    host.signed = False
    assert updater(tmp_path, host, require_verified_commit=True).run() == "unverified_commit"
    assert updater(tmp_path, host).run() == "switched"  # off by default


def test_the_environment_is_built_once_per_lock_and_rebuilt_when_it_changes(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host)
    u.run()
    host.head = "b" * 40
    u.run()
    assert len(host.envs_built) == 1  # same lock: reused
    host.head, host.lock_text = "c" * 40, "lerobot==0.4.5\n"
    u.run()
    assert len(host.envs_built) == 2 and u.state()["env"] != u.state()["previous_env"]


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


def flaky_smoke(passes):
    calls = {"n": 0}

    def smoke(release, python):
        calls["n"] += 1
        return calls["n"] <= passes

    return smoke


def test_a_release_that_fails_through_current_rolls_back_release_and_environment(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host)
    u.run()
    first_env = current(tmp_path, "current-env")
    host.head, host.lock_text = "b" * 40, "lerobot==0.4.5\n"
    host.smoke = flaky_smoke(1)  # passes in staging, fails once switched in
    assert u.run() == "rolled_back"
    assert current(tmp_path) == str(Path("releases") / ("a" * 12)) and current(tmp_path, "current-env") == first_env
    assert u.run() == "known_bad"  # not retried every timer tick
    assert not host.held


def test_a_broken_first_install_leaves_no_current(tmp_path):
    host = FakeHost()
    host.smoke = flaky_smoke(1)
    assert updater(tmp_path, host).run() == "rolled_back"
    assert not (tmp_path / "current").is_symlink() and not (tmp_path / "current-env").is_symlink()


def test_a_release_failing_its_smoke_check_is_discarded_and_not_refetched(tmp_path):
    host = FakeHost()
    host.smoke_ok["a" * 12] = False
    u = updater(tmp_path, host)
    assert u.run() == "smoke_failed"
    assert not (tmp_path / "releases" / ("a" * 12)).exists()
    assert u.run() == "known_bad" and host.archived == ["a" * 40]
    host.head = "b" * 40
    assert u.run() == "switched"  # a new main is tried again


def test_old_releases_and_unused_environments_are_pruned(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host)
    for index, letter in enumerate("abcde"):
        host.head, host.lock_text = letter * 40, f"pin=={index}\n"
        assert u.run() == "switched"
        os.utime(tmp_path / "releases" / (letter * 12), (0, index))
    kept = sorted(p.name for p in (tmp_path / "releases").iterdir())
    assert len(kept) == 3 and "e" * 12 in kept and "d" * 12 in kept
    assert len(list((tmp_path / "envs").iterdir())) == 2  # current and previous only


def test_a_manual_rollback_needs_an_idle_cell_and_restores_the_environment(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host)
    u.run()
    first_env = current(tmp_path, "current-env")
    host.head, host.lock_text = "b" * 40, "lerobot==0.4.5\n"
    u.run()
    host.in_use = True
    assert u.rollback() == "deferred"
    host.in_use = False
    assert u.rollback() == "rolled_back" and u.state()["current"] == "a" * 12
    assert current(tmp_path, "current-env") == first_env


def test_the_config_needs_its_sources_and_two_kept_releases(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path / "home"))
    path = tmp_path / "cfg.json"
    path.write_text('{"repo_url": "u", "github_repo": "o/r", "base_python": "p", "devices": ["d"], '
                    '"follower_device": "d", "keep": 1}')
    with pytest.raises(SystemExit):
        m.load_config(path)
    path.write_text('{"repo_url": "u", "github_repo": "o/r", "base_python": "p", "devices": ["d"]}')
    with pytest.raises(SystemExit):  # the follower device for the torque probe must be named
        m.load_config(path)
    path.write_text('{"repo_url": "u", "github_repo": "o/r", "base_python": "p", "devices": ["d"], '
                    '"follower_device": "d", "root": "elsewhere"}')
    with pytest.raises(SystemExit, match="session.lock"):  # a root the sessions do not lock
        m.load_config(path)
    path.write_text('{"repo_url": "u", "github_repo": "o/r", "base_python": "p", "devices": ["d"], '
                    '"follower_device": "d", "root": "%s"}' % (tmp_path / "home"))
    assert m.load_config(path)["required_checks"] == ["ci-result"]


def test_a_corrupt_state_file_is_kept_aside_and_rebuilt_from_the_links(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host)
    u.run()
    (tmp_path / "state.json").write_text("{not json")
    state = u.state()
    assert state["current"] == "a" * 12 and list(tmp_path.glob("state.corrupt-*"))


SERVICE = {"kind": "service", "lock": None, "units": ["rosy-situation.service"]}


def test_a_service_release_needs_no_cell_and_restarts_its_units_on_the_hosts_packages(tmp_path):
    host = FakeHost()
    host.in_use, host.torque_off, host.busy = True, False, False  # cell signals do not apply to a service
    u = updater(tmp_path, host, **SERVICE)
    assert u.run() == "switched"
    assert host.envs_built == [None] and host.restarts == [["rosy-situation.service"]]


def test_a_service_that_does_not_stay_active_is_rolled_back_and_restarted_on_the_previous_release(tmp_path):
    host = FakeHost()
    u = updater(tmp_path, host, **SERVICE)
    u.run()
    host.head, host.healthy = "b" * 40, False
    assert u.run() == "rolled_back"
    assert current(tmp_path) == str(Path("releases") / ("a" * 12))
    assert host.restarts[-2:] == [["rosy-situation.service"]] * 2  # the new one, then the previous one again
    assert u.run() == "known_bad"


def test_a_failed_first_service_install_puts_back_the_hand_deployed_current(tmp_path):
    (tmp_path / "abc123").mkdir()
    (tmp_path / "current").symlink_to(tmp_path / "abc123")
    host = FakeHost()
    host.healthy = False
    assert updater(tmp_path, host, **SERVICE).run() == "rolled_back"
    assert current(tmp_path) == str(tmp_path / "abc123") and not (tmp_path / "current-env").is_symlink()
    assert host.restarts == [["rosy-situation.service"]] * 2  # restarted again on the old code


def test_a_service_config_names_its_paths_smoke_units_and_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path / "home"))
    path = tmp_path / "cfg.json"
    base = '"kind": "service", "repo_url": "u", "github_repo": "o/r", "base_python": "p"'
    path.write_text("{%s, \"paths\": [\"x\"], \"smoke\": \"s\"}" % base)
    with pytest.raises(SystemExit, match="units"):
        m.load_config(path)
    path.write_text("{%s, \"paths\": [\"x\"], \"smoke\": \"s\", \"units\": [\"a.service\"], "
                    "\"root\": \"%s\"}" % (base, tmp_path / "situation"))
    cfg = m.load_config(path)  # no devices, and a root other than the cell's session.lock root
    assert cfg["lock"] is None and cfg["root"] == str(tmp_path / "situation")


def test_the_real_restart_installs_the_live_units_reloads_and_checks_they_stay_active(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    calls = tmp_path / "calls"
    fake = tmp_path / "bin" / "systemctl"
    fake.write_text('#!/bin/sh\necho "$*" >> "%s"\n[ "$3" != bad.service ]\n' % calls)
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    release = tmp_path / "root/releases/r1/deploy/ai_pc"
    release.mkdir(parents=True)
    (release / "svc.service").write_text("[Service]\nExecStart=/bin/true\n")
    (tmp_path / "root/current").symlink_to("releases/r1")
    (tmp_path / "units").mkdir()
    host = m.Host({"root": str(tmp_path / "root"), "settle": 0, "unit_dir": str(tmp_path / "units"),
                   "unit_files": ["deploy/ai_pc/svc.service"]})
    assert host.restart(["svc.service"])
    assert (tmp_path / "units/svc.service").read_text().startswith("[Service]")
    assert calls.read_text().splitlines() == ["--user daemon-reload", "--user restart svc.service",
                                               "--user is-active --quiet svc.service"]
    assert not host.restart(["bad.service"])  # the restart failed
    calls.write_text("")
    host.cfg["unit_files"] = ["deploy/ai_pc/missing.service", "deploy/ai_pc/svc.service"]
    assert not host.restart(["svc.service"])  # a release without its unit file is a failed switch ...
    assert calls.read_text().splitlines() == ["--user daemon-reload", "--user restart svc.service",
                                               "--user is-active --quiet svc.service"]  # ... yet still restarted
    calls.write_text("")
    fake.write_text('#!/bin/sh\necho "$*" >> "%s"\n[ "$2" = daemon-reload ] && sleep 120\nexit 0\n' % calls)
    monkeypatch.setattr(m.subprocess, "run", lambda args, **kw: real_run(args, **{**kw, "timeout": 2}))
    assert not host.restart(["svc.service"])  # a hung reload fails the switch but the restart still happens
    assert "--user restart svc.service" in calls.read_text().splitlines()


real_run = m.subprocess.run


def observed_host(tmp_path, monkeypatch, *, owners, pid='4242', active='active', torque=False, age=1.0, count=6):
    import json
    import subprocess as sp
    health = tmp_path / 'arm_a.json'
    now = 1000.0
    health.write_text(json.dumps(dict(expected_motor_count=6, observed_at=now - age,
                                      motors=[dict(torque_enabled=torque)] * count)))
    device = tmp_path / 'follower'
    device.write_text('')
    cfg = dict(devices=[str(device)], follower_device=str(device),
               observers=[dict(unit='rosy-omx-observer@arm_a.service', device=str(device), health=str(health))])

    def run(args, **kwargs):
        if args[0] == 'fuser':
            return sp.CompletedProcess(args, 0 if owners else 1, stdout=' '.join(owners), stderr='')
        return sp.CompletedProcess(args, 0, stdout=f'ActiveState={active}\nMainPID={pid}\n', stderr='')
    monkeypatch.setattr(m.subprocess, 'run', run)
    monkeypatch.setattr(m.time, 'time', lambda: now)
    return m.Host(cfg)


def test_the_torque_off_observer_alone_on_the_bus_counts_as_an_idle_cell(tmp_path, monkeypatch):
    host = observed_host(tmp_path, monkeypatch, owners=['4242'])
    assert host.device_in_use() is False
    assert host.follower_torque_off(tmp_path, tmp_path) is True
    assert host.follower_missing() is False


@pytest.mark.parametrize('kwargs', [dict(owners=['4242', '999']), dict(owners=['999']),
                                    dict(owners=['4242'], active='inactive')])
def test_any_other_bus_owner_is_still_a_running_session(tmp_path, monkeypatch, kwargs):
    assert observed_host(tmp_path, monkeypatch, **kwargs).device_in_use() is True


@pytest.mark.parametrize('kwargs', [dict(torque=True), dict(age=30.0), dict(count=5)])
def test_stale_partial_or_torque_on_snapshots_never_admit_a_switch(tmp_path, monkeypatch, kwargs):
    assert observed_host(tmp_path, monkeypatch, owners=['4242'], **kwargs).follower_torque_off(tmp_path, tmp_path) is False


def test_a_replaced_follower_board_is_reported_as_missing_not_as_torque_on(tmp_path):
    host = m.Host(dict(devices=[], follower_device=str(tmp_path / 'gone')))
    assert host.follower_missing() is True


def test_a_missing_follower_board_defers_with_its_own_reason(tmp_path, capsys):
    host = FakeHost()
    host.follower_missing = lambda: True
    assert updater(tmp_path, host).run() == "deferred"
    assert "follower_device_missing" in capsys.readouterr().out


def test_a_killed_fetch_lock_in_the_mirror_does_not_block_the_next_archive(tmp_path):
    import subprocess as sp
    source = tmp_path / "source"
    (source / "deploy").mkdir(parents=True)
    (source / "deploy" / "tool.py").write_text("print(1)\n")
    git = ["git", "-C", str(source), "-c", "user.email=t@t", "-c", "user.name=t"]
    sp.run(["git", "init", "-q", str(source)], check=True)
    sp.run(git + ["add", "."], check=True)
    sp.run(git + ["commit", "-qm", "c"], check=True)
    sp.run(git + ["config", "uploadpack.allowReachableSHA1InWant", "true"], check=True)
    sha = sp.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    root = tmp_path / "root"
    root.mkdir()
    sp.run(["git", "init", "--bare", "-q", str(root / "mirror.git")], check=True)
    (root / "mirror.git" / "shallow.lock").write_text("left by a killed fetch")
    target = tmp_path / "release"
    target.mkdir()
    m.Host({"root": str(root), "repo_url": "file://" + str(source)}).archive(sha, ["deploy"], target)
    assert (target / "deploy" / "tool.py").read_text() == "print(1)\n"


def test_failed_preparations_of_older_releases_are_removed(tmp_path):
    host = FakeHost()
    (tmp_path / "releases" / "0123456789ab.tmp").mkdir(parents=True)
    assert updater(tmp_path, host).run() == "switched"
    assert not list((tmp_path / "releases").glob("*.tmp"))


CELL_SERVICE = {"kind": "service", "lock": "deploy/robot/omx/requirements-cell.lock", "idle_gate": "cell",
                "units": ["rosy-omx-observer@arm_a.service"]}


@pytest.mark.parametrize("busy, reason", [({"busy": True}, "session_running"), ({"in_use": True}, "device_in_use"),
                                          ({"torque_off": False}, "follower_torque_not_off")])
def test_a_cell_gated_service_waits_for_the_idle_cell_like_the_cell_tools(tmp_path, busy, reason, capsys):
    host = FakeHost()
    for key, value in busy.items():
        setattr(host, key, value)
    assert updater(tmp_path, host, **CELL_SERVICE).run() == "deferred"
    assert reason in capsys.readouterr().out and host.restarts == []


def test_the_cell_lock_is_released_before_the_units_restart(tmp_path):
    host = FakeHost()
    locked_at_restart = []
    restart = host.restart
    host.restart = lambda units: locked_at_restart.append(host.held) or restart(units)
    assert updater(tmp_path, host, **CELL_SERVICE).run() == "switched"
    assert locked_at_restart == [False]  # the observer's start guard takes the same lock


def test_a_cell_gated_service_config_names_the_cells_devices_and_takes_its_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path / "home"))
    path = tmp_path / "cfg.json"
    base = ('"kind": "service", "repo_url": "u", "github_repo": "o/r", "base_python": "p", "paths": ["x"], '
            '"smoke": "s", "units": ["a.service"], "root": "%s", "idle_gate": "cell"' % (tmp_path / "devices"))
    path.write_text("{%s}" % base)
    with pytest.raises(SystemExit, match="devices"):
        m.load_config(path)
    path.write_text('{%s, "devices": ["d"]}' % base)
    with pytest.raises(SystemExit, match="observers or follower_device"):
        m.load_config(path)
    path.write_text('{%s, "devices": ["d"], "observers": [{"unit": "o", "device": "d", "health": "h"}]}' % base)
    assert m.load_config(path)["session_lock"] == str(tmp_path / "home" / "session.lock")
    path.write_text('{%s}' % base.replace('"cell"', '"other"'))
    with pytest.raises(SystemExit, match="idle_gate"):
        m.load_config(path)


@pytest.mark.parametrize("system, expected", [(True, ["--system-site-packages"]), (False, [])])
def test_a_locked_env_may_build_over_the_host_pythons_packages(tmp_path, monkeypatch, system, expected):
    calls = []
    monkeypatch.setattr(m.subprocess, "run", lambda args, **kw: calls.append(args))
    lock = tmp_path / "lock"
    lock.write_text("pyserial==3.5\n")
    m.Host({"base_python": "py", "system_site_packages": system}).build_env(lock, tmp_path / "env")
    assert calls[0] == ["py", "-m", "venv", *expected, str(tmp_path / "env")] and "-r" in calls[1]


def test_only_running_units_are_selected_so_a_hand_stopped_observer_stays_stopped(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    fake = tmp_path / "bin" / "systemctl"
    # observer@arm_b was stopped by hand for an owner handover: is-active fails for it
    fake.write_text('#!/bin/sh\ncase "$*" in *arm_b*) exit 3;; esac\nexit 0\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    units = ["rosy-omx-observer@arm_a.service", "rosy-omx-observer@arm_b.service"]
    assert m.Host({"restart_running_only": True}).running(units) == units[:1]
    assert m.Host({}).running(units) == units


def test_a_rollback_restarts_the_units_that_ran_before_the_switch_even_if_they_died(tmp_path):
    host = FakeHost()
    host.stopped = {"rosy-omx-camera@front.service"}
    u = updater(tmp_path, host, **{**CELL_SERVICE, "units": ["rosy-omx-observer@arm_a.service",
                                                               "rosy-omx-camera@front.service"]})
    u.run()
    host.head, host.healthy = "b" * 40, False
    assert u.run() == "rolled_back"
    assert host.restarts[-2:] == [["rosy-omx-observer@arm_a.service"]] * 2  # never the hand-stopped camera


@pytest.mark.parametrize("cfg", [{}, CELL_SERVICE], ids=["cell", "cell_gated_service"])
def test_a_release_failing_smoke_through_current_is_unlinked_before_the_lock_goes(tmp_path, cfg):
    host = FakeHost()
    u = updater(tmp_path, host, **cfg)
    u.run()
    held_at_relink = []
    relink = u.relink
    u.relink = lambda *a: held_at_relink.append(host.held) or relink(*a)
    host.head, host.smoke = "b" * 40, flaky_smoke(1)
    assert u.run() == "rolled_back"
    assert held_at_relink == [True]  # no session can start on the broken release


def test_a_service_without_the_cell_gate_restarts_under_its_own_lock_as_before(tmp_path):
    host = FakeHost()
    locked_at_restart = []
    restart = host.restart
    host.restart = lambda units: locked_at_restart.append(host.held) or restart(units)
    assert updater(tmp_path, host, **SERVICE).run() == "switched"
    assert locked_at_restart == [True]


def test_a_session_that_starts_during_the_restart_defers_instead_of_condemning_the_release(tmp_path, capsys):
    host = FakeHost()
    u = updater(tmp_path, host, **CELL_SERVICE)
    u.run()
    host.head, host.healthy = "b" * 40, False
    hold = host.hold_session
    calls = []
    host.hold_session = lambda: calls.append(1) or (None if len(calls) == 2 else hold())
    assert u.run() == "deferred"  # the observer refused to start because the session took the cell
    assert "session_started_during_restart" in capsys.readouterr().out
    assert current(tmp_path) == str(Path("releases") / ("a" * 12))
    host.healthy = True
    assert u.run() == "switched"  # retried, not known_bad


def test_a_host_python_without_ensurepip_builds_the_env_with_uv(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(m.subprocess, "run", lambda args, **kw: calls.append(args))
    lock = tmp_path / "lock"
    lock.write_text("pyserial==3.5\n")
    m.Host({"base_python": "/usr/bin/python3", "system_site_packages": True, "uv": "/opt/uv"}).build_env(
        lock, tmp_path / "env")
    assert calls[0] == ["/opt/uv", "venv", "-q", "--python", "/usr/bin/python3", "--system-site-packages",
                        str(tmp_path / "env")]
    assert calls[1] == ["/opt/uv", "pip", "install", "-q", "--python", str(tmp_path / "env" / "bin" / "python"),
                        "-r", str(lock)]
