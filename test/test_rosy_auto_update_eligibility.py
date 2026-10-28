"""D-412 updater: the idle check, holds, sealed approvals, claims and the precheck.

Moved out of test/test_rosy_auto_update.py (D-798); the fakes are in auto_update_fakes.py.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import os
import subprocess

import pytest

from auto_update_fakes import (CURRENT, NEXT, T0, _stale_inputs, _z, claim_mod, device, history, host, hub,
    idle_inputs, keys, kind_of, kinds, state, status, upd, updater, write_json)


def test_idle_robot_is_eligible(device, host, hub):
    report = updater(host, hub).eligibility()
    assert report["eligible"] is True, report
    assert report["reasons"] == []


@pytest.mark.parametrize("changes", [
    {"robot_mode": "MANUAL"},
    {"robot_mode": None},
    {"nav_state": "NAVIGATING"},
    {"nav_state": "PLANNING"},
    {"nav_state": None},
    {"line_follow_mode": "IR_LINE"},
    {"docking_state": "DOCKING"},
    {"docking_state": "UNDOCKING"},
    {"swarm_active": True},
    {"estop": True},
    {"activity_kind": "CALIBRATING"},
    {"velocity_linear": 0.05},
    {"velocity_linear": -0.05},
    {"velocity_angular": 0.2},
    {"velocity_linear": None},
    {"velocity_linear": True},
    {"battery_percent": 39.0, "battery_charging": False},
    {"battery_percent": None, "battery_charging": False},
    {"battery_percent": None, "battery_charging": None},
    # Contract amendment b63cb7f2: null is unknown, unknown is ineligible, checked first.
    {"battery_percent": None, "battery_charging": True},
    {"battery_percent": float("nan"), "battery_charging": True},
    {"battery_percent": float("inf")},
    {"estop": None},
    {"swarm_active": None},
    {"line_follow_mode": None},
    {"line_follow_state": None},
    {"velocity_linear": None, "velocity_angular": 0.0},
    {"velocity_angular": None},
    {"velocity_linear": float("nan")},
    {"velocity_angular": float("-inf")},
    {"velocity_linear": "0"},
    {"battery_percent": "80", "battery_charging": True},
    {"battery_percent": True, "battery_charging": True},
    {"swarm_role": "leader"},
    {"swarm_role": "follower"},
    {"schema": 1},
    {"schema": "2"},
    {"written_at": "2026-10-01T15:58:59+00:00"},  # 61 s old
    {"written_at": "not a time"},
], ids=lambda c: ",".join(f"{k}={v}" for k, v in c.items()))
def test_each_busy_signal_makes_the_robot_ineligible(device, host, hub, changes):
    host.inputs_changes = changes
    host.write_inputs()

    report = updater(host, hub).eligibility()

    assert report["eligible"] is False
    assert report["reasons"]


@pytest.mark.parametrize("changes", [
    {"battery_percent": 30.0, "battery_charging": True},
    {"battery_percent": 40.0},
    {"nav_state": "ARRIVED"},
    {"docking_state": "DOCKED"},
    {"velocity_linear": 0.004, "velocity_angular": -0.01},
    {"schema": 3},
    {"swarm_role": "none"},
    {"swarm_role": None},
    {"battery_percent": 80.0, "battery_charging": None},
], ids=lambda c: ",".join(f"{k}={v}" for k, v in c.items()))
def test_values_that_do_not_block(device, host, hub, changes):
    host.inputs_changes = changes
    host.write_inputs()

    report = updater(host, hub).eligibility()

    assert report["eligible"] is True, report


@pytest.mark.parametrize("missing", ["velocity_linear", "battery_charging", "docking_state",
                                     "line_follow_mode", "swarm_active", "estop", "activity_kind",
                                     "robot_mode", "nav_state", "swarm_role"])
def test_a_missing_schema_2_key_is_ineligible(device, host, hub, missing):
    data = idle_inputs(host.t)
    del data[missing]
    write_json(device / "run/rosy/status-inputs.json", data)
    host.second_sample_changes = None
    host.write_inputs = lambda: None  # keep the broken file across the sample sleep

    assert updater(host, hub).eligibility()["eligible"] is False


def test_missing_or_oversized_status_inputs_are_ineligible(device, host, hub):
    path = device / "run/rosy/status-inputs.json"
    host.write_inputs = lambda: None
    path.unlink()
    assert updater(host, hub).eligibility()["eligible"] is False

    data = idle_inputs(host.t)
    data["pad"] = "x" * (17 * 1024)
    write_json(path, data)
    assert updater(host, hub).eligibility()["eligible"] is False


def test_two_samples_ten_seconds_apart_must_both_be_idle(device, host, hub):
    host.second_sample_changes = {"velocity_linear": 0.2}
    start = host.t

    report = updater(host, hub).eligibility()

    assert report["eligible"] is False
    assert host.t - start >= dt.timedelta(seconds=10)


def test_eligibility_is_read_only(device, host, hub):
    shutil.rmtree(device / "var/lib/rosy/updates")  # the fixture's config dir
    updater(host, hub).eligibility()
    assert not (device / "var/lib/rosy/updates").exists()
    assert not (device / "run/rosy-claim").exists()


def test_active_hold_holds(device, host, hub):
    up = updater(host, hub)
    up.hold("agent-x", "G5 drive", 1)

    report = up.eligibility()

    assert report["eligible"] is False and report["held"] is True
    hold = json.loads((device / "var/lib/rosy/updates/hold.json").read_text(encoding="utf-8"))
    assert set(hold) == {"holder", "reason", "created_at", "expires_at"}
    assert hold["expires_at"] == _z(T0 + dt.timedelta(hours=1))


def test_expired_hold_is_ignored_and_moved_to_history(device, host, hub, keys):
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    up.hold("agent-x", "G5 drive", 1)
    host.t = T0 + dt.timedelta(hours=1, seconds=1)

    assert up.eligibility()["held"] is False
    result = up.run()

    assert result["phase"] == "committed"
    assert not (device / "var/lib/rosy/updates/hold.json").exists()
    assert any(entry["event"] == "hold_expired" for entry in history(device))


@pytest.mark.parametrize("hours", [0, -1, 168.01, 1000])
def test_hold_with_excessive_or_no_expiry_is_refused(device, host, hub, hours):
    with pytest.raises(upd.UpdateError):
        updater(host, hub).hold("agent-x", "x", hours)
    assert not (device / "var/lib/rosy/updates/hold.json").exists()


@pytest.mark.parametrize("payload", [
    {"holder": "a", "reason": "r", "created_at": _z(T0)},  # no expiry
    {"holder": "a", "reason": "r", "created_at": _z(T0), "expires_at": _z(T0 + dt.timedelta(days=8))},
    "garbage",
])
def test_hand_written_invalid_hold_fails_closed(device, host, hub, payload):
    path = device / "var/lib/rosy/updates/hold.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")

    report = updater(host, hub).eligibility()

    assert report["eligible"] is False and report["held"] is True
    assert "release-hold" in report["reasons"][0]


def test_over_long_hold_never_expires_on_its_own(device, host, hub):
    # Treated as invalid (fail closed), not as a hold that lapses after its 8 days.
    write_json(device / "var/lib/rosy/updates/hold.json",
               {"holder": "a", "reason": "r", "created_at": _z(T0), "expires_at": _z(T0 + dt.timedelta(days=8))})
    host.t = T0 + dt.timedelta(days=9)

    report = updater(host, hub).eligibility()

    assert report["held"] is True and "7 days" in report["reasons"][0]


def test_release_hold_clears_it(device, host, hub):
    up = updater(host, hub)
    up.hold("agent-x", "x", 1)
    up.release_hold()
    assert up.eligibility()["eligible"] is True
    assert [entry["event"] for entry in history(device)] == ["hold_set", "hold_released"]


@pytest.mark.parametrize("marker", ["hardware.approved", "navigation.approved"])
def test_sealed_approval_for_the_current_release_holds(device, host, hub, marker):
    write_json(device / "etc/rosy/approvals" / marker, {"release_id": CURRENT})
    report = updater(host, hub).eligibility()
    assert report["held"] is True and report["eligible"] is False


def test_approval_for_another_release_does_not_hold(device, host, hub):
    write_json(device / "etc/rosy/approvals/hardware.approved", {"release_id": "2026.09.30-001"})
    assert updater(host, hub).eligibility()["eligible"] is True


def test_claim_held_by_another_party_is_ineligible(device, host, hub, keys):
    hub.publish(keys, NEXT)
    claim_mod.acquire(device, "push-pc", "release push", 1800, now=T0)

    up = updater(host, hub)
    assert up.eligibility()["eligible"] is False
    result = up.run()

    assert result["phase"] == "ineligible"
    assert "push-pc" in result["reason"]
    assert "activate" not in kinds(host)


def test_stale_claim_is_taken_over(device, host, hub, keys):
    hub.publish(keys, NEXT)
    claim_mod.acquire(device, "push-pc", "release push", 60, now=T0 - dt.timedelta(minutes=5))

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert not (device / "run/rosy-claim").exists()  # released after the apply


def test_cli_status_and_eligibility_json(device, host, hub, keys, capsys, monkeypatch):
    hub.publish(keys, NEXT)
    monkeypatch.setattr(upd, "Host", lambda root: host)
    monkeypatch.setattr(upd, "API_BASE", hub.base)

    assert upd.main(["--root", str(device), "run"]) == 0
    capsys.readouterr()
    assert upd.main(["--root", str(device), "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["phase"] == "committed"
    assert upd.main(["--root", str(device), "eligibility", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["eligible"] is True
    assert upd.main(["--root", str(device), "hold", "--holder", "a", "--reason", "b", "--hours", "200"]) == 2
    assert upd.main(["--root", str(device), "hold", "--holder", "a", "--reason", "b", "--hours", "2"]) == 0
    assert upd.main(["--root", str(device), "eligibility", "--json"]) == 1
    assert upd.main(["--root", str(device), "release-hold"]) == 0


def test_two_samples_must_be_two_different_writes(device, host, hub):
    # M1: CORE stopped writing, so the second sample is the same file.
    host.write_inputs = lambda: None
    report = updater(host, hub).eligibility()
    assert report["eligible"] is False
    assert any("second sample" in reason for reason in report["reasons"])


def test_samples_older_than_25_seconds_are_stale(device, host, hub):
    # M1: two distinct writes, each 26 s old when read (CORE lagging, not stopped).
    def lagging():
        write_json(device / "run/rosy/status-inputs.json", idle_inputs(host.t - dt.timedelta(seconds=26)))

    host.write_inputs = lagging
    lagging()
    report = updater(host, hub).eligibility()
    assert report["eligible"] is False
    assert any("stale" in reason for reason in report["reasons"])


def test_run_busy_writes_nothing(device, host, hub, keys):
    # M3
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    write_json(device / "var/lib/rosy/updates/status.json", {"phase": "sentinel"})
    write_json(device / "var/lib/rosy/updates/state.json", {"sentinel": True})
    with up._run_lock():
        result = updater(host, hub).run()

    assert "RUN_BUSY" in result["reason"]
    assert status(device) == {"phase": "sentinel"}
    assert state(device) == {"sentinel": True}
    assert hub.requests == []


@pytest.mark.parametrize("content", [b"{not json", b"[1, 2]", b"x" * (70 * 1024), b'{"release_id": 5}'],
                         ids=["corrupt", "not-object", "oversize", "bad-id"])
def test_an_unreadable_approval_marker_holds(device, host, hub, content):
    # M6
    path = device / "etc/rosy/approvals/hardware.approved"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    report = updater(host, hub).eligibility()
    assert report["held"] is True and report["eligible"] is False


def test_a_symlinked_approval_marker_holds(device, host, hub, tmp_path):
    # M6
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"release_id": "2026.09.30-001"}), encoding="utf-8")
    link = device / "etc/rosy/approvals/navigation.approved"
    link.parent.mkdir(parents=True)
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("this host cannot create symlinks")
    assert updater(host, hub).eligibility()["held"] is True


@pytest.mark.parametrize("changes,eligible", [
    ({"docking_state": "UNDOCKED"}, True),
    ({"docking_state": "DOCKED"}, True),
    ({"docking_state": "CHARGING"}, True),
    ({"docking_state": "DOCK_FAILED"}, False),
    ({"docking_state": "SOMETHING_NEW"}, False),
    ({"line_follow_state": "TRACKING"}, False),
    ({"line_follow_state": "WAITING"}, False),
    ({"velocity_linear": 10 ** 400}, False),
    ({"battery_percent": 10 ** 400}, False),
], ids=lambda value: str(value)[:40])
def test_docking_allowlist_line_follow_state_and_overflow(device, host, hub, changes, eligible):
    # L2, L3
    host.inputs_changes = changes
    host.write_inputs()
    assert updater(host, hub).eligibility()["eligible"] is eligible


def test_the_activator_gets_the_updater_precheck(device, host, hub, keys):
    # N1
    hub.publish(keys, NEXT)
    updater(host, hub).run()
    activate = next(argv for argv in host.calls if kind_of(argv) == "activate")
    assert activate[0] == "env"
    precheck = next(item for item in activate if item.startswith("ROSY_ACTIVATE_PRECHECK="))
    assert "rosy_auto_update.py" in precheck and precheck.endswith(" precheck")


def test_a_refused_precheck_is_ineligible_not_a_failure(device, host, hub, keys):
    # N1
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "NATIVE_PRECHECK_REFUSED: robot mode is MANUAL"}), "")

    result = updater(host, hub).run()

    assert result["phase"] == "ineligible"
    assert NEXT not in state(device).get("failed", {})
    assert not state(device).get("apply_errors")


@pytest.mark.parametrize("setup,code", [
    (lambda device, host, up: None, 0),
    (lambda device, host, up: up.hold("agent", "G5", 1), 3),
    (lambda device, host, up: write_json(device / "etc/rosy/approvals/hardware.approved",
                                         {"release_id": CURRENT}), 3),
    (lambda device, host, up: (setattr(host, "inputs_changes", {"velocity_linear": 0.3}),
                               host.write_inputs()), 3),
    (lambda device, host, up: _stale_inputs(device, host), 3),
], ids=["idle", "hold", "sealed", "moving", "stale"])
def test_cli_precheck(device, host, hub, setup, code, monkeypatch, capsys):
    # N1: what the activator runs; one sample, our own claim allowed.
    up = updater(host, hub)
    setup(device, host, up)
    claim_mod.acquire(device, upd.CLAIM_HOLDER, "auto-update", 600, now=host.t)
    monkeypatch.setattr(upd, "Host", lambda root: host)
    assert upd.main(["--root", str(device), "precheck"]) == code


def test_a_claim_release_error_does_not_crash_the_run(device, host, hub, keys, monkeypatch):
    # N13
    hub.publish(keys, NEXT)

    def broken(root, holder):
        raise OSError("read-only /run")

    monkeypatch.setattr(claim_mod, "release", broken)

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert any(entry["event"] == "claim_release_failed" for entry in history(device))


@pytest.mark.parametrize("error", [
    "NATIVE_PRECHECK_FAILED: exit 1: Traceback (most recent call last)",
    "NATIVE_PRECHECK_FAILED: precheck could not run: timed out after 60 seconds",
], ids=["crashed", "timeout"])
def test_a_precheck_that_failed_is_an_apply_error_not_busy(device, host, hub, keys, error):
    # M2
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": error}), "")

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert "precheck" in result["reason"].lower()
    assert state(device)["apply_errors"][NEXT]["attempts"] == 1
    assert NEXT not in state(device).get("failed", {})


def test_the_precheck_busy_exit_matches_native_release():
    # LOW: the activator's "busy" code and the updater's precheck exit are one value.
    from deploy.robot.pinky_pro.native import native_release

    assert native_release.PRECHECK_BUSY_EXIT == upd.PRECHECK_BUSY_EXIT == 3


def test_release_hold_waits_for_no_run(device, host, hub, keys, capsys, monkeypatch):
    # MEDIUM: release-hold rewrites state.json, so it takes the run lock; busy is an error.
    up = updater(host, hub)
    up.hold("agent", "x", 1)
    write_json(device / "var/lib/rosy/updates/state.json", {"apply_errors": {NEXT: {"attempts": 3}}})
    with up._run_lock():
        with pytest.raises(upd.RunBusy):
            updater(host, hub).release_hold()
        monkeypatch.setattr(upd, "Host", lambda root: host)
        code = upd.main(["--root", str(device), "release-hold"])
    out = json.loads(capsys.readouterr().out)

    assert code == 4
    assert out["ok"] is False and "RUN_BUSY" in out["error"]
    assert (device / "var/lib/rosy/updates/hold.json").exists()
    assert state(device)["apply_errors"] == {NEXT: {"attempts": 3}}
