"""D-986 addendum 2026-11-20: the robot re-measures its navigation approval after a release change."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"
sys.path.insert(0, str(NATIVE))
import navigation_reapprove as nr  # noqa: E402

APPROVAL = {"phase": "IDLE", "approval": {"valid": False}, "needs_measurement": True}
ROBOT = {"mode": "IDLE", "velocity": {"linear": 0.0, "angular": 0.0}, "battery_status": {"charging": False}}
HEALTH = {"battery": {"evidence": "fresh", "level": "ok"}}


def test_decide_runs_only_when_every_gate_holds():
    assert nr.decide(APPROVAL, ROBOT, ROBOT, HEALTH, 0) == "run"
    assert nr.decide({**APPROVAL, "phase": "MEASURING"}, ROBOT, ROBOT, HEALTH, 0).startswith("approval phase")
    assert nr.decide({**APPROVAL, "approval": {"valid": True}}, ROBOT, ROBOT, HEALTH, 0) == "approved"
    assert nr.decide(APPROVAL, ROBOT, {**ROBOT, "mode": "NAVIGATION"}, HEALTH, 0).startswith("robot mode")
    moving = {**ROBOT, "velocity": {"linear": 0.02, "angular": 0.0}}
    assert nr.decide(APPROVAL, moving, ROBOT, HEALTH, 0) == "robot moving"
    assert nr.decide(APPROVAL, {**ROBOT, "velocity": {}}, ROBOT, HEALTH, 0) == "robot moving"
    assert nr.decide(APPROVAL, ROBOT, ROBOT, {"battery": {"evidence": "stale", "level": "ok"}}, 0).startswith("battery")
    assert nr.decide(APPROVAL, ROBOT, ROBOT, {"battery": {"evidence": "fresh", "level": "low"}}, 0).startswith("battery")
    for charging in (True, None):
        assert nr.decide(APPROVAL, ROBOT, {**ROBOT, "battery_status": {"charging": charging}}, HEALTH, 0) \
            == "charging not confirmed false"
    assert nr.decide(APPROVAL, ROBOT, ROBOT, HEALTH, nr.MAX_ATTEMPTS).startswith("gave up")


def test_reverse_is_the_last_trial_and_all_five_d986_trials_run():
    assert nr.TRIALS[-1][:2] == ("reverse", "button_release")
    assert {t[:2] for t in nr.TRIALS} == {("forward", "button_release"), ("reverse", "button_release"),
                                          ("cw", "button_release"), ("ccw", "button_release"),
                                          ("forward", "command_loss")}


def test_only_a_release_change_counts_as_needing_a_new_measurement(monkeypatch, tmp_path):
    def failing(message):
        def check(root):
            raise ValueError(message)
        return check

    monkeypatch.setattr(nr.mapping_approval, "check", failing("hardware approval release_id differs from the active release"))
    assert nr.approval_needs_remeasure(tmp_path) is None
    # The first approval of a robot stays with a person.
    monkeypatch.setattr(nr.mapping_approval, "check", failing("hardware approval is missing or empty"))
    assert nr.approval_needs_remeasure(tmp_path).startswith("approval:")
    monkeypatch.setattr(nr.mapping_approval, "check", failing("G4 approval bundle is missing"))
    assert nr.approval_needs_remeasure(tmp_path).startswith("approval:")
    monkeypatch.setattr(nr.mapping_approval, "check", lambda root: {"ready": True})
    assert nr.approval_needs_remeasure(tmp_path) == "approved"


class FakeCore:
    def __init__(self, robot=ROBOT):
        self.token, self.calls, self.robot = None, [], robot

    def get(self, path):
        self.calls.append(("GET", path))
        return {"/api/v1/navigation/approval": APPROVAL, "/api/v1/robot/state": self.robot,
                "/api/v1/power/health": HEALTH}[path]

    def post(self, path, body=None, ok=()):
        self.calls.append(("POST", path))


@pytest.fixture
def robot_root(tmp_path, monkeypatch):
    (tmp_path / "opt/rosy/releases/2026.11.20-200").mkdir(parents=True)
    (tmp_path / "opt/rosy/current").symlink_to(tmp_path / "opt/rosy/releases/2026.11.20-200")
    monkeypatch.setattr(nr, "approval_needs_remeasure", lambda root: None)
    monkeypatch.setattr(nr.rosy_claim, "check", lambda root: None)
    return tmp_path


def _run(root, core, reapprove):
    return nr.run(root, core, sleep=lambda s: None, reapprove_fn=reapprove, pair_fn=lambda c: "token")


def test_a_successful_run_counts_the_attempt_and_logs_out(robot_root):
    core, seen = FakeCore(), []
    assert _run(robot_root, core, lambda c, log: seen.append(c.token)) == "approved and navigation started"
    assert seen == ["token"]
    assert core.calls[-1] == ("POST", "/api/v1/auth/logout")
    state = json.loads((robot_root / "var/lib/rosy/nav-reapprove/state.json").read_text())
    assert state == {"2026.11.20-200": 1}


def test_a_failed_run_cancels_and_stops_after_max_attempts(robot_root):
    def boom(core, log):
        raise RuntimeError("CLEARANCE_TOO_SMALL")

    for _ in range(nr.MAX_ATTEMPTS):
        core = FakeCore()
        assert _run(robot_root, core, boom).startswith("failed: CLEARANCE_TOO_SMALL")
        assert ("POST", "/api/v1/navigation/approval/cancel") in core.calls
        assert core.calls[-1] == ("POST", "/api/v1/auth/logout")
    core = FakeCore()
    assert _run(robot_root, core, boom).startswith("gave up")
    assert ("POST", "/api/v1/navigation/approval/cancel") not in core.calls


def test_nothing_moves_while_claimed_disabled_or_busy(robot_root, monkeypatch):
    never = lambda core, log: pytest.fail("must not re-measure")  # noqa: E731
    core = FakeCore(robot={**ROBOT, "mode": "NAVIGATION"})
    assert _run(robot_root, core, never) == "robot mode NAVIGATION"
    assert core.calls[-1] == ("POST", "/api/v1/auth/logout")
    monkeypatch.setattr(nr.rosy_claim, "check", lambda root: {"holder": "rosy-auto-update"})
    assert _run(robot_root, FakeCore(), never) == "claimed"
    (robot_root / "etc/rosy").mkdir(parents=True)
    (robot_root / "etc/rosy/nav-reapprove.disabled").touch()
    assert _run(robot_root, FakeCore(), never) == "disabled"


def test_pair_uses_a_short_operator_code_and_refuses_without_one():
    class Core:
        def post(self, path, body=None, ok=()):
            assert path == "/api/v1/auth/pair" and body == {"code": "AB2C-D3EF", "label": "nav-reapprove"}
            return {"token": "t"}

    def runner(argv, **kwargs):
        assert argv[-4:] == ["--role", "operator", "--minutes", "5"]
        return subprocess.CompletedProcess(argv, 0, "Login code AB2C-D3EF  (operator, valid 5 min, one use)\n", "")

    assert nr.pair(Core(), runner) == "t"
    with pytest.raises(RuntimeError):
        nr.pair(Core(), lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "no"))


def test_units_ship_enabled_and_the_run_never_fails_the_unit():
    service = (NATIVE / "rosy-nav-reapprove.service").read_text(encoding="utf-8")
    assert "navigation_reapprove.py run" in service and "Type=oneshot" in service
    assert "WantedBy=timers.target" in (NATIVE / "rosy-nav-reapprove.timer").read_text(encoding="utf-8")
    import image_layer_plan
    assert {"rosy-nav-reapprove.service", "rosy-nav-reapprove.timer"} <= set(image_layer_plan.UNITS)
    assert "rosy-nav-reapprove.timer" in image_layer_plan.ENABLED_UNITS
    rootfs = (NATIVE.parent / "image/customize-rootfs.sh").read_text(encoding="utf-8")
    assert "rosy-nav-reapprove.timer" in rootfs
    payload = (NATIVE.parent / "image/build-native-payload.sh").read_text(encoding="utf-8")
    assert "rosy-nav-reapprove.service" in payload and "rosy-nav-reapprove.timer" in payload
