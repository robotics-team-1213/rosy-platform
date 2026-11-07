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
    def __init__(self, fail=None, active=("rosy-io.service",)):
        self.calls, self.fail, self.units = [], fail, set(active)
        self.preflight = OK
        self.spawned = []

    def run(self, *argv, timeout=120):
        self.calls.append(argv)
        failed = self.fail is not None and self.fail in " ".join(map(str, argv))
        return subprocess.CompletedProcess(argv, 1 if failed else 0, "", "boom" if failed else "")

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
    ops = Ops()
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
    ops = Ops(fail=COMMIT)
    host.begin(root, ops)
    state = host.status(root, ops)
    assert state["phase"] == "FAILED" and "commit failed" in state["reason"]
    assert (root / host.RUNTIME).read_bytes() == before
    assert ops.ran("release-hold") and ops.ran("restart", "rosy-core.service")


def test_a_failed_restart_restores_the_runtime_begin_found(root):
    before = (root / host.RUNTIME).read_bytes()
    ops = Ops()
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
    ops = Ops(fail="acquire")
    host.begin(root, ops)
    assert host.status(root, ops)["phase"] == "FAILED"
    assert (root / host.RUNTIME).read_bytes() == before
    assert not ops.ran("stop", "rosy-io.service") and not ops.ran("restart", "rosy-core.service")


def test_motors_that_do_not_answer_never_reach_motor_mode(root):
    before = (root / host.RUNTIME).read_bytes()
    ops = Ops()
    ops.preflight = {"configured_ids": [1, 2], "responded_ids": [1], "torque_free": False}
    host.begin(root, ops)
    assert host.status(root, ops)["phase"] == "FAILED"
    assert (root / host.RUNTIME).read_bytes() == before
    assert not (root / host.EVIDENCE / host.PREFLIGHT).exists()


def test_a_failed_restore_says_so(root):
    ops = Ops(fail="restart rosy-core")
    host.begin(root, ops)
    assert "restore failed" in host.status(root, ops)["reason"]


def test_a_persons_own_update_hold_stays_theirs(root):
    hold = root / host.HOLD
    hold.parent.mkdir(parents=True)
    hold.write_text("{}", encoding="ascii")
    ops = Ops()
    host.begin(root, ops)
    host.cancel(root, ops)
    assert not ops.ran("hold") and not [c for c in ops.calls if "release-hold" in c]


def test_cancel_returns_to_the_previous_runtime_and_units(root):
    before = (root / host.RUNTIME).read_bytes()
    ops = Ops()
    host.begin(root, ops)
    ops.calls.clear()
    host.cancel(root, ops)
    assert (root / host.RUNTIME).read_bytes() == before
    assert ops.ran("start", "rosy-io.service") and ops.ran("release-hold")
    assert host.status(root, ops)["phase"] == "IDLE"


def _copy_trials(root, tmp_path):
    bundle, evidence = _candidate(tmp_path)
    trials = root / host.TRIALS
    trials.mkdir(parents=True, exist_ok=True)
    for trial in bundle["trials"]:
        if (trial["direction"], trial["stop_cause"]) in host.REQUIRED:
            name = f"{trial['direction']}-{trial['stop_cause']}.json"
            (trials / name).write_bytes((evidence / trial["evidence_file"]).read_bytes())


def test_seal_writes_the_approver_and_returns_to_hardware_without_starting_navigation(root, tmp_path):
    ops = Ops()
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
    ops = Ops()
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
    ops = Ops()
    host.begin(root, ops)
    _copy_trials(root, tmp_path)
    (root / host.TRIALS / "cw-button_release.json").write_text("{}", encoding="ascii")
    host.seal(root, ops, "person-a", "floor")
    assert host.status(root, ops)["phase"] == "MEASURING"
    assert not (root / "etc/rosy/approvals/navigation.approved").exists()


def test_a_failed_return_to_hardware_restores_the_previous_runtime(root, tmp_path):
    before = (root / host.RUNTIME).read_bytes()
    ops = Ops()
    host.begin(root, ops)
    _copy_trials(root, tmp_path)
    ops.fail = "stop rosy-navigation"
    host.seal(root, ops, "person-a", "floor")
    assert host.status(root, ops)["phase"] == "FAILED"
    assert (root / host.RUNTIME).read_bytes() == before


def test_navigation_does_not_start_without_a_valid_seal(root):
    ops = Ops()
    with pytest.raises(ValueError):
        host.start_navigation(root, ops)
    assert not ops.ran("rosy-navigation.service")


def test_a_transition_that_died_reads_as_failed_and_a_live_one_refuses_another(root):
    ops = Ops()
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


def test_no_seal_reads_as_needing_measurement(root):
    state = host.status(root, Ops())
    assert state["approval"]["valid"] is False and state["needs_measurement"] is True
