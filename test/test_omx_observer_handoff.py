"""observer_handoff run: the observer stops and the port is confirmed free before the session starts, the session
runs under the same locks in its own process group, and the observer comes back only onto a confirmed-free port
and is reported resumed only once it holds the port (decision H4)."""
import importlib.util
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
OMX = ROOT / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("observer_handoff", OMX / "observer_handoff.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    import joint_tune_lock
finally:
    sys.path.remove(str(OMX))

TOPIC = "/omx_commissioning/arm_a/joint_states"
OBSERVER_PID = 4242
FREE = SimpleNamespace(returncode=1, stdout="", stderr="")
HELD = SimpleNamespace(returncode=0, stdout=" 42", stderr="")
posix = pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups need POSIX")
linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG is Linux only")


class Host:
    """Fake systemctl, fuser, locks and lease; one ordered event log. After 'start' the observer holds the port."""

    def __init__(self, ports=(), enabled="enabled", stop_ok=True, session_code=0, lease_before=None,
                 observer_takes_port=True, show="4242", active="inactive"):
        self.log, self.ports, self.enabled, self.stop_ok = [], list(ports), enabled, stop_ok
        self.session_code, self.spawned, self.show = session_code, None, show
        self.observer_takes_port, self.active = observer_takes_port, active
        self.lease = SimpleNamespace(
            default_owner=lambda: "me", LeaseHeld=type("LeaseHeld", (RuntimeError,), {}),
            claim=lambda *a, **k: (self.log.append("lease"),
                                   not (lease_before and lease_before["owner"] == "me" and lease_before["live"])),
            release=lambda *a, **k: self.log.append("unlease"),
            hold=lambda *a, **k: self.log.append("hold"))

    def run(self, *args):
        self.log.append(args[0])
        if args[0] == "stop":
            return SimpleNamespace(returncode=0 if self.stop_ok else 1, stdout="", stderr="refused")
        if args[0] == "is-active":
            return SimpleNamespace(returncode=0, stdout=self.active + "\n", stderr="")
        if args[0] == "is-enabled":
            if isinstance(self.enabled, Exception):
                raise self.enabled
            return SimpleNamespace(returncode=0 if self.enabled == "enabled" else 1, stdout=self.enabled + "\n",
                                   stderr="")
        if args[0] == "show":
            return SimpleNamespace(returncode=0, stdout=self.show + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def users(self, device):
        if self.ports:
            answer = self.ports.pop(0)
        elif "start" in self.log and self.observer_takes_port:
            answer = SimpleNamespace(returncode=0, stdout=f" {OBSERVER_PID}", stderr="")
        else:
            answer = FREE
        if isinstance(answer, Exception):
            raise answer
        return answer

    def lock(self, arm):
        self.log.append("lock")
        return SimpleNamespace(handles=(), close=lambda: self.log.append("unlock"))

    def spawn(self, command, env, pass_fds):
        self.log.append("session")
        self.spawned = SimpleNamespace(command=command, env=env)
        return SimpleNamespace(pid=1, wait=lambda: self.session_code)


@pytest.fixture
def cell(tmp_path, monkeypatch):
    (tmp_path / "omx-observer-arm_a.env").write_text(
        f"ROSY_OBSERVER_DEVICE=/dev/serial/by-id/x\nROSY_OBSERVER_TOPIC={TOPIC}\n", encoding="utf-8")
    (tmp_path / "obs").mkdir()
    monkeypatch.setattr(m, "resolve_device", lambda device: "/dev/ttyACM0")
    obs = str(tmp_path / "obs")
    return SimpleNamespace(env_dir=tmp_path, environ={"ROSY_OBSERVATION_DIR": obs}, state=tmp_path / "state",
                           bridge=lambda arm, env_dir, run: (TOPIC, obs))


def state_of(cell):
    return json.loads((cell.state / "arm_a.json").read_text(encoding="utf-8"))


def ticking():
    now = [0.0]

    def clock():
        now[0] += 1.0
        return now[0]

    return clock


def handoff(cell, host, **overrides):
    kwargs = dict(env_dir=cell.env_dir, environ=cell.environ, run=host.run, users=host.users, scan=lambda r: set(),
                  lock=host.lock, lease=host.lease, spawn=host.spawn, sleep=lambda s: None, clock=ticking(),
                  alive=lambda pgid: False, kill=lambda child, s: None, signals=(), bridge=cell.bridge,
                  state_dir=cell.state)
    kwargs.update(overrides)
    return m.handoff("arm_a", ["session"], **kwargs)


def test_the_session_runs_after_a_confirmed_free_port_and_the_observer_returns(cell, capfd):
    host = Host(ports=[HELD, FREE])
    assert handoff(cell, host) == 0
    assert host.log == ["lock", "lease", "stop", "session", "unlease", "unlock", "is-enabled", "start", "show"]
    assert host.spawned.env["ROSY_CHUNK_JOINT_TOPIC"] == TOPIC
    assert host.spawned.env["ROSY_OBSERVATION_DIR"] == cell.environ["ROSY_OBSERVATION_DIR"]
    out, err = capfd.readouterr()
    assert out == ""  # stdout belongs to the session
    assert json.loads(err.splitlines()[-1]) == {"event": "observer_resumed", "arm": "arm_a",
                                                "unit": "rosy-omx-observer@arm_a.service", "pid": OBSERVER_PID}
    assert {k: state_of(cell)[k] for k in ("schema", "session_code", "observer", "error")} == {
        "schema": "rosy.omx-observer-handoff.v1", "session_code": 0, "observer": "resumed", "error": None}


def test_an_existing_lease_of_this_owner_is_refreshed_and_kept(cell):  # decided inside claim's lease lock
    host = Host(lease_before={"owner": "me", "live": True})
    assert handoff(cell, host) == 0
    assert "lease" in host.log and "unlease" not in host.log  # D-1035, as record_session_cli.claim_arm_lease


def test_the_session_exit_code_is_returned_and_the_observer_still_returns(cell):
    host = Host(session_code=3)
    assert handoff(cell, host) == 3
    assert host.log[-2:] == ["start", "show"]


@pytest.mark.parametrize("case", ["relative folder", "other folder", "other arm's topic", "bad topic", "no device",
                                  "unreadable bridge", "stale unit topic"])
def test_bad_settings_refuse_before_the_observer_is_touched(cell, case):
    environ, kwargs = dict(cell.environ), {}
    if case == "relative folder":
        environ["ROSY_OBSERVATION_DIR"] = "relative/obs"
    elif case == "other folder":
        (cell.env_dir / "elsewhere").mkdir()
        environ["ROSY_OBSERVATION_DIR"] = str(cell.env_dir / "elsewhere")  # exists, but the bridge reads obs/
    elif case == "other arm's topic":
        kwargs["topic"] = "/omx_commissioning/arm_b/joint_states"
    elif case == "bad topic":
        kwargs["topic"] = "/elsewhere"
    elif case == "stale unit topic":  # the unit would restart on a topic the bridge does not read
        (cell.env_dir / "omx-observer-arm_a.env").write_text(
            "ROSY_OBSERVER_DEVICE=/dev/serial/by-id/x\nROSY_OBSERVER_TOPIC=/omx_commissioning/arm_b/joint_states\n",
            encoding="utf-8")
    elif case == "no device":
        (cell.env_dir / "omx-observer-arm_a.env").write_text(f"ROSY_OBSERVER_TOPIC={TOPIC}\n", encoding="utf-8")
    else:
        def unreadable(arm, env_dir, run):
            raise m.HandoffError("cannot read the bridge's binding")

        kwargs["bridge"] = unreadable
    host = Host()
    assert handoff(cell, host, environ=environ, **kwargs) == m.HANDOFF_FAILED
    assert host.log == []
    assert not (cell.state / "arm_a.json").exists()  # nothing touched, nothing to report


def test_the_bridges_snapshot_folder_is_the_default(cell):
    host = Host()
    assert handoff(cell, host, environ={}) == 0
    assert host.spawned.env["ROSY_OBSERVATION_DIR"] == cell.environ["ROSY_OBSERVATION_DIR"]


def test_bridge_binding_reads_the_manifest_and_the_bridge_units_folder(tmp_path):
    manifest = tmp_path / "observations.yaml"
    manifest.write_text("workcells:\n  - workcell_id: cell_ab\n    arms:\n"
                        "      - {arm_id: arm_a, joint_topic: /omx_commissioning/arm_a/joint_states}\n"
                        "      - {arm_id: arm_b, joint_topic: /omx_commissioning/arm_b/joint_states}\n",
                        encoding="utf-8")
    (tmp_path / "omx-observation-bridge.env").write_text(
        f"ROSY_WORKCELL_OBSERVATIONS={manifest}\nROSY_OBSERVATION_WORKCELL=cell_ab\n", encoding="utf-8")
    calls = []

    def run(*args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="HOME=/home/u ROSY_OBSERVATION_DIR=/run/user/1000/rosy-observations\n",
                               stderr="")

    assert m.bridge_binding("arm_b", env_dir=tmp_path, run=run) == (
        "/omx_commissioning/arm_b/joint_states", "/run/user/1000/rosy-observations")
    assert calls == [("show", "-p", "Environment", "--value", "rosy-omx-observation-bridge.service")]
    with pytest.raises(m.HandoffError):
        m.bridge_binding("arm_s", env_dir=tmp_path, run=run)  # not in the manifest


def test_a_held_lock_refuses_before_the_observer_is_touched(cell):
    host = Host()

    def lock(arm):
        raise SystemExit("another OMX session holds session.lock")

    assert handoff(cell, host, lock=lock) == m.HANDOFF_FAILED
    assert host.log == []


def test_a_port_that_never_returns_stops_the_session_and_leaves_the_observer_down(cell):
    host = Host(ports=[HELD] * 100)
    assert handoff(cell, host) == m.HANDOFF_FAILED
    assert "session" not in host.log and "start" not in host.log
    assert host.log[-2:] == ["unlease", "unlock"]


@pytest.mark.parametrize("error", [
    SimpleNamespace(returncode=1, stdout="", stderr="Cannot stat file /dev/ttyACM0"),
    SimpleNamespace(returncode=2, stdout="", stderr=""),
    OSError("fuser not installed"),
])
def test_a_port_check_that_cannot_be_made_is_never_a_free_port(cell, error):
    host = Host(ports=[error, error])
    assert handoff(cell, host) == m.HANDOFF_FAILED
    assert "session" not in host.log and "start" not in host.log


def test_a_holder_only_proc_sees_is_a_held_port(cell):
    host = Host()
    assert handoff(cell, host, scan=lambda resolved: {77}) == m.HANDOFF_FAILED
    assert "session" not in host.log


def test_a_vanished_link_after_the_stop_is_a_refusal(cell, monkeypatch):
    host = Host()
    calls = []

    def resolve(device):
        calls.append(device)
        if len(calls) > 1:
            raise m.HandoffError("link does not resolve")
        return "/dev/ttyACM0"

    monkeypatch.setattr(m, "resolve_device", resolve)
    assert handoff(cell, host) == m.HANDOFF_FAILED
    assert "session" not in host.log and "start" not in host.log


def test_a_session_that_left_the_port_held_keeps_its_result_and_reports_the_observer(cell):
    host = Host(ports=[FREE] + [HELD] * 100)
    assert handoff(cell, host) == 0  # the placement result is the session's
    assert "start" not in host.log
    assert state_of(cell)["observer"] == "failed" and "held" in state_of(cell)["error"]


def test_a_failed_stop_does_not_start_the_session(cell):
    host = Host(stop_ok=False)
    assert handoff(cell, host) == m.HANDOFF_FAILED
    assert "session" not in host.log


@pytest.mark.parametrize("host_kwargs, started, observer", [
    ({"enabled": "disabled"}, False, "left_disabled"),  # left down on purpose: not a failure
    ({"enabled": "bad-setting"}, False, "failed"),  # an is-enabled error is not 'disabled'
    ({"enabled": OSError("no bus")}, False, "failed"),
    ({"observer_takes_port": False}, True, "failed"),  # started, but never held the port
    ({"show": "0"}, True, "failed"),  # started without a main process
])
def test_restore_reports_only_what_it_saw(cell, host_kwargs, started, observer, capfd):
    host = Host(**host_kwargs)
    assert handoff(cell, host) == 0  # never folded into the session's result
    assert ("start" in host.log) == started
    assert "observer_resumed" not in capfd.readouterr().err
    assert state_of(cell)["observer"] == observer


def test_a_failed_restore_keeps_a_failing_session_code(cell):
    host = Host(session_code=4, enabled=OSError("no bus"))
    assert handoff(cell, host) == 4


def test_session_processes_that_outlive_the_wait_keep_the_observer_down(cell):
    host = Host()
    assert handoff(cell, host, alive=lambda pgid: True, group_timeout_s=3) == m.SESSION_LINGERS
    assert "start" not in host.log
    assert state_of(cell)["observer"] == "stayed_down"


def test_release_restarts_only_an_enabled_observer_on_a_free_port(cell):
    host = Host()
    assert m.release("arm_a", run=host.run, users=host.users, scan=lambda r: set(), env_dir=cell.env_dir,
                     sleep=lambda s: None, clock=ticking(), state_dir=cell.state) == 0
    assert host.log == ["is-enabled", "start", "show"]
    host = Host(enabled="disabled")
    assert m.release("arm_a", run=host.run, users=host.users, scan=lambda r: set(), env_dir=cell.env_dir,
                     sleep=lambda s: None, clock=ticking(), state_dir=cell.state) == 0
    assert "start" not in host.log
    host = Host(ports=[HELD])
    assert m.release("arm_a", run=host.run, users=host.users, scan=lambda r: set(), env_dir=cell.env_dir,
                     sleep=lambda s: None, clock=ticking(), state_dir=cell.state) == m.RECOVERY_FAILED
    assert host.log == []


def test_options_after_the_arm_are_options_and_the_command_follows_the_double_dash(tmp_path):
    args, session = m.parse(["run", "arm_a", "--joint-topic", TOPIC, "--env-dir", str(tmp_path), "--",
                             "wrapper", "--joint-topic", "x"])
    assert (args.joint_topic, args.env_dir, session) == (TOPIC, tmp_path, ["wrapper", "--joint-topic", "x"])
    args, session = m.parse(["release", "arm_a", "--env-dir", str(tmp_path)])
    assert (args.command, args.env_dir, session) == ("release", tmp_path, [])
    for bad in (["run", "arm_a"], ["run", "arm_a", "--"], ["release", "arm_a", "--", "x"], ["run", "a/b", "--", "x"]):
        with pytest.raises(SystemExit):
            m.parse(bad)


def last_json(stdout):
    """cell_task_exec's reading of a wrapper's stdout: the last line that is a JSON object."""
    for line in reversed(stdout.splitlines()):
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                return json.loads(s)
            except ValueError:
                pass
    return {}


def test_cell_task_exec_still_reads_the_sessions_last_json_line_through_run(cell, capfd):
    assert "parsed = last_json_object(proc.stdout)" in (OMX / "cell_task_exec.py").read_text(encoding="utf-8")
    child = ("import json\nfor row in ({'stage': 'grasp'}, {'stage': 'place'}, {'result': 'placed', 'task': 'T1'}):"
             "\n    print(json.dumps(row))")
    environ = {**os.environ, **cell.environ}
    for host, observer in ((Host(), "resumed"), (Host(enabled=OSError("no bus")), "failed")):
        code = m.handoff("arm_a", [sys.executable, "-c", child], env_dir=cell.env_dir, environ=environ,
                         run=host.run, users=host.users, scan=lambda r: set(), lock=host.lock, lease=host.lease,
                         sleep=lambda s: None, clock=ticking(), alive=lambda pgid: False, signals=(),
                         bridge=cell.bridge, state_dir=cell.state)
        out, err = capfd.readouterr()
        assert code == 0  # cell_task_exec's placed needs exit 0 too; a failed restore must not take it away
        assert last_json(out) == {"result": "placed", "task": "T1"}
        assert len(out.splitlines()) == 3 and state_of(cell)["observer"] == observer


def posix_handoff(cell, command, **overrides):
    """Real processes and signals; the host log records the session's start and the moment its group was gone."""
    host = Host()

    def spawn(*args, **kwargs):
        host.log.append("session")
        return m.spawn_session(*args, **kwargs)

    def alive(pgid):
        if m.group_alive(pgid):
            return True
        host.log.append("group_gone")
        return False

    kwargs = dict(env_dir=cell.env_dir, environ={**os.environ, **cell.environ}, run=host.run, users=host.users,
                  scan=lambda r: set(), lock=host.lock, lease=host.lease, sleep=time.sleep, spawn=spawn, alive=alive,
                  bridge=cell.bridge, state_dir=cell.state)
    kwargs.update(overrides)
    return m.handoff("arm_a", command, **kwargs), host


def signal_me(*delays, signum=None):
    for delay in delays:
        threading.Timer(delay, os.kill, (os.getpid(), signum or signal.SIGTERM)).start()


@posix
def test_a_signal_reaches_the_whole_group_behind_a_shell_wrapper(cell):
    signal_me(0.5)
    started = time.monotonic()
    code, host = posix_handoff(cell, ["sh", "-c", "sleep 30 & sleep 30"])
    assert code == 143  # cancelled, whatever the wrapper returned
    assert time.monotonic() - started < 10  # the background sleep got the signal too
    assert host.log.index("session") < host.log.index("group_gone") < host.log.index("start")
    assert host.log[-2:] == ["start", "show"]


@posix
def test_a_second_signal_does_not_skip_to_the_restore(cell, capfd):
    child = ("import json, signal, time\nsignal.signal(signal.SIGTERM, lambda *a: None)\ntime.sleep(1.5)\n"
             "print(json.dumps({'result': 'parked'}))")
    signal_me(0.3, 0.6)
    started = time.monotonic()
    code, host = posix_handoff(cell, [sys.executable, "-c", child])
    assert code == 143
    assert time.monotonic() - started >= 1.4  # waited for the session itself to finish
    assert last_json(capfd.readouterr().out) == {"result": "parked"}
    assert host.log.index("session") < host.log.index("group_gone") < host.log.index("start")


@posix
def test_run_waits_for_a_wrappers_background_session(cell):
    started = time.monotonic()
    code, host = posix_handoff(cell, ["sh", "-c", "(sleep 1) & exit 0"])
    assert code == 0 and time.monotonic() - started >= 0.9
    assert host.log.index("session") < host.log.index("group_gone") < host.log.index("start")


@posix
def test_a_session_that_will_not_end_is_reported_and_never_killed(cell):
    code, host = posix_handoff(cell, ["sh", "-c", "(trap '' TERM HUP; sleep 2) & exit 0"], group_timeout_s=0.5)
    assert code == m.SESSION_LINGERS and "start" not in host.log and "group_gone" not in host.log
    time.sleep(2)  # the leftover ends on its own


def test_keep_live_leaves_an_existing_pidless_reservation_as_it_is(tmp_path):
    sys.path.insert(0, str(OMX))
    try:
        import cell_arm_lease
    finally:
        sys.path.remove(str(OMX))
    reserved = cell_arm_lease.claim("arm_a", "u@x", "job", root=tmp_path, now=100, ttl_s=3600)
    record, created = cell_arm_lease.claim("arm_a", "u@x", "observer_handoff", pid=os.getpid(), root=tmp_path,
                                           now=200, report_created=True, keep_live=True)
    assert not created and record["pid"] is None and record["expires"] == reserved["expires"] == 3700
    assert cell_arm_lease.live(cell_arm_lease._read("arm_a", tmp_path), now=3000)  # still valid, no handoff pid
    fresh, created = cell_arm_lease.claim("arm_b", "u@x", "observer_handoff", pid=os.getpid(), root=tmp_path,
                                          now=200, report_created=True, keep_live=True)
    assert created and fresh["pid"] == os.getpid()  # nothing to keep: the handoff's own lease covers the session


def test_group_members_ignores_zombies_and_other_groups(tmp_path):
    for pid, state, pgrp in ((10, "S", 7), (11, "Z", 7), (12, "S", 8), (13, "R", 7)):
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "stat").write_text(f"{pid} (a b) {state} 1 {pgrp} {pgrp} 0", encoding="utf-8")
    assert m.group_members(7, tmp_path) == {10, 13}
    assert m.group_members(7, tmp_path / "missing") is None


@linux
def test_the_leader_keeps_watching_while_a_background_session_outlives_its_child(tmp_path):
    """The leader's direct child returns at once; SIGTERM to the leader must still reach the background sleep."""
    import subprocess

    pids = tmp_path / "pids"
    leader = subprocess.Popen([sys.executable, str(OMX / "observer_handoff.py"), "_lead", "--", "sh", "-c",
                               f"sleep 60 & echo $! > {pids}; exit 0"], start_new_session=True)
    deadline = time.monotonic() + 5
    while not pids.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    sleeper = int(pids.read_text())
    time.sleep(0.5)
    assert leader.poll() is None  # not gone with its direct child
    os.kill(leader.pid, signal.SIGTERM)
    assert leader.wait(timeout=10) == 0
    assert not m.group_members(leader.pid) and sleeper not in (m.group_members(leader.pid) or ())


def test_claim_reports_whether_this_call_created_the_lease(tmp_path):
    sys.path.insert(0, str(OMX))
    try:
        import cell_arm_lease
    finally:
        sys.path.remove(str(OMX))
    record, created = cell_arm_lease.claim("arm_a", "u@x", "handoff", root=tmp_path, now=100, report_created=True)
    assert created and record["owner"] == "u@x"
    assert cell_arm_lease.claim("arm_a", "u@x", "session", root=tmp_path, now=200, report_created=True)[1] is False
    assert cell_arm_lease.claim("arm_a", "u@x", root=tmp_path, now=300)["owner"] == "u@x"  # old form unchanged
    assert cell_arm_lease.claim("arm_a", "u@x", root=tmp_path, now=10_000, report_created=True)[1]  # expired


DRIVER = """
import importlib.util, json, os, sys
from types import SimpleNamespace as NS
cfg = json.loads(sys.argv[1])
sys.path.insert(0, cfg["omx"])
spec = importlib.util.spec_from_file_location("observer_handoff", cfg["omx"] + "/observer_handoff.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.resolve_device = lambda device: "/dev/ttyACM0"
ok, free = NS(returncode=0, stdout="", stderr=""), NS(returncode=1, stdout="", stderr="")
lease = NS(default_owner=lambda: "me", LeaseHeld=RuntimeError, claim=lambda *a, **k: ({}, True),
           release=lambda *a, **k: None)
m.handoff("arm_a", ["sh", "-c", cfg["script"]], env_dir=cfg["env_dir"],
          environ={**os.environ, "ROSY_OBSERVATION_DIR": cfg["obs"]}, run=lambda *a: ok, users=lambda d: free,
          scan=lambda r: set(), lock=lambda arm: NS(handles=(), close=lambda: None), lease=lease,
          bridge=lambda arm, env_dir, run: (cfg["topic"], cfg["obs"]), state_dir=cfg["state"])
"""


@linux
def test_fleets_timeout_kill_of_run_still_ends_the_whole_session(cell, tmp_path):
    """cell_task_exec runs the wrapper with subprocess.run(timeout=300), which SIGKILLs it: run gets no chance to
    forward anything, so the leader's PR_SET_PDEATHSIG must end the session group (here a shell and its sleep)."""
    import subprocess

    pids = tmp_path / "pids"
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER, encoding="utf-8")
    cfg = {"omx": str(OMX), "env_dir": str(cell.env_dir), "obs": cell.environ["ROSY_OBSERVATION_DIR"],
           "topic": TOPIC, "state": str(cell.state), "script": f"echo $$ > {pids}; sleep 60 & echo $! >> {pids}; wait"}
    with pytest.raises(subprocess.TimeoutExpired):  # the same call cell_task_exec makes, with a short timeout
        subprocess.run([sys.executable, str(driver), json.dumps(cfg)], capture_output=True, text=True, timeout=3)
    session = [int(pid) for pid in pids.read_text().split()]
    assert len(session) == 2

    def alive(pid):  # a zombie nobody reaps (container PID 1) is not a running session
        try:
            return Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0] not in ("Z", "X")
        except OSError:
            return False

    deadline = time.monotonic() + 10
    while any(alive(pid) for pid in session) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not any(alive(pid) for pid in session), "the session outlived run's SIGKILL"


def test_only_a_resolving_by_id_link_is_a_checkable_port(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "BY_ID", tmp_path)
    plain = tmp_path / "plain"
    plain.write_text("")
    with pytest.raises(m.HandoffError):
        m.resolve_device(str(plain))
    try:
        os.symlink(tmp_path / "gone", tmp_path / "broken")
        os.symlink(plain, tmp_path / "ok")
    except (OSError, NotImplementedError):
        pytest.skip("this host cannot create symlinks")
    with pytest.raises(m.HandoffError):
        m.resolve_device(str(tmp_path / "broken"))
    assert m.resolve_device(str(tmp_path / "ok")) == str(plain.resolve())


def test_the_session_reuses_the_held_locks_and_nothing_else_does(tmp_path, monkeypatch):
    pytest.importorskip("fcntl")
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path / "omx"))
    monkeypatch.setenv("HOME", str(tmp_path))
    parent = joint_tune_lock.session_lock("arm_a")
    try:
        with pytest.raises(SystemExit):
            joint_tune_lock.session_lock("arm_a")  # no handoff env: refused as before
        fds = [h.fileno() for h in parent.handles]
        monkeypatch.setenv(joint_tune_lock.HELD_ENV, f"arm_b:{fds[0]}:{fds[1]}")
        with pytest.raises(SystemExit):
            joint_tune_lock.session_lock("arm_a")  # another arm's grant is not this arm's
        other = (tmp_path / "other").open("a")
        monkeypatch.setenv(joint_tune_lock.HELD_ENV, f"arm_a:{fds[0]}:{other.fileno()}")
        with pytest.raises(SystemExit):
            joint_tune_lock.session_lock("arm_a")  # an fd that is not the lock file is not reused
        other.close()
        monkeypatch.setenv(joint_tune_lock.HELD_ENV, f"arm_a:{fds[0]}:{fds[1]}")
        child = joint_tune_lock.session_lock("arm_a")
        child.close()
        monkeypatch.delenv(joint_tune_lock.HELD_ENV)
        with pytest.raises(SystemExit):
            joint_tune_lock.session_lock("arm_a")  # the child's close left the parent's hold in place
    finally:
        parent.close()
    joint_tune_lock.session_lock("arm_a").close()


@pytest.fixture
def session(tmp_path, monkeypatch):
    """chunk_runner's snapshot writer, the bridge's arm reader and the radians helper, writing into tmp_path."""
    paths = [str(OMX), str(ROOT / "contracts/foundation")]
    sys.path[:0] = paths
    try:
        import arm_status_bridge
        import chunk_runner
        sources = pytest.importorskip("workcell_observation_sources")
        from core_common.observation_snapshot import SnapshotChannel
    finally:
        for p in paths:
            sys.path.remove(p)
    monkeypatch.setenv("ROSY_OBSERVATION_DIR", str(tmp_path / "obs"))
    calibration = {name: SimpleNamespace(range_min=1024, range_max=3072) for name in arm_status_bridge.MOTORS}
    return SimpleNamespace(runner=chunk_runner, sources=sources, arm=arm_status_bridge, channel=SnapshotChannel,
                           calibration=calibration, topic="/omx_commissioning/arm_a/joint_states")


def test_runner_snapshot_rows_are_readable_by_the_bridge_source(session):
    """The session writes the observer's channel in the shape NativeSource (the bridge's arm reader) accepts."""
    rows, state = [], [0.0, -50.0, 50.0, 100.0, -100.0, 50.0]
    live = session.runner.snapshot_live(rows.append, session.topic, session.calibration)
    live({"t": time.time(), "state": state})
    assert rows  # the plain live.json write still happened
    sample = session.sources.NativeSource(session.topic, joint_names=session.arm.JOINTS).latest()
    assert sample is not None
    assert dict(sample.value) == session.arm.to_radians(state, {
        k: {"range_min": 1024, "range_max": 3072} for k in session.arm.MOTORS})


def test_a_stale_runner_row_is_not_a_fresh_bridge_sample(session):
    live = session.runner.snapshot_live(lambda row: None, session.topic, session.calibration)
    live({"t": time.time() - 30, "state": [0.0] * 6})
    assert session.sources.NativeSource(session.topic, joint_names=session.arm.JOINTS).latest() is None


def test_snapshot_write_failure_does_not_break_the_session(session, monkeypatch):
    """Observation is auxiliary: a refused channel write must not fail the runner's tick."""
    def broken_write(self, kind, payload, *, captured_at, quality=None):
        raise OSError("disk refused")

    monkeypatch.setattr(session.channel, "write", broken_write)
    rows = []
    live = session.runner.snapshot_live(rows.append, session.topic, session.calibration)
    live({"t": time.time(), "state": [0.0] * 6})  # returns normally
    assert rows


# --- Codex review of 447739d962 / 9f26324955 (PR #374): five findings, each at its cause ---


def test_record_session_puts_a_pidless_reservation_back_so_it_outlives_the_session(tmp_path, monkeypatch):
    sys.path.insert(0, str(OMX))
    try:
        import cell_arm_lease
        import record_session_cli as cli
    finally:
        sys.path.remove(str(OMX))
    monkeypatch.setenv("ROSY_ARM_LEASES", str(tmp_path))
    monkeypatch.setenv("ROSY_ARM_LEASE_OWNER", "me@here")
    reserved = cell_arm_lease.claim("arm_a", "me@here", "job", root=tmp_path, now=time.time(), ttl_s=3600)
    record, created, before = cli.claim_arm_lease("arm_a")
    assert not created and record["pid"] == os.getpid() and before["pid"] is None  # covered during the session
    assert not cell_arm_lease.restore("arm_a", before, {**record, "pid": 1}, root=tmp_path)  # changed since our claim
    assert cell_arm_lease.restore("arm_a", before, record, root=tmp_path)
    after = cell_arm_lease._read("arm_a", tmp_path)
    assert after["pid"] is None and after["expires"] == reserved["expires"]
    assert cell_arm_lease.live(after, now=time.time() + 3000)  # still the same valid reservation, no dead pid
    # never over a hold or another owner's lease
    assert not cell_arm_lease.restore("arm_a", {**before, "owner": "other@x"}, record, root=tmp_path)
    cell_arm_lease.hold("arm_a", "runner HOLD", owner="me@here", root=tmp_path)
    assert not cell_arm_lease.restore("arm_a", before, record, root=tmp_path)
    assert cell_arm_lease._read("arm_a", tmp_path)["hold"] == "runner HOLD"


def test_run_does_not_wait_a_second_time_after_the_leader_did(cell):
    sleeps = []
    host = Host()
    code = handoff(cell, host, alive=lambda pgid: True, group_timeout_s=100, leader_waited=True,
                   sleep=sleeps.append)
    assert code == m.SESSION_LINGERS and sleeps == []  # no window without a leader to pass run's death on
    assert "start" not in host.log
    assert "hold" in host.log and "unlease" not in host.log  # the arm stays refused until a person checks it


@pytest.mark.parametrize("command", [["s", "--joint-topic", "/omx_commissioning/arm_b/joint_states"],
                                     ["s", "--joint-topic=/omx_commissioning/arm_b/joint_states"],
                                     ["s", "--joint-topic"]])
def test_a_topic_on_the_session_command_that_differs_refuses_before_the_observer_is_touched(cell, command):
    host = Host()
    kwargs = dict(env_dir=cell.env_dir, environ=cell.environ, run=host.run, users=host.users, lock=host.lock,
                  lease=host.lease, spawn=host.spawn, bridge=cell.bridge, state_dir=cell.state, signals=())
    assert m.handoff("arm_a", command, **kwargs) == m.HANDOFF_FAILED
    assert host.log == []
    assert m.handoff("arm_a", ["s", "--joint-topic", TOPIC], **{**kwargs, "sleep": lambda s: None,
                     "clock": ticking(), "alive": lambda p: False, "scan": lambda r: set()}) == 0


def test_the_runner_refuses_a_joint_topic_other_than_the_handoffs_checked_one(session, monkeypatch, tmp_path):
    monkeypatch.setenv("ROSY_CHUNK_JOINT_TOPIC", session.topic)
    base = ["--config", str(tmp_path / "c"), "--library", str(tmp_path / "l"), "--io", str(tmp_path / "io")]
    with pytest.raises(SystemExit) as exc:
        session.runner.main([*base, "--joint-topic", "/omx_commissioning/arm_b/joint_states"])
    assert exc.value.code == 2  # argparse refusal, before the arm is opened


@pytest.mark.parametrize("active, stopped_expected", [("active", False), ("inactive", True)])
def test_a_failed_stop_is_reported_as_the_stop_and_only_a_down_unit_is_restarted(cell, active, stopped_expected,
                                                                                capfd):
    host = Host(stop_ok=False, active=active)
    assert handoff(cell, host) == m.HANDOFF_FAILED
    assert "session" not in host.log and ("start" in host.log) == stopped_expected
    err = capfd.readouterr().err
    assert "recovery" not in err or stopped_expected  # a still-running observer: no recovery failure line
    saved = state_of(cell)
    assert "could not stop" in saved["error"]
    assert saved["observer"] == ("resumed" if stopped_expected else "stop_failed")  # never counted stopped


@posix
def test_sigterm_before_the_session_launches_exits_143(cell):
    host = Host(ports=[HELD] * 3)  # the port stays held while the signal arrives
    signal_me(0.05)
    code = handoff(cell, host, signals=m.SIGNALS, sleep=lambda s: time.sleep(0.1), group_timeout_s=1)
    assert code == 143 and "session" not in host.log


def test_a_stop_that_times_out_is_checked_before_any_restart(cell):
    host = Host(active="active")
    plain = host.run

    def run(*args):
        if args[0] == "stop":
            host.log.append("stop")
            raise m.subprocess.TimeoutExpired("systemctl", 10)
        return plain(*args)

    assert handoff(cell, host, run=run) == m.HANDOFF_FAILED
    assert "start" not in host.log and state_of(cell)["observer"] == "stop_failed"
