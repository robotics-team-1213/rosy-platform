"""D-412 updater: resume after an interruption, the core-down waiver and rollback review.

Moved out of test/test_rosy_auto_update.py (D-798); the fakes are in auto_update_fakes.py.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess

import pytest

from auto_update_fakes import (CURRENT, FakeHost, NEWER, NEXT, T0, _retired_display, _stale_inputs, _z,
    claim_mod, device, history, host, hub, journal, keys, kind_of, kinds, state, status, switched, upd,
    updater, write_json)


RESTARTING = {"sync", "restart", "rollback", "activate", "start"}


def _core_state(active: str, sub: str, pid: int, returncode: int = 0):
    return lambda h, argv: subprocess.CompletedProcess(
        [], returncode, f"ActiveState={active}\nSubState={sub}\nMainPID={pid}\n" if returncode == 0 else "", "")


def _core_down_until_restarted(host: FakeHost, *, fresh_after_restart: bool = False,
                               active: str = "inactive", sub: str = "dead") -> None:
    host.core_up = False
    real_write = FakeHost.write_inputs

    def core_state(h, argv):
        if h.core_up:
            return None
        return _core_state(active, sub, 0)(h, argv)

    def is_active(h, argv):
        if "rosy-core.service" in argv and not h.core_up:
            return subprocess.CompletedProcess([], 3, "", "inactive")
        return None

    def restart(h, argv):
        if "rosy-core.service" in argv:
            h.core_up = True
            if fresh_after_restart:
                h.write_inputs = lambda: real_write(h)
                h.write_inputs()
        return None

    def mainpid(h, argv):
        if argv[-1] == "rosy-core.service" and not h.core_up:
            return subprocess.CompletedProcess([], 0, "0\n", "")
        return None

    host.overrides.update({"corestate": core_state, "is-active": is_active, "restart": restart,
                           "mainpid": mainpid})


def _resume_case(device, host, hub, keys, step="image-layer-sync"):
    hub.publish(keys, NEXT)
    switched(device, host)
    journal(device, step)


def _switched_then_timed_out(h, argv):
    h.links = {"current": NEXT, "previous": CURRENT}
    return subprocess.CompletedProcess([], 124, "", "TIMEOUT")


def test_resume_waits_for_a_hold_before_any_restart(device, host, hub, keys):
    # H1
    hub.publish(keys, NEXT)
    switched(device, host)
    journal(device, "health")
    up = updater(host, hub)
    up.hold("agent", "G5", 2)

    result = up.run()

    assert result["phase"] == "held"
    assert not RESTARTING & set(kinds(host))  # reading MainPID (is CORE running?) is allowed
    assert state(device)["applying"]["release_id"] == NEXT

    up.release_hold()
    assert up.run()["phase"] == "committed"


@pytest.mark.parametrize("cause", ["moving", "sealed", "same_sample"])
def test_resume_waits_until_the_robot_is_idle(device, host, hub, keys, cause):
    # H1 (+ M1 in the resume path)
    hub.publish(keys, NEXT)
    switched(device, host)
    journal(device, "image-layer-sync")
    if cause == "moving":
        host.inputs_changes = {"velocity_linear": 0.3}
        host.write_inputs()
    elif cause == "sealed":
        write_json(device / "etc/rosy/approvals/hardware.approved", {"release_id": NEXT})
    else:
        host.write_inputs = lambda: None

    result = updater(host, hub).run()

    assert result["phase"] in {"held", "ineligible"}
    assert not RESTARTING & set(kinds(host))
    assert state(device)["applying"]["step"] == "image-layer-sync"


def test_resume_after_rollback_step_never_commits(device, host, hub, keys):
    # H2: the journal reached rollback with the new release still current.
    hub.publish(keys, NEXT)
    switched(device, host)
    journal(device, "rollback", why="HEALTH: x")

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    assert host.links["current"] == CURRENT
    order = kinds(host)
    assert order.index("rollback") < order.index("sync") < order.index("ready")
    assert NEXT in state(device)["failed"]
    assert state(device).get("applying") is None


def test_resume_after_rollback_step_with_old_release_current_still_syncs(device, host, hub, keys):
    # H2: rollback-release.sh already ran; only the tail is left.
    hub.publish(keys, NEXT)
    (device / "opt/rosy/releases" / NEXT).mkdir(parents=True)
    host.links = {"current": CURRENT, "previous": NEXT}
    journal(device, "rollback", why="HEALTH: x")

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back"
    assert "rollback" not in kinds(host)
    sync = [argv for argv in host.calls if kind_of(argv) == "sync"]
    assert sync and CURRENT in sync[0][-1]
    assert "ready" in kinds(host)


def test_operator_rollback_of_a_committed_release_is_respected(device, host, hub, keys):
    # H4
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    assert up.run()["phase"] == "committed"
    assert NEXT in state(device)["committed"]
    host.links = {"current": CURRENT, "previous": NEXT}  # rosy-release-push.ps1 -Rollback
    host.calls.clear()

    result = up.run()

    assert result["phase"] == "idle"
    assert state(device)["failed"][NEXT]["detail"] == "operator rolled back"
    assert "activate" not in kinds(host)


@pytest.mark.parametrize("outcome", [
    subprocess.CompletedProcess([], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), ""),
    subprocess.CompletedProcess([], 124, "", "TIMEOUT"),
], ids=["busy", "timeout"])
def test_a_rollback_that_cannot_run_now_is_retried(device, host, hub, keys, outcome):
    # M7
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)
    host.overrides["rollback"] = lambda h, argv: outcome
    up = updater(host, hub)

    result = up.run()

    assert result["phase"] == "error"
    assert state(device)["applying"]["step"] == "rollback"
    assert host.links["current"] == NEXT

    del host.overrides["rollback"]
    final = up.run()
    assert final["phase"] == "rolled_back"
    assert host.links["current"] == CURRENT
    assert state(device).get("applying") is None


def test_resume_with_core_down_waives_the_idleness_check(device, host, hub, keys):
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host, fresh_after_restart=True)
    _stale_inputs(device, host)

    result = updater(host, hub).run()

    assert result["phase"] == "committed", result
    assert "core not running; idleness check waived" in result["last_result"]["detail"]
    assert any("idleness check waived" in entry["detail"] for entry in history(device))


@pytest.mark.parametrize("active,sub", [("failed", "failed"), ("activating", "auto-restart")])
def test_failed_or_restarting_core_without_a_pid_is_down(device, host, hub, keys, active, sub):
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host, fresh_after_restart=True, active=active, sub=sub)
    _stale_inputs(device, host)

    assert updater(host, hub).run()["phase"] == "committed"


@pytest.mark.parametrize("override", [
    _core_state("active", "running", 0),           # active without a MainPID
    _core_state("inactive", "dead", 4242),         # a PID still recorded
    _core_state("activating", "start-pre", 0),     # starting, not crash-looping
    _core_state("inactive", "dead", 0, returncode=1),  # systemctl failed: assume running
    lambda h, argv: subprocess.CompletedProcess([], 0, "garbage\n", ""),
], ids=["active-no-pid", "pid-left", "start-pre", "systemctl-failed", "unparseable"])
def test_anything_else_counts_as_core_running(device, host, hub, keys, override):
    _resume_case(device, host, hub, keys)
    host.overrides["corestate"] = override
    _stale_inputs(device, host)

    result = updater(host, hub).run()

    assert result["phase"] == "ineligible"
    assert "waived" not in result["reason"]
    assert not RESTARTING & set(kinds(host))


def test_resume_with_core_down_still_honours_a_hold(device, host, hub, keys):
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host)
    _stale_inputs(device, host)
    up = updater(host, hub)
    up.hold("agent", "G5", 2)

    result = up.run()

    assert result["phase"] == "held"
    assert not RESTARTING & set(kinds(host))
    assert state(device)["applying"]["step"] == "image-layer-sync"


def test_resume_with_core_down_still_honours_a_seal_and_a_claim(device, host, hub, keys):
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host)
    _stale_inputs(device, host)
    claim_mod.acquire(device, "push-pc", "release push", 1800, now=T0)

    result = updater(host, hub).run()

    assert result["phase"] == "ineligible"
    assert "push-pc" in result["reason"]
    assert not RESTARTING & set(kinds(host))


def test_resume_with_core_active_and_stale_inputs_is_ineligible(device, host, hub, keys):
    _resume_case(device, host, hub, keys)
    _stale_inputs(device, host)

    result = updater(host, hub).run()

    assert result["phase"] == "ineligible"
    assert "waived" not in result["reason"]
    assert not RESTARTING & set(kinds(host))


def test_waived_resume_defers_when_core_comes_back_without_idle_status(device, host, hub, keys):
    # N4: CORE restarted by the core-release check; before restarting units the
    # normal idleness check applies, and stale inputs defer the resume.
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host, fresh_after_restart=False)
    _stale_inputs(device, host)

    result = updater(host, hub).run()

    assert result["phase"] == "ineligible"
    assert "deferred" in result["reason"]
    assert state(device)["applying"]["release_id"] == NEXT
    assert not any(kind_of(argv) == "restart" and "rosy-io.service" in argv for argv in host.calls)
    assert "rollback" not in kinds(host)


def test_the_waiver_note_is_dropped_once_core_runs_again(device, host, hub, keys):
    # N15: a later resume with CORE running must not carry the old waiver note.
    _resume_case(device, host, hub, keys)
    _core_down_until_restarted(host, fresh_after_restart=False)
    _stale_inputs(device, host)
    up = updater(host, hub)
    assert up.run()["phase"] == "ineligible"
    host.write_inputs = lambda: FakeHost.write_inputs(host)
    host.write_inputs()

    result = up.run()

    assert result["phase"] == "committed", result
    assert "waived" not in result["last_result"]["detail"]


def test_core_active_but_silent_for_30_minutes_is_stuck(device, host, hub, keys):
    # N5: no auto-rollback; tell the operator.
    _resume_case(device, host, hub, keys)
    _stale_inputs(device, host)
    assert updater(host, hub).run()["phase"] == "ineligible"  # silent_since = T0
    host.t = T0 + dt.timedelta(minutes=29)
    assert updater(host, hub).run()["phase"] == "ineligible"

    host.t = T0 + dt.timedelta(minutes=31)
    result = updater(host, hub).run()

    assert result["phase"] == "stuck"
    assert result["reason"].startswith("CORE active but not writing status; operator action required")
    assert "rosy-release-push.ps1 -Rollback" in result["reason"]  # L3
    assert state(device)["applying"]["release_id"] == NEXT
    assert not RESTARTING & set(kinds(host))


def test_previous_above_current_is_an_operator_rollback(device, host, hub, keys):
    # N9
    (device / "opt/rosy/releases" / NEXT).mkdir(parents=True)
    host.links = {"current": CURRENT, "previous": NEXT}
    hub.publish(keys, NEXT)

    result = updater(host, hub).run()

    assert result["phase"] == "idle"
    assert state(device)["failed"][NEXT]["detail"] == "operator rolled back"


def test_rollback_pending_gives_up_after_five_retries(device, host, hub, keys):
    # N12
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), "")
    up = updater(host, hub)
    results = [up.run() for _ in range(7)]
    phases = [result["phase"] for result in results]

    # the first attempt and five retries; the sixth failure gives up
    assert phases[:5] == ["error"] * 5
    assert phases[5] == "failed"
    assert "operator" in results[5]["reason"]
    assert state(device).get("applying") is None
    assert kinds(host).count("rollback") == 6
    assert phases[6] == "failed"  # stays visible (L2), no further rollback attempts


def test_a_self_rollback_is_not_mistaken_for_an_operator_rollback(device, host, hub, keys):
    # HIGH: N9 must not catch our own unmarked rollback (N7); the release is retried.
    hub.publish(keys, NEXT)

    def switched_then_timed_out(h, argv):
        h.links = {"current": NEXT, "previous": CURRENT}
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["activate"] = switched_then_timed_out
    up = updater(host, hub)
    up.run()
    assert host.links == {"current": CURRENT, "previous": NEXT}
    assert NEXT not in state(device).get("failed", {})

    del host.overrides["activate"]
    host.t += dt.timedelta(hours=1)
    result = up.run()

    assert NEXT not in state(device).get("failed", {}), state(device).get("failed")
    assert result["phase"] == "committed", result
    assert NEXT not in state(device).get("self_rolled_back", {})  # cleared by the commit


def test_stuck_is_measured_from_the_first_silent_resume(device, host, hub, keys):
    # M1: an old journal is not stuck the moment it is first seen silent.
    _resume_case(device, host, hub, keys)
    journal(device, "image-layer-sync", started_at=_z(T0 - dt.timedelta(hours=2)))
    _stale_inputs(device, host)
    up = updater(host, hub)

    assert up.run()["phase"] == "ineligible"
    assert state(device)["applying"]["silent_since"] == _z(T0)
    host.t = T0 + dt.timedelta(minutes=29)
    assert up.run()["phase"] == "ineligible"
    host.t = T0 + dt.timedelta(minutes=31)
    assert up.run()["phase"] == "stuck"


def test_silent_since_restarts_after_a_held_resume(device, host, hub, keys):
    # M1: silence, then a hold, then silence again is a new silent period.
    _resume_case(device, host, hub, keys)
    _stale_inputs(device, host)
    up = updater(host, hub)
    assert up.run()["phase"] == "ineligible"
    assert state(device)["applying"]["silent_since"] == _z(T0)

    up.hold("agent", "x", 1)
    host.t = T0 + dt.timedelta(minutes=5)
    assert up.run()["phase"] == "held"
    assert "silent_since" not in state(device)["applying"]

    up.release_hold()
    host.t = T0 + dt.timedelta(minutes=31)
    assert up.run()["phase"] == "ineligible"  # not stuck: silent only since now
    assert state(device)["applying"]["silent_since"] == _z(host.t)


def test_silent_since_is_cleared_by_an_eligible_resume(device, host, hub, keys):
    # M1: an eligible (waived, then deferred) resume ends the silent period.
    _resume_case(device, host, hub, keys)
    _stale_inputs(device, host)
    up = updater(host, hub)
    assert up.run()["phase"] == "ineligible"
    assert state(device)["applying"]["silent_since"] == _z(T0)

    _core_down_until_restarted(host, fresh_after_restart=False)
    host.t = T0 + dt.timedelta(minutes=5)
    result = up.run()
    assert result["phase"] == "ineligible" and "deferred" in result["reason"]
    assert "silent_since" not in state(device)["applying"]

    host.t = T0 + dt.timedelta(minutes=31)
    assert up.run()["phase"] == "ineligible"  # CORE back but silent: a new period, not stuck


def test_rollback_failure_stays_visible(device, host, hub, keys):
    # L2: after the N12 cap the robot keeps saying so until a person fixes it.
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), "")
    up = updater(host, hub)
    for _ in range(6):
        up.run()
    assert state(device)["last_result"]["outcome"] == "rollback_failed"

    result = up.run()

    assert result["phase"] == "failed"
    assert result["last_result"]["outcome"] == "rollback_failed"
    assert "rosy-release-push.ps1 -Rollback" in result["reason"]
    assert kinds(host).count("rollback") == 6

    host.links = {"current": CURRENT, "previous": NEXT}  # the operator rolled back
    assert up.run()["phase"] == "idle"


def test_a_rollback_that_gave_up_then_an_operator_rollback_fails_the_release(device, host, hub, keys):
    # HIGH 1 (the reviewer's probe): our rollback never moved current, so the
    # operator's later rollback is an operator rollback (N9).
    hub.publish(keys, NEXT)
    host.overrides["activate"] = _switched_then_timed_out
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), "")
    up = updater(host, hub)
    for _ in range(6):
        up.run()
    assert state(device)["last_result"]["outcome"] == "rollback_failed"
    assert NEXT not in (state(device).get("self_rolled_back") or {})

    del host.overrides["activate"], host.overrides["rollback"]
    host.links = {"current": CURRENT, "previous": NEXT}  # rosy-release-push.ps1 -Rollback
    host.t += dt.timedelta(minutes=5)
    up.run()

    assert state(device)["failed"][NEXT]["detail"] == "operator rolled back"
    assert kinds(host).count("activate") == 1


def test_a_definitive_rollback_error_is_not_a_self_rollback(device, host, hub, keys):
    # HIGH 1
    hub.publish(keys, NEXT)
    host.overrides["activate"] = _switched_then_timed_out
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "SIGNATURE_INVALID: previous does not verify"}), "")

    updater(host, hub).run()

    assert host.links["current"] == NEXT
    assert NEXT not in (state(device).get("self_rolled_back") or {})


def test_a_failing_rollback_tail_still_backs_off(device, host, hub, keys):
    # HIGH 2 (the reviewer's probe): moved away but the tail failed; the apply
    # error must still be counted so the loop is bounded.
    hub.publish(keys, NEXT)
    host.overrides["activate"] = _switched_then_timed_out
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == CURRENT else None)
    up = updater(host, hub)
    for _ in range(6):
        host.t += dt.timedelta(minutes=5)
        up.run()

    assert kinds(host).count("activate") <= 3
    assert state(device)["apply_errors"][NEXT]["attempts"] >= 1
    assert NEXT in state(device)["self_rolled_back"]  # it did move current away


def test_release_hold_acknowledges_a_rollback_failure(device, host, hub, keys):
    # MEDIUM
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), "")
    up = updater(host, hub)
    for _ in range(6):
        up.run()
    sticky = up.run()
    assert sticky["phase"] == "failed" and "release-hold" in sticky["reason"]

    up.release_hold()

    assert state(device).get("last_result") is None
    assert up.run()["phase"] != "failed"


def test_stale_self_rollback_entries_are_pruned(device, host, hub, keys):
    # LOW
    hub.publish(keys, NEXT)
    write_json(device / "var/lib/rosy/updates/state.json", {
        "self_rolled_back": {CURRENT: _z(T0), NEWER: _z(T0), "2026.10.01-030": _z(T0), NEXT: _z(T0)},
        "failed": {NEWER: {"at": _z(T0), "detail": "x"}},
        "withdrawn": {"2026.10.01-030": {"at": _z(T0), "reason": "x"}},
    })
    up = updater(host, hub)
    up.hold("agent", "x", 1)

    up.run()

    assert set(state(device)["self_rolled_back"]) == {NEXT}


def test_a_refused_rollback_is_a_sticky_acknowledgeable_rollback_failure(device, host, hub, keys):
    # LOW 1
    hub.publish(keys, NEXT)
    host.overrides["ready"] = lambda h, argv: (subprocess.CompletedProcess([], 1, "", "x")
                                              if h.links["current"] == NEXT else None)
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "SIGNATURE_INVALID: previous does not verify"}), "")
    up = updater(host, hub)
    up.run()
    assert state(device)["last_result"]["outcome"] == "rollback_failed"

    sticky = up.run()
    assert sticky["phase"] == "failed" and "release-hold" in sticky["reason"]
    assert up.release_hold()["acknowledged_rollback_failure"] == NEXT
    assert up.run()["phase"] != "failed"


def test_release_hold_reports_what_it_acknowledged(device, host, hub, keys, capsys, monkeypatch):
    # LOW 2
    up = updater(host, hub)
    up.hold("agent", "x", 1)
    write_json(device / "var/lib/rosy/updates/state.json", {
        "apply_errors": {NEXT: {"attempts": 3}, NEWER: {"attempts": 1}},
        "last_result": {"release_id": NEXT, "outcome": "rollback_failed", "at": _z(T0), "detail": "x"},
    })
    monkeypatch.setattr(upd, "Host", lambda root: host)

    assert upd.main(["--root", str(device), "release-hold"]) == 0
    out = json.loads(capsys.readouterr().out)

    assert out == {"ok": True, "released": True, "acknowledged_rollback_failure": NEXT,
                   "cleared_apply_errors": [NEXT, NEWER]}

    assert upd.main(["--root", str(device), "release-hold"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "released": False,
                                                   "acknowledged_rollback_failure": None,
                                                   "cleared_apply_errors": []}


def test_self_rollback_entries_below_current_are_pruned_unless_previous(device, host, hub, keys):
    # LOW 3
    hub.publish(keys, NEXT)
    host.links = {"current": CURRENT, "previous": "2026.10.01-019"}
    write_json(device / "var/lib/rosy/updates/state.json", {
        "self_rolled_back": {"2026.10.01-018": _z(T0), "2026.10.01-019": _z(T0), NEXT: _z(T0)},
    })
    up = updater(host, hub)
    up.hold("agent", "x", 1)

    up.run()

    assert set(state(device)["self_rolled_back"]) == {"2026.10.01-019", NEXT}


def test_acknowledged_unmarked_rollback_failure_then_operator_rollback(device, host, hub, keys):
    # LOW 4: the mark_failed=False variant: transient switch, the rollback never runs.
    hub.publish(keys, NEXT)

    def switched_then_timed_out(h, argv):
        h.links = {"current": NEXT, "previous": CURRENT}
        return subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    host.overrides["activate"] = switched_then_timed_out
    host.overrides["rollback"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_RELEASE_BUSY: x"}), "")
    up = updater(host, hub)
    for _ in range(6):
        up.run()
    assert state(device)["last_result"]["outcome"] == "rollback_failed"
    assert NEXT not in state(device).get("failed", {})

    assert up.release_hold()["acknowledged_rollback_failure"] == NEXT
    del host.overrides["activate"], host.overrides["rollback"]
    host.t += dt.timedelta(hours=7)
    assert up.run()["phase"] != "failed"
    assert kinds(host).count("activate") == 1  # NEXT is current: nothing to activate again

    host.links = {"current": CURRENT, "previous": NEXT}  # rosy-release-push.ps1 -Rollback
    up.run()
    assert state(device)["failed"][NEXT]["detail"] == "operator rolled back"
    assert kinds(host).count("activate") == 1


def test_a_rollback_past_rosy_face_starts_the_old_display_once(device, host, hub, keys):
    hub.publish(keys, NEXT)
    _retired_display(device)
    bad = subprocess.CompletedProcess([], 1, "", "boom")
    host.overrides["ready"] = lambda h, argv: bad if h.links["current"] == NEXT else None
    host.overrides["is-active"] = lambda h, argv: (
        subprocess.CompletedProcess([], 3, "", "") if upd.RETIRED_DISPLAY_UNIT in argv else None)

    result = updater(host, hub).run()

    assert result["phase"] == "rolled_back", result
    starts = [argv for argv in host.calls if argv == ["systemctl", "start", upd.RETIRED_DISPLAY_UNIT]]
    assert len(starts) == 1
    assert not (device / upd.UPDATE_DISPLAY).exists()


def test_a_waiting_journal_clears_the_update_marker(device, host, hub, keys):
    # D-433 review MED3: a held apply must not keep "Updating" over STOPPED or CORE-missing.
    hub.publish(keys, NEXT)
    switched(device, host)
    journal(device, "health")
    marker = device / upd.UPDATE_DISPLAY
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("health" + chr(10) + NEXT + chr(10), encoding="utf-8")
    up = updater(host, hub)
    up.hold("agent", "G5", 2)

    assert up.run()["phase"] == "held"
    assert not marker.exists()

    up.release_hold()
    assert up.run()["phase"] == "committed"
    assert not marker.exists()
