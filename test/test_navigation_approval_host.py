"""D-986: the privileged transitions of navigation re-approval on a device tree, with no real system calls."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_native_mapping_approval import _candidate, _device

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"))
import navigation_approval_host as host  # noqa: E402

OK = {"configured_ids": [1, 2], "responded_ids": [1, 2], "torque_free": True}
COMMIT = "<the commit step>"  # never part of a command line, unlike a word from the tmp path


class Ops:
    def __init__(self, root, fail=None, active=("rosy-io.service",)):
        self.root, self.calls, self.fail, self.units = root, [], fail, set(active)
        self.clock, self.boot = 0.0, "boot-a"
        self.preflight = OK
        self.spawned = []

    def run(self, *argv, timeout=120):
        self.calls.append(argv)
        failed = self.fail is not None and self.fail in " ".join(map(str, argv))
        if not failed and "hold" in argv:
            path = host._hold_path(self.root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"holder": host.HOLDER}), encoding="ascii")
        return subprocess.CompletedProcess(argv, 1 if failed else 0, "", "boom" if failed else "")

    def now(self):
        return self.clock

    def boot_id(self):
        return self.boot

    def spawn(self, action, *arguments):
        self.spawned.append((action, *arguments))
        return subprocess.CompletedProcess([], 0, "", "")

    def active(self, unit):
        return unit in self.units

    def commit(self, root, new, old):
        if self.fail == COMMIT:
            self.fail = None
            raise ValueError("commit failed")
        assert (root / host.RUNTIME).read_bytes() == old
        (root / host.RUNTIME).write_bytes(new)

    def probe_motors(self):
        return self.preflight

    def ran(self, *words):
        return [c for c in self.calls if all(w in c for w in words)]


@pytest.fixture
def root(tmp_path):
    return _device(tmp_path, mode="hardware")


def test_begin_measures_the_motors_with_torque_free_and_moves_to_motor(root):
    ops = Ops(root)
    host.begin(root, ops)
    state = host.status(root, ops)
    assert state["phase"] == "MEASURING" and state["runtime_mode"] == "motor"
    assert b"ROSY_NAVIGATION_BACKEND=localization" in (root / host.RUNTIME).read_bytes()  # CORE refuses motor+slam
    assert json.loads((root / host.EVIDENCE / host.PREFLIGHT).read_text(encoding="ascii")) == OK
    stop, restart = ops.ran("stop", "rosy-io.service")[0], ops.ran("restart", "rosy-core.service")[0]
    assert ops.calls.index(stop) < ops.calls.index(restart)
    assert ops.ran("hold") and ops.ran("acquire") and ops.ran("release")


def test_a_failed_commit_restores_the_runtime_begin_found(root):
    before = (root / host.RUNTIME).read_bytes()
    ops = Ops(root, fail=COMMIT)
    host.begin(root, ops)
    state = host.status(root, ops)
    assert state["phase"] == "FAILED" and "commit failed" in state["reason"]
    assert (root / host.RUNTIME).read_bytes() == before
    assert not host._hold_path(root).exists() and ops.ran("restart", "rosy-core.service")


def test_a_failed_restart_restores_the_runtime_begin_found(root):
    before = (root / host.RUNTIME).read_bytes()
    ops = Ops(root)
    real = ops.run

    def first_restart_fails(*argv, timeout=120):
        ops.fail = "restart rosy-core" if not ops.ran("restart") else None
        return real(*argv, timeout=timeout)
    ops.run = first_restart_fails
    host.begin(root, ops)
    state = host.status(root, ops)
    assert state["phase"] == "FAILED" and "restore failed" not in state["reason"]
    assert (root / host.RUNTIME).read_bytes() == before
    assert ops.ran("start", "rosy-io.service")


def test_a_claim_held_by_another_job_changes_nothing(root):
    before = (root / host.RUNTIME).read_bytes()
    ops = Ops(root, fail="acquire")
    host.begin(root, ops)
    assert host.status(root, ops)["phase"] == "FAILED"
    assert (root / host.RUNTIME).read_bytes() == before
    assert not ops.ran("stop", "rosy-io.service") and not ops.ran("restart", "rosy-core.service")


def test_motors_that_do_not_answer_never_reach_motor_mode(root):
    before = (root / host.RUNTIME).read_bytes()
    ops = Ops(root)
    ops.preflight = {"configured_ids": [1, 2], "responded_ids": [1], "torque_free": False}
    host.begin(root, ops)
    assert host.status(root, ops)["phase"] == "FAILED"
    assert (root / host.RUNTIME).read_bytes() == before
    assert not (root / host.EVIDENCE / host.PREFLIGHT).exists()


def test_a_failed_restore_says_so(root):
    ops = Ops(root, fail="restart rosy-core")
    host.begin(root, ops)
    assert "restore failed" in host.status(root, ops)["reason"]


def _person_hold(root):
    path = host._hold_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"holder": "person"}), encoding="ascii")
    return path


def test_a_persons_update_hold_refuses_begin_and_stays(root):
    path = _person_hold(root)
    before = (root / host.RUNTIME).read_bytes()
    ops = Ops(root)
    host.begin(root, ops)
    state = host.status(root, ops)
    assert state["phase"] == "FAILED" and "person" in state["reason"]
    assert path.exists() and (root / host.RUNTIME).read_bytes() == before and not ops.ran("stop", "rosy-io.service")


def test_a_hold_that_appeared_later_is_never_deleted(root):
    ops = Ops(root)
    host.begin(root, ops)
    path = _person_hold(root)
    host.cancel(root, ops)
    assert path.exists()


def test_the_hold_is_found_where_the_updater_looks(root, monkeypatch, tmp_path):
    import os_state_layout
    elsewhere = tmp_path / "shared/hold.json"
    monkeypatch.setattr(os_state_layout, "policy_file", lambda _root, _name: elsewhere)
    elsewhere.parent.mkdir()
    elsewhere.write_text(json.dumps({"holder": "person"}), encoding="ascii")
    ops = Ops(root)
    host.begin(root, ops)
    assert host.status(root, ops)["phase"] == "FAILED" and elsewhere.exists()


def test_a_second_begin_after_a_failed_restore_keeps_the_original_runtime(root):
    original = (root / host.RUNTIME).read_bytes()
    ops = Ops(root)
    host.begin(root, ops)
    state = json.loads((root / host.STATE).read_text(encoding="utf-8"))
    (root / host.STATE).write_text(json.dumps({**state, "phase": "FAILED"}), encoding="utf-8")
    assert b"ROSY_RUNTIME_MODE=motor" in (root / host.RUNTIME).read_bytes()
    host.begin(root, ops)
    host.cancel(root, ops)
    assert (root / host.RUNTIME).read_bytes() == original
    assert host.status(root, ops)["phase"] == "IDLE"


def _state(root):
    return json.loads((root / host.STATE).read_text(encoding="utf-8"))


def _after_failed_restore(root, ops):
    host.begin(root, ops)
    ops.fail = "restart rosy-core"
    host.cancel(root, ops)
    ops.fail = None
    return _state(root)["deadline"]


def test_a_second_begin_keeps_the_retry_deadline(root):
    ops = Ops(root)
    deadline = _after_failed_restore(root, ops)
    assert deadline == host.RETRY_S
    ops.clock = 5.0
    host.begin(root, ops)
    assert _state(root)["phase"] == "MEASURING" and _state(root)["deadline"] == deadline


@pytest.mark.parametrize("step", ["restart rosy-core", "acquire"])
def test_a_second_begin_that_fails_changes_no_retry_timing(root, step):
    ops = Ops(root)
    deadline = _after_failed_restore(root, ops)
    runtime = _state(root)["previous_runtime"]
    ops.clock, ops.fail = 5.0, step
    host.begin(root, ops)
    state = _state(root)
    assert state["deadline"] == deadline and state["previous_runtime"] == runtime and state["phase"] == "FAILED"
    ops.clock, ops.fail = deadline, None
    assert host.expire_if_due(root, ops) is True


def test_a_second_begin_refused_at_the_hold_step_still_brings_the_robot_back(root):
    original = (root / host.RUNTIME).read_bytes()
    ops = Ops(root)
    _after_failed_restore(root, ops)
    ops.fail = "hold --holder"
    host.begin(root, ops)
    assert host.status(root, ops)["phase"] == "FAILED" and (root / host.RUNTIME).read_bytes() == original
    assert host.expire_if_due(root, ops) is False


def test_a_failed_restore_keeps_the_hold_and_only_a_good_one_releases_it(root):
    ops = Ops(root)
    host.begin(root, ops)
    ops.fail = "restart rosy-core"
    host.cancel(root, ops)
    assert host._hold_path(root).exists() and host.status(root, ops)["phase"] == "FAILED"
    ops.fail = None
    host.cancel(root, ops)
    assert not host._hold_path(root).exists() and host.status(root, ops)["phase"] == "IDLE"


def test_measuring_expires_before_the_hold_and_status_shows_it(root):
    assert host.MEASURE_S < float(host.HOLD_HOURS) * 3600
    ops = Ops(root)
    host.begin(root, ops)
    assert host.status(root, ops)["measuring_expires_in_s"] == host.MEASURE_S
    assert host.expire_if_due(root, ops) is False and not ops.spawned
    ops.clock = host.MEASURE_S
    assert host.expire_if_due(root, ops) is True
    assert ops.spawned == [("cancel", "measuring expired")]
    host.cancel(root, ops, "measuring expired")
    state = host.status(root, ops)
    assert state["phase"] == "IDLE" and state["reason"] == "measuring expired" and state["runtime_mode"] == "hardware"


def test_a_reboot_ends_measuring(root):
    ops = Ops(root)
    host.begin(root, ops)
    ops.boot, ops.clock = "boot-b", 1.0
    assert host.status(root, ops)["measuring_expires_in_s"] is None
    assert host.expire_if_due(root, ops) is True


def test_nothing_to_expire_when_idle_or_already_back(root):
    ops = Ops(root)
    ops.clock = 1e9
    assert host.expire_if_due(root, ops) is False
    ops.fail = "acquire"
    host.begin(root, ops)
    assert host.expire_if_due(root, ops) is False and not ops.spawned


def test_trials_from_before_a_release_change_are_discarded_at_the_seal(root, tmp_path):
    ops = Ops(root)
    host.begin(root, ops)
    _copy_trials(root, tmp_path)
    (root / "opt/rosy/current/install/.rosy-release").write_text("2026.11.07-900", encoding="ascii")
    with pytest.raises(ValueError, match="release changed"):
        host.request_seal(root, ops, "person-a", "floor")
    assert not ops.spawned and not list((root / host.TRIALS).glob("*.json"))
    assert all(row["state"] == "missing" for row in host.status(root, ops)["trials"])
    assert host.status(root, ops)["phase"] == "MEASURING"
    assert not (root / "etc/rosy/approvals/navigation.approved").exists()


def test_the_seal_itself_refuses_a_changed_motion_fingerprint(root, tmp_path):
    ops = Ops(root)
    host.begin(root, ops)
    _copy_trials(root, tmp_path)
    (root / "etc/rosy/os-factory-release.json").write_text('{"release_id": "new"}', encoding="ascii")
    host.seal(root, ops, "person-a", "floor")
    assert "release changed" in host.status(root, ops)["reason"]
    assert not (root / "etc/rosy/approvals/navigation.approved").exists()


def test_cancel_returns_to_the_previous_runtime_and_units(root):
    before = (root / host.RUNTIME).read_bytes()
    ops = Ops(root)
    host.begin(root, ops)
    ops.calls.clear()
    host.cancel(root, ops)
    assert (root / host.RUNTIME).read_bytes() == before
    assert ops.ran("start", "rosy-io.service") and not host._hold_path(root).exists()
    assert host.status(root, ops)["phase"] == "IDLE"


def _copy_trials(root, tmp_path, surface="floor", scan_check=True):
    bundle, evidence = _candidate(tmp_path)
    trials = root / host.TRIALS
    trials.mkdir(parents=True, exist_ok=True)
    for trial in bundle["trials"]:
        if (trial["direction"], trial["stop_cause"]) in host.REQUIRED:
            name = f"{trial['direction']}-{trial['stop_cause']}"
            content = (evidence / trial["evidence_file"]).read_bytes()
            (trials / f"{name}.json").write_bytes(content)
            (trials / f"{name}.surface.json").write_text(json.dumps({
                "test_surface": surface, "raw_sha256": host.mapping_approval._sha256(content),
                "scan_check": {"odom": 0.03, "scan": 0.03} if scan_check else None}), encoding="ascii")


def _measuring_with_trials(root, tmp_path, **kw):
    ops = Ops(root)
    host.begin(root, ops)
    _copy_trials(root, tmp_path, **kw)
    return ops


def test_a_seal_on_another_surface_than_the_trials_is_refused(root, tmp_path):
    ops = _measuring_with_trials(root, tmp_path, surface="lifted", scan_check=False)
    assert all(row["state"] == "valid" and row["test_surface"] == "lifted" for row in host.status(root, ops)["trials"])
    with pytest.raises(ValueError, match="floor surface"):
        host.request_seal(root, ops, "person-a", "floor")
    host.seal(root, ops, "person-a", "floor")
    assert not (root / "etc/rosy/approvals/navigation.approved").exists()
    host.seal(root, ops, "person-a", "lifted")
    bundle = json.loads((root / "etc/rosy/approvals/g4.bundle.json").read_text(encoding="utf-8"))
    assert bundle["test_surface"] == "lifted"


def test_mixed_surfaces_cannot_be_sealed_as_either(root, tmp_path):
    ops = _measuring_with_trials(root, tmp_path)
    side = root / host.TRIALS / "cw-button_release.surface.json"
    side.write_text(json.dumps({**json.loads(side.read_text(encoding="ascii")), "test_surface": "lifted"}), encoding="ascii")
    for surface in ("floor", "lifted"):
        with pytest.raises(ValueError, match="surface"):
            host.request_seal(root, ops, "person-a", surface)


@pytest.mark.parametrize("damage", ["missing", "other_raw", "no_scan_check"])
def test_a_floor_trial_without_its_cross_check_is_not_valid(root, tmp_path, damage):
    ops = _measuring_with_trials(root, tmp_path)
    side = root / host.TRIALS / "cw-button_release.surface.json"
    record = json.loads(side.read_text(encoding="ascii"))
    if damage == "missing":
        side.unlink()
    elif damage == "other_raw":
        side.write_text(json.dumps({**record, "raw_sha256": "0" * 64}), encoding="ascii")
    else:
        side.write_text(json.dumps({**record, "scan_check": None}), encoding="ascii")
    rows = {row["direction"] + row["stop_cause"]: row for row in host.status(root, ops)["trials"]}
    assert rows["cwbutton_release"]["state"] == "invalid"
    with pytest.raises(ValueError, match="every required trial"):
        host.request_seal(root, ops, "person-a", "floor")


def test_seal_writes_the_approver_and_returns_to_hardware_without_starting_navigation(root, tmp_path):
    ops = Ops(root)
    host.begin(root, ops)
    _copy_trials(root, tmp_path)
    assert all(row["state"] == "valid" for row in host.status(root, ops)["trials"])
    host.request_seal(root, ops, "person-a", "floor")
    assert ops.spawned == [("seal", "person-a", "floor")]
    host.seal(root, ops, "person-a", "floor")
    state = host.status(root, ops)
    assert state["phase"] == "IDLE" and state["runtime_mode"] == "hardware"
    assert state["approval"]["valid"] is True and state["needs_measurement"] is False
    assert b"ROSY_NAVIGATION_BACKEND=slam" in (root / host.RUNTIME).read_bytes()
    marker = json.loads((root / "etc/rosy/approvals/navigation.approved").read_text(encoding="utf-8"))
    assert marker["operator"] == "person-a"
    assert not ops.ran("--no-block")
    host.start_navigation(root, ops)
    assert ops.ran("start", "--no-block", "rosy-navigation.service")


def test_seal_refuses_until_every_trial_is_valid(root, tmp_path):
    ops = Ops(root)
    host.begin(root, ops)
    with pytest.raises(ValueError, match="every required trial"):
        host.request_seal(root, ops, "person-a", "floor")
    _copy_trials(root, tmp_path)
    path = root / host.TRIALS / "cw-button_release.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["requested_angular_rps"] = -0.5
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert [r["state"] for r in host.status(root, ops)["trials"]].count("invalid") == 1
    with pytest.raises(ValueError, match="every required trial"):
        host.request_seal(root, ops, "person-a", "floor")
    assert not ops.spawned


def test_evidence_that_fails_at_the_seal_stays_measuring_with_no_marker(root, tmp_path):
    ops = Ops(root)
    host.begin(root, ops)
    _copy_trials(root, tmp_path)
    (root / host.TRIALS / "cw-button_release.json").write_text("{}", encoding="ascii")
    host.seal(root, ops, "person-a", "floor")
    assert host.status(root, ops)["phase"] == "MEASURING"
    assert not (root / "etc/rosy/approvals/navigation.approved").exists()


def test_a_failed_return_to_hardware_restores_the_previous_runtime(root, tmp_path):
    before = (root / host.RUNTIME).read_bytes()
    ops = Ops(root)
    host.begin(root, ops)
    _copy_trials(root, tmp_path)
    ops.fail = "stop rosy-navigation"
    host.seal(root, ops, "person-a", "floor")
    assert host.status(root, ops)["phase"] == "FAILED"
    assert (root / host.RUNTIME).read_bytes() == before


def test_navigation_does_not_start_without_a_valid_seal(root):
    ops = Ops(root)
    with pytest.raises(ValueError):
        host.start_navigation(root, ops)
    assert not ops.ran("rosy-navigation.service")


def test_a_transition_that_died_reads_as_failed_and_a_live_one_refuses_another(root):
    ops = Ops(root)
    host.request_begin(root, ops)
    assert ops.spawned == [("begin",)]
    assert host.status(root, ops)["phase"] == "BEGINNING"  # systemd has not reported the unit yet
    state = json.loads((root / host.STATE).read_text(encoding="utf-8"))
    (root / host.STATE).write_text(json.dumps({**state, "requested_at": 0}), encoding="utf-8")
    assert host.status(root, ops)["phase"] == "FAILED"
    ops.units.add(f"{host.UNIT}.service")
    assert host.status(root, ops)["phase"] == "BEGINNING"
    with pytest.raises(ValueError, match="cannot begin"):
        host.request_begin(root, ops)


@pytest.mark.parametrize("unit,expected", [
    ("[Unit]\nWants=network-online.target rosy-io.service\n", True),
    ("[Unit]\nWants=network-online.target\n# Wants=rosy-io.service\nAfter=rosy-io.service\n", False),
    (None, False),
])
def test_status_reports_an_os_update_unit_that_stops_navigation(root, unit, expected):
    path = root / host.OS_UPDATE_UNIT
    if unit is not None:
        path.parent.mkdir(parents=True)
        path.write_text(unit, encoding="ascii")
    ops = Ops(root)
    assert host.status(root, ops)["os_update_stops_navigation"] is expected
    assert not ops.calls  # read only: the timer is never touched


def test_starting_navigation_reports_the_os_update_unit(root, tmp_path):
    ops = _measuring_with_trials(root, tmp_path)
    host.seal(root, ops, "person-a", "floor")
    path = root / host.OS_UPDATE_UNIT
    path.parent.mkdir(parents=True)
    path.write_text("[Unit]\nWants=rosy-io.service\n", encoding="ascii")
    ops.calls.clear()
    assert host.start_navigation(root, ops)["os_update_stops_navigation"] is True
    assert not ops.ran("stop", "rosy-os-update.timer")


def test_no_seal_reads_as_needing_measurement(root):
    state = host.status(root, Ops(root))
    assert state["approval"]["valid"] is False and state["needs_measurement"] is True


def test_commit_checks_the_projection_with_the_image_installed_dispatcher(monkeypatch, tmp_path):
    # The release copy of os_storage_dispatch.py cannot find os-bootstrap and answers HOLD (geg6 11-09).
    import types
    for name, attr in (("os_state_config", "commit_runtime"), ("os_state_ready", "publish_ready")):
        monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(**{attr: lambda *a, **k: None}))
    calls = []
    ops = host.SystemOps()
    ops.run = lambda *argv, **k: (calls.append(argv), types.SimpleNamespace(
        returncode=0, stdout='{"phase": "PROJECTED"}'))[1]

    ops.commit(tmp_path, b"new", b"old")

    assert calls == [(sys.executable, "-B", "/opt/rosy/native-runtime/os_storage_dispatch.py", "--projected")]
    assert host.HERE not in host.DISPATCH.parents
