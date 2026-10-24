"""D-412 updater: the apply transaction, health, units, history, prune and the D-433 display.

Moved out of test/test_rosy_auto_update.py (D-798); the fakes are in auto_update_fakes.py.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

import pytest

from auto_update_fakes import (BOOT, CURRENT, HOST, NATIVE, NEXT, REPO, T0, _retired_display, _z, device,
    history, host, hub, idle_inputs, journal, keys, kind_of, kinds, state, status, switched, upd, updater,
    write_json)


def _down(unit: str, *, after_only: bool = False):
    def override(h, argv):
        if unit in argv and (not after_only or h.links["current"] == NEXT):
            return subprocess.CompletedProcess([], 3, "", "inactive")
        return None
    return override


def _unit(name: str) -> list[str]:
    return [line.strip() for line in (NATIVE / name).read_text(encoding="utf-8").splitlines()]


def _alive(pid: int) -> bool:
    if os.name == "nt":
        listed = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in listed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # SIGKILL 로도 지워지지 않는 좀비는 죽은 것이다 — 컨테이너의 PID 1 이 고아를
    # 회수하지 않으면 kill(pid, 0) 이 좀비에게도 성공한다(CI 적색 2026-10-02).
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as fh:
            line = fh.read()
    except OSError:
        return True
    return line.rpartition(") ")[2].split()[0] != "Z"


def _units(device, *names):
    units = device / "etc/systemd/system"
    units.mkdir(parents=True, exist_ok=True)
    for name in names:
        (units / name).write_text("[Unit]" + chr(10), encoding="utf-8")
    return units


def _inactive(*units):
    return lambda h, argv: subprocess.CompletedProcess([], 3, "", "") if any(u in argv for u in units) else None


def test_apply_success_runs_the_transaction_in_order(device, host, hub, keys):
    hub.publish(keys, NEXT)

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert result["current_release"] == NEXT
    assert result["last_result"]["outcome"] == "committed"
    order = [k for k in kinds(host) if k not in {"is-active", "failed", "mainpid"}]
    assert order[:3] == ["unpack", "verify", "activate"]
    # The pre-apply baseline (active units, failed units) is taken before activation.
    before = kinds(host)[:kinds(host).index("activate")]
    assert "is-active" in before and "failed" in before
    assert order.index("sync") < order.index("restart") < order.index("ready")
    sync = next(argv for argv in host.calls if kind_of(argv) == "sync")
    assert sync[-1] == str(device / "opt/rosy/releases" / NEXT / "deploy/robot/native/sync-image-layer.py")
    restart = next(argv for argv in host.calls if kind_of(argv) == "restart")
    assert restart == ["systemctl", "restart", "rosy-io.service", "rosy-auto-update.timer"]
    assert host.t - T0 >= dt.timedelta(seconds=60)  # health held for 60 s
    assert not (device / "run/rosy-claim").exists()
    assert state(device).get("applying") is None
    events = [entry["event"] for entry in history(device)]
    assert events.index("staged") < events.index("applying") < events.index("committed")


def test_core_on_the_old_release_is_restarted(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: (setattr(h, "stale_core", True), None)[1]

    result = updater(host, hub).run()

    assert host.core_restarts == 1
    assert result["phase"] == "committed"


@pytest.mark.parametrize("failure", ["ready", "cwd", "inactive", "failed_unit", "sync", "core_restart"])
def test_health_failure_rolls_back_and_marks_the_id_failed(device, host, hub, keys, failure):
    hub.publish(keys, NEXT)
    bad = subprocess.CompletedProcess([], 1, "", "boom")
    if failure == "ready":
        host.overrides["ready"] = lambda h, argv: bad if h.links["current"] == NEXT else None
    elif failure == "cwd":
        host.overrides["cwd"] = lambda pid, release: str(
            device / "opt/rosy/releases" / (CURRENT if pid == 103 else str(release)))
    elif failure == "inactive":
        host.overrides["is-active"] = lambda h, argv: bad if "rosy-camera.service" in argv and h.links["current"] == NEXT else None
    elif failure == "failed_unit":
        host.overrides["failed"] = lambda h, argv: subprocess.CompletedProcess(
            [], 0, "rosy-hw-probe.service loaded failed failed probe\n" if h.links["current"] == NEXT else "", "")
    elif failure == "sync":
        host.overrides["sync"] = lambda h, argv: bad if NEXT in " ".join(argv) else None
    else:
        host.overrides["activate"] = lambda h, argv: (setattr(h, "stale_core", True), None)[1]
        host.overrides["restart"] = lambda h, argv: bad if "rosy-core.service" in argv and h.links["current"] == NEXT else None

    up = updater(host, hub)
    result = up.run()

    assert result["phase"] == "rolled_back", result
    assert result["last_result"]["outcome"] == "rolled_back"
    assert host.links["current"] == CURRENT
    assert "rollback" in kinds(host)
    after = kinds(host)[kinds(host).index("rollback"):]
    assert "sync" in after and "ready" in after
    rolled_sync = [argv for argv in host.calls[kinds(host).index("rollback"):] if kind_of(argv) == "sync"][0]
    assert CURRENT in rolled_sync[-1]
    assert NEXT in state(device)["failed"]
    assert not (device / "run/rosy-claim").exists()

    # never retried
    host.calls.clear()
    again = up.run()
    assert again["phase"] == "idle"
    assert "activate" not in kinds(host)


def test_camera_down_before_the_apply_does_not_block_the_commit(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["is-active"] = _down("rosy-camera.service")

    result = updater(host, hub).run()

    assert result["phase"] == "committed", result
    assert "rosy-camera.service" in result["last_result"]["detail"]
    assert NEXT not in state(device).get("failed", {})


def test_camera_up_before_and_down_after_rolls_back(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["is-active"] = _down("rosy-camera.service", after_only=True)

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    assert "rosy-camera.service" in result["last_result"]["detail"]


def test_core_is_always_required_even_if_it_was_down_before(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["is-active"] = _down("rosy-core.service")

    assert updater(host, hub).run()["phase"] == "rolled_back"


def test_io_cwd_is_not_checked_when_io_was_down_before(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["is-active"] = _down("rosy-io.service")
    host.overrides["cwd"] = lambda pid, release: str(
        device / "opt/rosy/releases" / (CURRENT if pid == 102 else str(release)))

    assert updater(host, hub).run()["phase"] == "committed"


def test_a_unit_failed_before_the_apply_does_not_block_the_commit(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["failed"] = lambda h, argv: subprocess.CompletedProcess(
        [], 0, "rosy-hw-probe.service loaded failed failed probe\n", "")

    result = updater(host, hub).run()

    assert result["phase"] == "committed", result
    assert "rosy-hw-probe.service" in result["last_result"]["detail"]


def test_a_unit_that_fails_during_the_apply_rolls_back_beside_an_old_failure(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["failed"] = lambda h, argv: subprocess.CompletedProcess(
        [], 0, "rosy-hw-probe.service loaded failed failed probe\n"
        + ("rosy-io.service loaded failed failed io\n" if h.links["current"] == NEXT else ""), "")

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    assert "rosy-io.service" in result["last_result"]["detail"]


def test_activation_busy_retries_later_and_is_not_failed(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: another operation is active"}), "")

    up = updater(host, hub)
    result = up.run()

    assert result["phase"] == "waiting"
    assert "NATIVE_RELEASE_BUSY" in result["reason"]
    assert NEXT not in state(device).get("failed", {})
    assert "rollback" not in kinds(host)
    assert not (device / "run/rosy-claim").exists()

    del host.overrides["activate"]
    assert up.run()["phase"] == "committed"


def test_activation_refused_marks_failed_without_rollback(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_PYTHON_RUNTIME: mismatch"}), "")

    result = updater(host, hub).run()

    assert result["phase"] == "image_required"
    assert result["last_result"]["outcome"] == "image_required"
    assert NEXT in state(device)["failed"]
    assert "rollback" not in kinds(host)


def test_interrupted_apply_is_finished_on_the_next_run(device, host, hub, keys):
    hub.publish(keys, NEXT)
    (device / "opt/rosy/releases" / NEXT).mkdir(parents=True)
    host.links = {"current": NEXT, "previous": CURRENT}
    write_json(device / "var/lib/rosy/updates/state.json",
               {"applying": {"release_id": NEXT, "previous": CURRENT, "started_at": _z(T0), "boot_id": BOOT}})

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert state(device).get("applying") is None
    assert any(entry["event"] == "apply_interrupted" for entry in history(device))


def test_status_and_history_follow_the_contract(device, host, hub, keys):
    hub.publish(keys, NEXT)

    updater(host, hub).run()

    current = status(device)
    assert set(current) == {"schema", "updated_at", "hostname", "current_release", "candidate",
                            "phase", "reason", "last_result"}
    assert current["schema"] == 1 and current["hostname"] == HOST
    assert current["phase"] in upd.PHASES
    assert current["updated_at"].endswith("Z")
    assert set(current["last_result"]) == {"release_id", "outcome", "at", "detail"}
    lines = history(device)
    assert lines
    for entry in lines:
        assert set(entry) == {"at", "event", "release_id", "detail", "boot_id"}
        assert entry["boot_id"] == BOOT
    raw = (device / "var/lib/rosy/updates/history.jsonl").read_bytes()
    assert b"\r\n" not in raw


def test_real_host_bounds_every_command(tmp_path):
    real = upd.Host(tmp_path)
    result = real.run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.5)
    assert result.returncode == 124
    assert "TIMEOUT" in result.stderr
    missing = real.run(["definitely-not-a-command-xyz"], timeout=5)
    assert missing.returncode == 127


def test_the_service_is_a_low_priority_root_oneshot_with_network():
    lines = _unit("rosy-auto-update.service")
    for directive in ("Type=oneshot", "Nice=19", "IOSchedulingClass=idle", "ProtectSystem=strict",
                      "ExecStart=/usr/bin/python3 -I -B /opt/rosy/native-runtime/rosy_auto_update.py run",
                      "Wants=network-online.target", "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6"):
        assert directive in lines, directive
    assert not any(line.startswith(("User=", "DynamicUser=", "PrivateNetwork=")) for line in lines)
    assert not any(line.startswith("[Install]") for line in lines)  # started by the timer only


def test_the_timer_runs_every_ten_minutes_spread_out():
    lines = _unit("rosy-auto-update.timer")
    for directive in ("OnBootSec=5min", "OnUnitActiveSec=10min", "RandomizedDelaySec=2min",
                      "WantedBy=timers.target"):
        assert directive in lines, directive
    assert not any(line.startswith("Persistent=") for line in lines)  # no effect without OnCalendar (L5)


def test_the_service_requires_recovery_and_keeps_proc_readable():
    # L8: /var/lib/rosy/releases comes from rosy-release-recover (StateDirectory), which
    # the unit requires and follows; nothing may hide other processes' /proc/<pid>/cwd.
    lines = _unit("rosy-auto-update.service")
    assert "Requires=rosy-release-recover.service" in lines
    assert any(line.startswith("After=") and "rosy-release-recover.service" in line for line in lines)
    assert not any("-/var/lib/rosy/releases" in line for line in lines)
    for forbidden in ("CapabilityBoundingSet=", "ProtectProc=", "PrivatePIDs=", "ProcSubset="):
        assert not any(line.startswith(forbidden) for line in lines), forbidden


def test_claim_ttl_outlasts_the_unit_timeout():
    # M8: the claim must not expire while the run that holds it may still be running.
    timeout = next(line.split("=", 1)[1] for line in _unit("rosy-auto-update.service")
                   if line.startswith("TimeoutStartSec="))
    assert timeout.endswith("min")
    assert upd.CLAIM_TTL_S >= int(timeout[:-3]) * 60


def test_resume_after_boot_recovery_mid_sync_resyncs_the_current_release(device, host, hub, keys):
    # H2: current != release_id and the step was later than activate.
    hub.publish(keys, NEXT)
    (device / "opt/rosy/releases" / NEXT).mkdir(parents=True)
    journal(device, "image-layer-sync")

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    sync = [argv for argv in host.calls if kind_of(argv) == "sync"]
    assert sync and CURRENT in sync[0][-1]
    assert "activate" not in kinds(host)


@pytest.mark.parametrize("outcome", [
    subprocess.CompletedProcess([], 124, "", "TIMEOUT after 900s"),
    subprocess.CompletedProcess([], 127, "", "cannot run bash"),
    subprocess.CompletedProcess([], 1, "Traceback (most recent call last)", "boom"),
], ids=["timeout", "missing", "no-json"])
def test_transient_activation_failure_is_not_marked_failed(device, host, hub, keys, outcome):
    # H3
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: outcome

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert NEXT not in state(device).get("failed", {})
    assert state(device).get("applying") is None
    del host.overrides["activate"]
    host.t += dt.timedelta(minutes=11)  # past the first apply backoff (N7)
    assert updater(host, hub).run()["phase"] == "committed"


def test_activation_failure_with_a_native_journal_recovers_and_restarts_runtime(device, host, hub, keys):
    # H3
    hub.publish(keys, NEXT)

    def killed_midway(h, argv):
        write_json(device / "var/lib/rosy/releases/native-activation.json",
                   {"schema_version": 1, "operation": "activate", "candidate": NEXT,
                    "old_current": CURRENT, "old_previous": None, "phase": "switched"})
        h.links = {"current": NEXT, "previous": CURRENT}
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["activate"] = killed_midway

    result = updater(host, hub).run()

    order = kinds(host)
    assert order.index("recover") < order.index("start")
    start = next(argv for argv in host.calls if kind_of(argv) == "start")
    assert start == ["systemctl", "start", "rosy-runtime.target"]
    assert host.links["current"] == CURRENT
    assert NEXT not in state(device).get("failed", {})
    assert result["phase"] == "error"


def test_transient_activation_failure_that_left_the_new_release_current_rolls_back_unmarked(
        device, host, hub, keys):
    # H3: no native journal, yet the switch happened: roll back but keep the id retryable.
    hub.publish(keys, NEXT)

    def switched_then_timed_out(h, argv):
        h.links = {"current": NEXT, "previous": CURRENT}
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["activate"] = switched_then_timed_out

    result = updater(host, hub).run()

    assert host.links["current"] == CURRENT
    assert "rollback" in kinds(host)
    assert NEXT not in state(device).get("failed", {})
    assert result["last_result"]["outcome"] == "rolled_back"


def test_inputs_are_checked_again_right_before_activation(device, host, hub, keys):
    # M2: the robot started moving after eligibility passed.
    hub.publish(keys, NEXT)
    seen = {"n": 0}

    def started_moving(h, argv):
        seen["n"] += 1
        h.inputs_changes = {"robot_mode": "MANUAL"}
        h.write_inputs()
        return None

    host.overrides["failed"] = started_moving  # the baseline lists failed units before activation

    result = updater(host, hub).run()

    assert seen["n"] >= 1
    assert result["phase"] == "ineligible"
    assert "activate" not in kinds(host)
    assert state(device).get("applying") is None
    assert not (device / "run/rosy-claim").exists()


def test_old_and_failed_release_directories_are_pruned_after_commit(device, host, hub, keys):
    # M5
    releases = device / "opt/rosy/releases"
    stamp = (T0 - dt.timedelta(hours=2)).timestamp()
    for old in ("2026.09.30-001", "2026.09.30-002"):
        (releases / old).mkdir()
        os.utime(releases / old, (stamp, stamp))  # older than the 1 h prune guard (N6)
    host.links["previous"] = "2026.09.30-002"
    (releases / ".tmp-2026.10.01-099-1").mkdir()
    hub.publish(keys, NEXT)

    assert updater(host, hub).run()["phase"] == "committed"

    left = sorted(path.name for path in releases.iterdir())
    assert left == [".tmp-2026.10.01-099-1", CURRENT, NEXT]  # current=NEXT, previous=CURRENT


def test_the_claim_is_refreshed_at_each_journal_step(device, host, hub, keys):
    # M8
    hub.publish(keys, NEXT)
    seen = {}

    def slow_sync(h, argv):
        h.t += dt.timedelta(seconds=2000)
        return None

    def capture(h, argv):
        seen["claim"] = json.loads((device / "run/rosy-claim/claim.json").read_text(encoding="utf-8"))
        seen["t"] = h.t
        return None

    host.overrides["sync"] = slow_sync
    host.overrides["restart"] = capture

    assert updater(host, hub).run()["phase"] == "committed"
    expires = upd.parse_z(seen["claim"]["expires_at"])
    assert expires >= seen["t"] + dt.timedelta(seconds=upd.CLAIM_TTL_S - 1)


def test_history_records_only_changes_of_phase_or_reason_class(device, host, hub, keys):
    # L4
    hub.publish(keys, NEXT)
    write_json(device / "run/rosy/status-inputs.json", idle_inputs(T0 - dt.timedelta(seconds=100)))
    host.write_inputs = lambda: None
    up = updater(host, hub)
    up.run()
    host.t += dt.timedelta(seconds=60)
    up.run()

    ineligible = [entry for entry in history(device) if entry["event"] == "ineligible"]
    assert len(ineligible) == 1


def test_history_rotates_at_its_size_limit(device, host, hub, monkeypatch):
    # L4
    monkeypatch.setattr(sys.modules["auto_update_records"], "HISTORY_MAX_BYTES", 400)  # read by _history
    up = updater(host, hub)
    for index in range(10):
        up.hold("agent", f"reason {index}", 1)
    path = device / "var/lib/rosy/updates/history.jsonl"
    assert path.stat().st_size <= 400 + 300
    assert (device / "var/lib/rosy/updates/history.jsonl.1").is_file()


def test_real_host_kills_the_whole_process_group_on_timeout(tmp_path):
    # L6: a grandchild of a timed-out command must not survive it.
    marker = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"open(r'{marker}', 'w').write(str(p.pid))\n"
        "time.sleep(30)\n"
    )
    result = upd.Host(tmp_path).run([sys.executable, "-c", script], timeout=3)
    assert result.returncode == 124
    pid = int(marker.read_text())
    deadline = dt.datetime.now() + dt.timedelta(seconds=5)
    while dt.datetime.now() < deadline and _alive(pid):
        pass
    assert not _alive(pid), (result, subprocess.run(
        ["ps", "-o", "pid,ppid,pgid,stat,args", "-p", str(pid)],
        capture_output=True, text=True).stdout)


def test_disabled_while_applying_still_finishes_the_apply(device, host, hub, keys):
    # L9
    hub.publish(keys, NEXT)
    switched(device, host)
    journal(device, "health")
    write_json(device / "var/lib/rosy/updates/config.json", {"enabled": False, "repo": REPO})

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert hub.requests == []


def test_unexpected_exception_after_activation_rolls_back(device, host, hub, keys):
    hub.publish(keys, NEXT)

    def explode(h, argv):
        raise RuntimeError("bug in a helper")

    host.overrides["restart"] = lambda h, argv: explode(h, argv) if h.links["current"] == NEXT else None

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    assert "UNEXPECTED" in result["last_result"]["detail"]
    assert host.links["current"] == CURRENT


def test_repeated_transient_apply_failures_back_off_then_hold(device, host, hub, keys):
    # N7
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess([], 124, "", "TIMEOUT")
    up = updater(host, hub)
    for attempt in range(1, 4):
        assert up.run()["phase"] == "error"
        assert kinds(host).count("activate") == attempt
        # inside the backoff no activation; after the third failure the robot is held
        assert up.run()["phase"] == ("waiting" if attempt < 3 else "held")
        assert kinds(host).count("activate") == attempt
        host.t += dt.timedelta(hours=7)

    result = up.run()

    assert result["phase"] == "held"
    assert result["reason"] == upd.ESCALATED_REASON
    assert result["reason"].startswith("repeated transient apply failures; operator action required")
    assert kinds(host).count("activate") == 3
    assert NEXT not in state(device).get("failed", {})

    del host.overrides["activate"]
    up.release_hold()  # operator action clears the count
    assert up.run()["phase"] == "committed"


def test_prune_skips_young_directories_and_runs_under_the_release_lock(device, host, hub, keys):
    # N6
    releases = device / "opt/rosy/releases"
    old = releases / "2026.09.30-001"
    young = releases / "2026.09.30-002"
    old.mkdir()
    young.mkdir()
    stamp = (T0 - dt.timedelta(hours=2)).timestamp()
    os.utime(old, (stamp, stamp))
    young_stamp = (T0 - dt.timedelta(minutes=30)).timestamp()
    os.utime(young, (young_stamp, young_stamp))
    up = updater(host, hub)

    with up._locked_file(device / "var/lib/rosy/releases/native-release.lock"):
        up._prune({})
    assert old.exists()  # lock busy: nothing pruned

    up._prune({})
    assert not old.exists() and young.exists()

    os.utime(young, (stamp, stamp))
    host.links = {"current": None, "previous": None}
    up._prune({})
    assert young.exists()  # no current: never prune


def test_a_failed_rollback_recovers_a_native_journal(device, host, hub, keys):
    # N8, N10
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)

    def died_midway(h, argv):
        write_json(device / "var/lib/rosy/releases/native-activation.json",
                   {"schema_version": 1, "operation": "rollback", "candidate": CURRENT,
                    "old_current": NEXT, "old_previous": CURRENT, "phase": "prepared"})
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["rollback"] = died_midway

    updater(host, hub).run()

    order = kinds(host)
    assert "recover" in order and order.index("recover") < order.index("start")


def test_runtime_is_not_started_when_recover_fails(device, host, hub, keys):
    # N10
    hub.publish(keys, NEXT)

    def killed_midway(h, argv):
        write_json(device / "var/lib/rosy/releases/native-activation.json", {"bad": True})
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["activate"] = killed_midway
    host.overrides["recover"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RECOVERY_HOLD: invalid"}), "")

    updater(host, hub).run()

    assert "recover" in kinds(host)
    assert "start" not in kinds(host)


def test_interrupted_activation_that_never_switched_is_not_a_failure(device, host, hub, keys):
    # N11
    hub.publish(keys, NEXT)
    (device / "opt/rosy/releases" / NEXT).mkdir(parents=True)
    journal(device, "activate")

    result = updater(host, hub).run()

    assert NEXT not in state(device).get("failed", {})
    assert state(device).get("applying") is None
    assert result["phase"] == "waiting"


def test_runtime_mismatch_is_definitive(device, host, hub, keys):
    # L1
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RUNTIME_MISMATCH: core-only native systemd"}), "")
    assert updater(host, hub).run()["phase"] == "failed"
    assert NEXT in state(device)["failed"]


def test_escalation_reasons_name_the_remedy(device, host, hub, keys):
    # L3
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess([], 124, "", "TIMEOUT")
    up = updater(host, hub)
    for _ in range(3):
        up.run()
        host.t += dt.timedelta(hours=7)
    result = up.run()
    assert result["phase"] == "held"
    assert "release-hold" in result["reason"]


def test_the_update_marker_follows_the_apply_and_is_gone_after(device, host, hub, keys):
    hub.publish(keys, NEXT)
    seen = []

    def during_sync(h, argv):
        marker = device / upd.UPDATE_DISPLAY
        seen.append(marker.read_text(encoding="utf-8") if marker.exists() else None)
        return None

    host.overrides["sync"] = during_sync

    result = updater(host, hub).run()

    assert result["phase"] == "committed", result
    assert seen and seen[0] == f"image-layer-sync\n{NEXT}\n"
    assert not (device / upd.UPDATE_DISPLAY).exists()


@pytest.mark.parametrize("case", ["face_installed", "already_running", "disabled"])
def test_the_old_display_is_left_alone_otherwise(device, host, hub, keys, case):
    hub.publish(keys, NEXT)
    units = _retired_display(device)
    if case == "face_installed":
        (units / upd.FACE_UNIT).write_text("[Unit]\n", encoding="utf-8")
    if case == "disabled":
        host.overrides["is-enabled"] = lambda h, argv: subprocess.CompletedProcess([], 1, "", "")
    if case != "already_running":
        host.overrides["is-active"] = lambda h, argv: (
            subprocess.CompletedProcess([], 3, "", "") if upd.RETIRED_DISPLAY_UNIT in argv else None)
    bad = subprocess.CompletedProcess([], 1, "", "boom")
    host.overrides["ready"] = lambda h, argv: bad if h.links["current"] == NEXT else None

    updater(host, hub).run()

    assert ["systemctl", "start", upd.RETIRED_DISPLAY_UNIT] not in host.calls


def test_this_updater_swaps_the_display_to_rosy_face_once(device, host, hub, keys):
    # D-433 review HIGH2: the live swap is this updater's, never the sync's.
    _units(device, upd.FACE_UNIT, upd.RETIRED_DISPLAY_UNIT)
    host.overrides["is-active"] = _inactive(upd.FACE_UNIT)

    updater(host, hub).run()

    stop = host.calls.index(["systemctl", "stop", upd.RETIRED_DISPLAY_UNIT])
    assert host.calls.index(["systemctl", "start", upd.FACE_UNIT]) > stop


@pytest.mark.parametrize("case", ["no_face", "face_running", "old_not_running", "face_disabled"])
def test_no_swap_otherwise(device, host, hub, keys, case):
    names = [upd.RETIRED_DISPLAY_UNIT] + ([] if case == "no_face" else [upd.FACE_UNIT])
    _units(device, *names)
    if case in ("no_face", "face_disabled"):
        host.overrides["is-active"] = _inactive(upd.FACE_UNIT)
    if case == "old_not_running":
        host.overrides["is-active"] = _inactive(upd.FACE_UNIT, upd.RETIRED_DISPLAY_UNIT)
    if case == "face_disabled":
        host.overrides["is-enabled"] = lambda h, argv: subprocess.CompletedProcess([], 1, "", "")

    updater(host, hub).run()

    assert ["systemctl", "stop", upd.RETIRED_DISPLAY_UNIT] not in host.calls
    assert ["systemctl", "start", upd.FACE_UNIT] not in host.calls
