"""D-373 site-network robustness: robots by name, host key under the robot id, visible failures."""
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
for p in (ROOT / "learning" / "training" / "perception", ROOT / "learning" / "training" / "perception" / "model"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import deliver  # noqa: E402
import operator_ssh  # noqa: E402
import rosy_ml  # noqa: E402
import test_model_deliver as td  # noqa: E402
import test_model_watch_inbox as ti  # noqa: E402
import watch  # noqa: E402

DNS_ERR = "ssh: Could not resolve hostname pinky-a.local: Name or service not known"
REFUSED = "ssh: connect to host pinky-a.local port 22: Connection refused"
TIMED_OUT = "ssh: connect to host pinky-a.local port 22: Connection timed out"
CHANGED = "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!\nHost key verification failed."
UNKNOWN = "No ED25519 host key is known for pinky-a and you have requested strict checking.\n" \
          "Host key verification failed."


# --- operator_ssh: alias and classification -------------------------------------------------

def test_options_pin_under_the_alias_and_stay_strict():
    opts = operator_ssh.options("/k", "/kh", "pinky-a")
    assert "HostKeyAlias=pinky-a" in opts
    assert "StrictHostKeyChecking=yes" in opts
    assert not any("StrictHostKeyChecking=no" in o or "accept-new" in o for o in opts)
    assert not any(o.startswith("HostKeyAlias") for o in operator_ssh.options("/k", "/kh"))


@pytest.mark.parametrize("rc, err, kind", [
    (255, DNS_ERR, "dns"),
    (255, "ssh: Could not resolve hostname x: Temporary failure in name resolution", "dns"),
    (255, REFUSED, "unreachable"),
    (255, TIMED_OUT, "unreachable"),
    (255, "ssh: connect to host x port 22: No route to host", "unreachable"),
    (124, "", "unreachable"),
    (255, CHANGED, "hostkey"),
    (255, UNKNOWN, "hostkey"),
    (255, "Permission denied (publickey).", None),   # a key problem is not a network failure
    (1, REFUSED, None),                              # a remote command's code is never one
    (75, "", None),
])
def test_classify(rc, err, kind):
    assert operator_ssh.classify(rc, err) == kind


def test_network_exit_codes_are_distinct_and_free():
    codes = set(operator_ssh.KIND_EXIT.values())
    assert codes == {77, 78, 79}
    taken = {0, 1, 2, 3, 4, 5, 6, 75, 76, 124, 255}  # deliver, harvest/intake, watch, ssh
    assert not codes & taken


# --- deliver: the alias reaches every ssh/scp, each kind has its exit code ------------------

def _push(tmp_path, runner, *extra):
    tmp_path.mkdir(exist_ok=True)
    models = tmp_path / "models"
    rev = td._model(models, "pass")
    return deliver.main(["push", "pinky-a.local", rev, "--models", str(models), *td.SSH,
                         *extra], runner=runner)


def test_push_passes_the_alias_to_ssh_and_scp(tmp_path):
    runner = td.FakeRunner()
    assert _push(tmp_path, runner, "--host-key-alias", "pinky-a") == 0
    assert runner.calls and all("HostKeyAlias=pinky-a" in c for c in runner.calls)
    assert all("rosy@pinky-a.local" in " ".join(c) for c in runner.calls[:1])


class StderrRunner(td.FakeRunner):
    def __init__(self, returncode, stderr):
        super().__init__(returncode=returncode)
        self.stderr = stderr

    def __call__(self, cmd, **kw):
        r = super().__call__(cmd, **kw)
        r.stderr = self.stderr
        return r


@pytest.mark.parametrize("err, code", [
    (DNS_ERR, 77), (REFUSED, 78), (TIMED_OUT, 78), (CHANGED, 79), (UNKNOWN, 79)])
def test_each_network_failure_has_its_exit_code_and_one_line(tmp_path, capsys, err, code):
    assert _push(tmp_path, StderrRunner(255, err)) == code
    lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.startswith("ssh ")]
    assert len(lines) == 1 and f"(exit {code})" in lines[0]


def test_a_timeout_is_unreachable(tmp_path, capsys):
    def runner(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    assert _push(tmp_path, runner) == 78
    assert "unreachable" in capsys.readouterr().err


def test_a_remote_failure_keeps_its_old_code(tmp_path):
    assert _push(tmp_path / "a", StderrRunner(1, "boom")) == 1
    assert _push(tmp_path / "b", StderrRunner(255, "Permission denied (publickey).")) == 1


def test_status_maps_a_dns_failure(capsys):
    rc = deliver.main(["status", "x.local", *td.SSH, "--host-key-alias", "a"],
                      runner=StderrRunner(255, DNS_ERR))
    assert rc == 77


def test_observe_raises_a_kinded_failure():
    with pytest.raises(deliver.SshFailure) as exc:
        deliver.observe("x.local", identity="/k", known_hosts="/kh", host_key_alias="a",
                        runner=StderrRunner(255, CHANGED))
    assert exc.value.kind == "hostkey"


def test_unsafe_alias_is_refused():
    assert deliver.main(["status", "h", *td.SSH, "--host-key-alias", "a b"],
                        runner=td.FakeRunner()) == 2


# --- watch: alias passed, failures recorded, exit code, no attempt spent --------------------

def test_watch_passes_the_robot_id_as_the_alias(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(deliver, "main", lambda argv, **kw: calls.append(argv) or 0)
    monkeypatch.setattr(deliver, "observe", lambda host, **kw: calls.append(kw) or {})
    cfg = watch.load_config(ti._config(tmp_path))
    robot = cfg["robots"][0]
    watch.default_deliverer(cfg)(robot, "rev-1")
    watch.default_observer(cfg)(robot)
    argv, kw = calls
    assert argv[argv.index("--host-key-alias") + 1] == "pinky-a"
    assert kw["host_key_alias"] == "pinky-a"


class Net(ti.Fakes):
    """Observe fails with a network kind for the named robots; deliver can return a code."""

    def __init__(self, down=None, push_code=0):
        super().__init__()
        self.down, self.push_code = dict(down or {}), push_code

    def observe(self, robot):
        kind = self.down.get(robot["name"])
        if kind:
            raise deliver.SshFailure(kind, f"{kind}: detail for {robot['name']}")
        return super().observe(robot)

    def deliver(self, robot, rev):
        if self.push_code:
            return self.push_code
        return super().deliver(robot, rev)


def test_a_network_failure_exits_with_its_code_and_is_recorded(tmp_path, capsys):
    cfg = ti._config(tmp_path)
    ti._drop(tmp_path, "m1")
    fakes = Net(down={"pinky-a": "dns"})
    assert ti._run(cfg, fakes) == 77
    err = capsys.readouterr().err
    assert err.count("pinky-a: dns failure (exit 77, 1 in a row)") == 1
    state = ti._state(tmp_path)
    fail = state["robot_failures"]["pinky-a"]
    assert (fail["kind"], fail["exit"], fail["count"]) == ("dns", 77, 1) and fail["at"]
    assert "pinky-b" not in state["robot_failures"]
    assert ("pinky-b", ti.rev_of("m1")) in fakes.delivers       # one robot never blocks another
    entry = state["commits"]["m1"]["robots"]["pinky-a"]
    assert entry["status"] == "pending" and entry["attempts"] == 0   # no attempt spent


def test_consecutive_count_grows_and_never_gives_up(tmp_path):
    cfg = ti._config(tmp_path, max_attempts=2)
    ti._drop(tmp_path, "m1")
    fakes = Net(down={"pinky-a": "unreachable", "pinky-b": "unreachable"})
    for n in (1, 2, 3, 4):
        assert ti._run(cfg, fakes) == 78
        assert ti._state(tmp_path)["robot_failures"]["pinky-a"]["count"] == n
    assert ti._state(tmp_path)["commits"]["m1"]["robots"]["pinky-a"]["status"] == "pending"
    fakes.down["pinky-a"] = "hostkey"                              # another kind restarts the count
    assert ti._run(cfg, fakes) == 79
    assert ti._state(tmp_path)["robot_failures"]["pinky-a"]["count"] == 1


def test_a_reachable_robot_clears_its_failure(tmp_path):
    cfg = ti._config(tmp_path)
    ti._drop(tmp_path, "m1")
    fakes = Net(down={"pinky-a": "dns"})
    assert ti._run(cfg, fakes) == 77
    fakes.down.clear()
    assert ti._run(cfg, fakes) == 0
    assert ti._state(tmp_path)["robot_failures"] == {}


def test_an_up_to_date_robot_that_cannot_be_read_is_no_longer_silent(tmp_path):
    cfg = ti._config(tmp_path)
    ti._drop(tmp_path, "m1")
    fakes = Net()
    assert ti._run(cfg, fakes) == 0                                 # delivered, entry ok
    fakes.down["pinky-a"] = "dns"
    assert ti._run(cfg, fakes) == 77


@pytest.mark.parametrize("code, kind", [(77, "dns"), (78, "unreachable"), (79, "hostkey")])
def test_a_push_that_fails_with_a_network_code(tmp_path, code, kind):
    cfg = ti._config(tmp_path)
    ti._drop(tmp_path, "m1")
    assert ti._run(cfg, Net(push_code=code)) == code
    state = ti._state(tmp_path)
    assert state["robot_failures"]["pinky-a"]["kind"] == kind
    assert state["commits"]["m1"]["robots"]["pinky-a"]["attempts"] == 0


def test_the_unit_surfaces_a_failed_exit_and_the_timer_keeps_firing():
    unit = ti.Path(ROOT / "deploy" / "site" / "rosy-model-watch.service").read_text("utf-8")
    keys = {ln.partition("=")[0] for ln in unit.splitlines() if "=" in ln and ln[0] not in "#["}
    assert not keys & {"SuccessExitStatus", "SuccessExitStatus=", "Restart", "RestartPreventExitStatus"}
    timer = (ROOT / "deploy" / "site" / "rosy-model-watch.timer").read_text("utf-8")
    assert "OnUnitInactiveSec=10min" in timer   # a failed oneshot counts as inactive


# --- rosy_ml -------------------------------------------------------------------------------

def _ml(tmp_path, monkeypatch, host="pinky-a.local", state=None):
    cfg = tmp_path / "ml.yaml"
    monkeypatch.setenv("ROSY_ML_CONFIG", str(cfg))
    key = tmp_path / "id"
    key.write_text("k")
    key.chmod(0o600)  # doctor refuses a group/world-readable key on POSIX
    kh = tmp_path / "kh"
    kh.write_text("")
    doc = {"operator": "ana", "robots": {"pinky-a": host},
           "ssh": {"identity": str(key), "known_hosts": str(kh)}}
    if state:
        doc["state_file"] = str(state)
    cfg.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return kh


class Keys:
    """ssh-keygen -F over a dict {lookup name: known_hosts line}; everything else succeeds."""

    def __init__(self, entries):
        self.entries, self.calls = entries, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] == "ssh-keygen":
            line = self.entries.get(cmd[2])
            out = f"# Host {cmd[2]} found: line 1\n{line}\n" if line else ""
            return types.SimpleNamespace(returncode=0 if line else 1, stdout=out, stderr="")
        out = "root:rosy-camera 750\n" if "sudo -n stat" in " ".join(cmd) else ""
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")


def _doctor_out(tmp_path, monkeypatch, capsys, runner, resolve, host="pinky-a.local"):
    _ml(tmp_path, monkeypatch, host)
    monkeypatch.setattr(rosy_ml, "_replay_clip_count", lambda cfg: 1)
    rc = rosy_ml.main(["doctor", "pinky-a"], runner=runner, resolve=resolve,
                      connect=lambda a, timeout: types.SimpleNamespace(close=lambda: None),
                      find_spec=lambda n: object())
    return rc, capsys.readouterr().out


def test_doctor_reports_an_unresolvable_host(tmp_path, monkeypatch, capsys):
    def nxdomain(host, port):
        raise OSError("Name or service not known")
    rc, out = _doctor_out(tmp_path, monkeypatch, capsys,
                          Keys({"pinky-a": "pinky-a ssh-ed25519 AAAA"}), nxdomain)
    assert rc == 1
    bad = [ln for ln in out.splitlines() if ln.startswith("✗")]
    assert any("pinky-a: host name resolves" in ln and "mDNS" in ln for ln in bad)
    assert not any("TCP 22" in ln for ln in out.splitlines())
    assert any("skipped: not reachable" in ln for ln in bad)


def test_doctor_resolves_names_and_skips_ips(tmp_path, monkeypatch, capsys):
    seen = []
    rc, out = _doctor_out(tmp_path, monkeypatch, capsys,
                          Keys({"pinky-a": "pinky-a ssh-ed25519 AAAA"}),
                          lambda h, p: seen.append(h) or [])
    assert rc == 0 and seen == ["pinky-a.local"] and "✓ pinky-a: host name resolves" in out
    seen.clear()
    _, out = _doctor_out(tmp_path, monkeypatch, capsys, Keys({"192.0.2.9": "x"}),
                         lambda h, p: seen.append(h), host="192.0.2.9")
    assert seen == [] and "is an IP" in out


def test_doctor_names_the_one_command_for_an_address_keyed_pin(tmp_path, monkeypatch, capsys):
    rc, out = _doctor_out(tmp_path, monkeypatch, capsys,
                          Keys({"pinky-a.local": "pinky-a.local ssh-ed25519 AAAA"}),
                          lambda h, p: [])
    assert rc == 1
    bad = [ln for ln in out.splitlines() if ln.startswith("✗")]
    assert len(bad) == 1 and "rosy_ml repin pinky-a" in bad[0]
    assert "pinky-a ssh-ed25519" not in (tmp_path / "kh").read_text()   # never rewritten silently


def test_doctor_looks_up_the_alias_not_the_address(tmp_path, monkeypatch, capsys):
    keys = Keys({"pinky-a": "pinky-a ssh-ed25519 AAAA"})
    rc, _ = _doctor_out(tmp_path, monkeypatch, capsys, keys, lambda h, p: [])
    assert rc == 0
    assert ["ssh-keygen", "-F", "pinky-a", "-f", str(tmp_path / "kh")] in keys.calls
    ssh = [c for c in keys.calls if c[0] == "ssh"]
    assert ssh and all("HostKeyAlias=pinky-a" in c for c in ssh)


def test_repin_copies_the_key_under_the_id(tmp_path, monkeypatch, capsys):
    kh = _ml(tmp_path, monkeypatch)
    kh.write_text("pinky-a.local ssh-ed25519 AAAA\n")
    keys = Keys({"pinky-a.local": "pinky-a.local ssh-ed25519 AAAA"})
    assert rosy_ml.main(["repin", "pinky-a"], runner=keys) == 0
    assert kh.read_text().splitlines() == ["pinky-a.local ssh-ed25519 AAAA",
                                            "pinky-a ssh-ed25519 AAAA"]


def test_repin_without_any_pin_is_refused_and_changes_nothing(tmp_path, monkeypatch, capsys):
    kh = _ml(tmp_path, monkeypatch)
    assert rosy_ml.main(["repin", "pinky-a"], runner=Keys({})) == 1
    assert kh.read_text() == "" and "trusted network" in capsys.readouterr().out


def test_repin_is_a_no_op_when_already_pinned(tmp_path, monkeypatch, capsys):
    kh = _ml(tmp_path, monkeypatch)
    assert rosy_ml.main(["repin", "pinky-a"],
                        runner=Keys({"pinky-a": "pinky-a ssh-ed25519 AAAA"})) == 0
    assert kh.read_text() == ""


def test_init_warns_about_an_ip_and_an_address_keyed_pin(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "ml.yaml"
    monkeypatch.setenv("ROSY_ML_CONFIG", str(cfg))
    key = tmp_path / "id"
    key.write_text("k")
    key.chmod(0o600)  # doctor refuses a group/world-readable key on POSIX
    kh = tmp_path / "kh"
    kh.write_text("")
    rc = rosy_ml.main(["init", "--robot", "pinky-a=192.0.2.9", "--identity", str(key),
                       "--known-hosts", str(kh)], runner=Keys({"192.0.2.9": "192.0.2.9 ssh-ed25519 A"}))
    out = capsys.readouterr().out
    assert rc == 0 and "is an IP" in out and "rosy_ml repin pinky-a" in out


def test_commands_pass_the_robot_id_as_the_alias(tmp_path, monkeypatch):
    _ml(tmp_path, monkeypatch)
    runner = td.FakeRunner()
    assert rosy_ml.main(["rollback", "pinky-a"], runner=runner) == 0
    assert runner.calls and all("HostKeyAlias=pinky-a" in c for c in runner.calls)


def test_a_network_failure_surfaces_through_rosy_ml(tmp_path, monkeypatch):
    _ml(tmp_path, monkeypatch)
    assert rosy_ml.main(["rollback", "pinky-a"], runner=StderrRunner(255, DNS_ERR)) == 77


def test_status_shows_the_last_watcher_failure(tmp_path, monkeypatch, capsys):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"robot_failures": {
        "pinky-a": {"kind": "dns", "exit": 77, "at": "2026-10-01T09:00:00+00:00", "count": 3}}}))
    _ml(tmp_path, monkeypatch, state=state)
    rosy_ml.main(["status", "pinky-a"], runner=td.FakeRunner())
    line = [ln for ln in capsys.readouterr().out.splitlines() if "watcher failure" in ln]
    assert len(line) == 1
    for word in ("pinky-a", "dns", "77", "2026-10-01T09:00:00+00:00", "3 in a row"):
        assert word in line[0]


def test_store_status_and_status_via_watch_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROSY_ML_CONFIG", str(tmp_path / "none.yaml"))
    wc = ti._config(tmp_path)
    ti._drop(tmp_path, "m1")
    (tmp_path / "state.json").write_text(json.dumps({"robot_failures": {
        "pinky-b": {"kind": "hostkey", "exit": 79, "at": "T", "count": 2}}}))
    assert rosy_ml.main(["store-status", "--watch-config", str(wc)]) == 0
    out = capsys.readouterr().out
    assert "pinky-b: last watcher failure: hostkey (exit 79) at T, 2 in a row" in out
    assert "pinky-a: last watcher failure" not in out


def test_no_failure_means_no_line(tmp_path, monkeypatch, capsys):
    _ml(tmp_path, monkeypatch, state=tmp_path / "missing.json")
    rosy_ml.main(["status", "pinky-a"], runner=td.FakeRunner())
    assert "watcher failure" not in capsys.readouterr().out
