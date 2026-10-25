"""D-871: the Learning center follows green main only while running and idle, and restores its unit."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("learning_center_update", ROOT / "deploy/model_pc/learning_center_update.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
GREEN = {"ci-result": ("completed", "success", "github-actions")}
OLD, NEW = "a" * 40, "b" * 40


def unit(sha, port=8769):
    return ("[Service]\n"
            f'ExecStartPre="/venv/bin/python" "/src/{sha}/deploy/model_pc/install_learning_center.py" '
            f'"--source-root" "/src/{sha}" "--commit" "{sha}" "--state" "/state" "--center-config" "/cfg.json" '
            f'"--python" "/venv/bin/python" "--port" "{port}"\n'
            f'ExecStart="/venv/bin/python" "/src/{sha}/learning/curation/perception/review_app.py"\n')


class FakeHost:
    def __init__(self, tmp_path):
        self.unit_path = tmp_path / "units" / m.SERVICE
        self.unit_path.parent.mkdir()
        self.unit_path.write_text(unit(OLD))
        self.head, self.check_runs, self.descendant = NEW, dict(GREEN), True
        self.running, self.job = True, None
        self.stop_rc, self.raise_in = 0, None
        self.apply_ok = self.health_ok = True
        self.calls = []

    def remote_head(self): return self.head
    def checks(self, sha): return self.check_runs
    def descends(self, base, head): return self.descendant
    def unit_text(self): return self.unit_path.read_text() if self.unit_path.exists() else None
    def write_unit(self, text): self.unit_path.write_text(text)
    def running_center(self): return self.running
    def busy(self): return self.job

    def systemctl(self, *args):
        self.calls.append(("systemctl", *args))
        return self.stop_rc if args[0] == "stop" else 0

    def fetch(self, sha, target):
        self.calls.append(("fetch", sha))
        target.mkdir(parents=True)

    def render(self, source, args, sha):
        assert args["--state"] == "/state" and args["--port"] == "8769" and args["python"] == "/venv/bin/python"
        return unit(sha)

    def apply(self, source, args, sha):
        self.calls.append(("apply", sha, self.unit_path.read_text() == unit(sha)))
        if self.raise_in == "apply":
            raise m.subprocess.TimeoutExpired("installer", 600)
        return self.apply_ok

    def healthy(self, sha, port):
        self.calls.append(("healthy", sha, port))
        return self.health_ok


def updater(tmp_path, host):
    return m.Updater({"required_checks": ["ci-result"], "source_root": str(tmp_path / "src"),
                      "state_file": str(tmp_path / "state.json")}, host)


def test_a_green_descendant_moves_the_idle_center_with_the_new_installers_exact_unit_first(tmp_path):
    host = FakeHost(tmp_path)
    assert updater(tmp_path, host).run() == "switched"
    order = [c[0] for c in host.calls]
    assert order == ["fetch", "systemctl", "apply", "healthy"] and host.calls[1] == ("systemctl", "stop", m.SERVICE)
    assert host.calls[2] == ("apply", NEW, True)  # the new unit is written before the installer runs
    assert list(host.unit_path.parent.glob(m.SERVICE + ".bak-aaaaaaaaaa-*"))[0].read_text() == unit(OLD)
    assert updater(tmp_path, host).run() == "up_to_date"


@pytest.mark.parametrize("change, step", [
    (dict(running=False), "idle"),  # stopped or disabled by hand: never started from here
    (dict(job="center_job_running"), "held"),
    (dict(head=OLD), "up_to_date"),
    (dict(check_runs={}), "waiting_ci"),
    (dict(check_runs={"ci-result": ("completed", "failure", "github-actions")}), "ci_failed"),
    (dict(check_runs={"ci-result": ("completed", "success", "other-app")}), "ci_failed"),
    (dict(descendant=False), "not_descendant"),
])
def test_nothing_is_touched_unless_the_center_runs_idle_on_a_trusted_newer_commit(tmp_path, change, step):
    host = FakeHost(tmp_path)
    for key, value in change.items():
        setattr(host, key, value)
    assert updater(tmp_path, host).run() == step
    assert host.calls == [] and host.unit_path.read_text() == unit(OLD)


@pytest.mark.parametrize("failure", ["apply_ok", "health_ok"])
def test_a_failed_install_or_health_check_restores_the_backup_unit_and_is_not_retried(tmp_path, failure):
    host = FakeHost(tmp_path)
    setattr(host, failure, False)
    u = updater(tmp_path, host)
    assert u.run() == "rolled_back"
    assert host.unit_path.read_text() == unit(OLD)
    # restart, not start: the installer may already have started the new code under the restored unit
    assert host.calls[-2:] == [("systemctl", "daemon-reload"), ("systemctl", "restart", m.SERVICE)]
    host.calls.clear()
    assert u.run() == "known_bad" and host.calls == []
    host.head = "c" * 40
    setattr(host, failure, True)
    assert u.run() == "switched"  # main moved on


def test_a_missing_unit_is_not_installed_from_here(tmp_path):
    host = FakeHost(tmp_path)
    host.unit_path.unlink()
    assert updater(tmp_path, host).run() == "not_installed" and host.calls == []


def test_the_installer_arguments_come_from_the_units_check_line():
    args = m.installer_args(unit(OLD, port=8770))
    assert args["--commit"] == OLD and args["--port"] == "8770" and args["--source-root"] == f"/src/{OLD}"
    with pytest.raises(ValueError):
        m.installer_args("[Service]\nExecStart=/bin/true\n")


def test_the_real_install_passes_only_the_installers_flags_and_the_namespace_matches_its_cli(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(m.subprocess, "run", lambda command, **kw: seen.append(command) or
                        type("Done", (), {"returncode": 0})())
    host = m.Host.__new__(m.Host)
    host.cfg = {}
    args = m.installer_args(unit(OLD))
    assert host.apply(Path("/src") / NEW, args, NEW)
    command = seen[0]
    assert command[:2] == ["/venv/bin/python", str(Path("/src") / NEW / m.INSTALLER)] and command[-1] == "--apply"
    flags = {word for word in command if word.startswith("--")}
    assert flags == {"--source-root", "--commit", "--state", "--center-config", "--port", "--python", "--apply"}
    installer = (ROOT / m.INSTALLER).read_text()
    for flag in flags - {"--apply"}:
        assert f"'{flag[2:]}'" in installer or f"'{flag}'" in installer, flag
    namespace = host.namespace(Path("/src") / NEW, args, NEW)
    assert namespace.port == 8769 and namespace.commit == NEW and namespace.collaboration is None


def with_updater(path):
    (path / m.UPDATER).parent.mkdir(parents=True)
    (path / m.UPDATER).write_text("")


def test_current_follows_the_installed_checkout_for_the_timer(tmp_path):
    host = FakeHost(tmp_path)
    (tmp_path / "src" / OLD).mkdir(parents=True)
    u = updater(tmp_path, host)
    host.head = OLD
    u.run()
    assert not (tmp_path / "current").is_symlink()  # an old checkout without the updater: the timer would fail
    with_updater(tmp_path / "src" / OLD)
    host.head = NEW
    u.run(dry_run=True)
    assert not (tmp_path / "current").is_symlink()  # a dry run changes nothing
    host.head = OLD
    u.run()
    assert str((tmp_path / "current").readlink()) == f"src/{OLD}"
    with_updater(tmp_path / "src" / NEW)
    host.head = NEW
    assert u.run() == "switched" and str((tmp_path / "current").readlink()) == f"src/{NEW}"


def test_a_center_that_does_not_stop_is_left_running_on_its_old_unit(tmp_path):
    host = FakeHost(tmp_path)
    host.stop_rc = 1
    assert updater(tmp_path, host).run() == "held"
    assert host.unit_path.read_text() == unit(OLD) and not [c for c in host.calls if c[0] == "apply"]
    assert host.calls[-1] == ("systemctl", "start", m.SERVICE)  # a timed-out stop still killed it


def test_an_error_after_the_stop_restores_and_restarts_the_old_unit(tmp_path):
    host = FakeHost(tmp_path)
    host.raise_in = "apply"
    with pytest.raises(m.subprocess.TimeoutExpired):
        updater(tmp_path, host).run()
    assert host.unit_path.read_text() == unit(OLD) and host.calls[-1] == ("systemctl", "restart", m.SERVICE)


def test_a_failed_fetch_is_retried_and_a_failed_render_is_not(tmp_path):
    host = FakeHost(tmp_path)
    def fetch(sha, target):
        raise m.subprocess.CalledProcessError(128, "git fetch")
    host.fetch = fetch
    u = updater(tmp_path, host)
    assert u.run() == "fetch_failed" and u.run() == "fetch_failed"  # a network blip is not the commit's fault
    host.fetch = lambda sha, target: target.mkdir(parents=True)
    def render(source, args, sha):
        raise m.subprocess.CalledProcessError(1, "git rev-parse")
    host.render = render
    assert u.run() == "render_failed" and u.run() == "known_bad"
    assert host.unit_path.read_text() == unit(OLD) and not [c for c in host.calls if c[1:2] == ("stop",)]
