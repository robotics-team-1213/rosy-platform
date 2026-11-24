"""D-986 addendum 2026-11-20: the robot re-measures its navigation approval after a release change."""
from __future__ import annotations

import json
from pathlib import Path
import re
import ssl
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


def test_reapprove_waits_for_fresh_unplugged_voltage_before_trials(monkeypatch):
    assert not nr._battery_ready_for_trial({"battery_status": {"charging": True, "filtered_voltage": 7.6}}, HEALTH)
    assert not nr._battery_ready_for_trial({"battery_status": {"charging": None, "filtered_voltage": 7.6}}, HEALTH)
    assert not nr._battery_ready_for_trial({"battery_status": {"charging": False, "filtered_voltage": None}}, HEALTH)
    assert not nr._battery_ready_for_trial({"battery_status": {"charging": False, "filtered_voltage": 7.6}},
                                           {"battery": {"evidence": "missing", "level": "ok"}})
    assert not nr._battery_ready_for_trial({"battery_status": {"charging": False, "filtered_voltage": 7.6}},
                                           {"battery": {"evidence": "stale", "level": "ok"}})
    assert not nr._battery_ready_for_trial({"battery_status": {"charging": False, "filtered_voltage": 7.6}},
                                           {"battery": {"evidence": "fresh", "level": "critical"}})
    assert nr._battery_ready_for_trial({"battery_status": {"charging": False, "filtered_voltage": 7.6}}, HEALTH)

    polls = iter([
        OSError("CORE restarting"),
        ({"battery_status": {"charging": False, "filtered_voltage": None}},
         {"battery": {"evidence": "missing", "level": "ok"}}),
        ({"battery_status": {"charging": False, "filtered_voltage": 7.6}},
         {"battery": {"evidence": "stale", "level": "ok"}}),
        ({"battery_status": {"charging": False, "filtered_voltage": 7.6}},
         {"battery": {"evidence": "fresh", "level": "ok"}}),
    ])
    calls, phases = [], iter([{"phase": "MEASURING"}, {"phase": "IDLE", "approval": {"valid": True}}])

    class ReapproveCore:
        def get(self, path):
            calls.append(("GET", path))
            if path == "/api/v1/navigation/approval":
                return next(phases)
            if path == "/api/v1/robot/state":
                item = next(polls)
                if isinstance(item, Exception):
                    raise item
                self._current_poll = item
                return self._current_poll[0]
            if path == "/api/v1/power/health":
                return self._current_poll[1]
            raise AssertionError(f"unexpected GET {path}")

        def post(self, path, body=None, ok=()):
            calls.append(("POST", path))
            return {}

    slept = []
    monkeypatch.setattr(nr.time, "sleep", slept.append)
    monkeypatch.setattr(nr, "run_trial", lambda core, d, c, h: calls.append(("TRIAL", d, c)) or {"stop_latency_s": 0.1})
    logs = []
    nr.reapprove(ReapproveCore(), logs.append)

    first_trial_idx = next(i for i, call in enumerate(calls) if call[0] == "TRIAL")
    assert slept == [1.0, 1.0, 1.0]
    assert calls[0] == ("POST", "/api/v1/navigation/approval/begin")
    assert [c for c in calls[:first_trial_idx] if c[1] == "/api/v1/robot/state"] == [
        ("GET", "/api/v1/robot/state")] * 4
    assert [c for c in calls if c[0] == "TRIAL"] == [("TRIAL", d, c) for d, c, _ in nr.TRIALS]
    assert calls[-3:] == [
        ("POST", "/api/v1/navigation/approval/seal"),
        ("GET", "/api/v1/navigation/approval"),
        ("POST", "/api/v1/navigation/approval/navigation-start"),
    ]


def test_run_returns_cleanly_when_core_is_unavailable(robot_root):
    assert nr.run(robot_root, FakeCore(), sleep=lambda _: None,
                  pair_fn=lambda _: (_ for _ in ()).throw(OSError("connection refused"))).startswith("core unavailable:")

    class DownCore(FakeCore):
        def get(self, path):
            raise OSError("CORE down")

    down = DownCore()
    assert nr.run(robot_root, down, sleep=lambda _: None, pair_fn=lambda _: "token").startswith("core unavailable:")
    assert not any(call[0] == "POST" for call in down.calls)


def test_core_keeps_tls_after_first_tls_response(monkeypatch):
    class FakeResp:
        status = 200

        def read(self):
            return b'{"ok":true}'

    attempts = []

    class FakeHTTPS:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            attempts.append("https")
            if len(attempts) == 2:
                raise ssl.SSLEOFError("CORE restarted mid-handshake")

        def getresponse(self):
            return FakeResp()

        def close(self):
            pass

    monkeypatch.setattr(nr.http.client, "HTTPSConnection", FakeHTTPS)
    monkeypatch.setattr(nr.time, "sleep", lambda _: None)
    core = nr.Core()
    assert core.get("/api/v1/robot/state") == {"ok": True}
    assert core.tls is True and core._tls_confirmed is True
    assert core.get("/api/v1/robot/state") == {"ok": True}
    assert core.tls is True and len(attempts) == 3


def test_units_ship_enabled_and_the_run_never_fails_the_unit():
    service = (NATIVE / "rosy-nav-reapprove.service").read_text(encoding="utf-8")
    assert not re.search(r"^\s*Requires=", service, re.MULTILINE)
    assert re.search(r"^\s*Wants=.*\brosy-core\.service\b", service, re.MULTILINE)
    assert "navigation_reapprove.py run" in service and "Type=oneshot" in service
    assert "ConfigurationDirectory=rosy/approvals" in service
    timer = (NATIVE / "rosy-nav-reapprove.timer").read_text(encoding="utf-8")
    assert "WantedBy=timers.target" in timer and "OnBootSec=30s" in timer
    import image_layer_plan
    assert {"rosy-nav-reapprove.service", "rosy-nav-reapprove.timer"} <= set(image_layer_plan.UNITS)
    assert "rosy-nav-reapprove.timer" in image_layer_plan.ENABLED_UNITS
    rootfs = (NATIVE.parent / "image/customize-rootfs.sh").read_text(encoding="utf-8")
    assert "rosy-nav-reapprove.timer" in rootfs
    payload = (NATIVE.parent / "image/build-native-payload.sh").read_text(encoding="utf-8")
    assert "rosy-nav-reapprove.service" in payload and "rosy-nav-reapprove.timer" in payload


@pytest.mark.parametrize("changes,expected_prefix", [
    ({"navigation": "NAVIGATING"}, "navigation NAVIGATING"),
    ({"navigation": "PLANNING"}, "navigation PLANNING"),
    ({"navigation": "BLOCKED"}, "navigation BLOCKED"),
    ({"trip_lease": {"lease_id": "L1"}}, "trip lease active"),
    ({"line_follow": {"mode": "CAMERA_LINE", "state": "OFF"}}, "line follow active"),
    ({"line_follow": {"mode": "OFF", "state": "TRACKING"}}, "line follow active"),
    ({"docking": {"state": "DOCKING"}}, "docking DOCKING"),
    ({"docking": {"state": "UNDOCKING"}}, "docking UNDOCKING"),
    ({"swarm": {"active": True, "role": None}}, "swarm active"),
    ({"swarm": {"active": False, "role": "leader"}}, "swarm active"),
    ({"activity": {"kind": "CALIBRATING"}}, "activity active"),
    ({"safety": {"estop": True}}, "estop engaged"),
], ids=lambda v: str(v)[:32])
def test_decide_blocks_during_any_working_state(changes, expected_prefix):
    assert nr.decide(APPROVAL, {**ROBOT, **changes}, ROBOT, HEALTH, 0).startswith(expected_prefix)
    assert nr.decide(APPROVAL, ROBOT, {**ROBOT, **changes}, HEALTH, 0).startswith(expected_prefix)


@pytest.mark.parametrize("inputs", [
    {"robot_mode": "NAVIGATION", "nav_state": "IDLE"},
    {"robot_mode": "IDLE", "nav_state": "NAVIGATING"},
    {"robot_mode": "IDLE", "nav_state": "IDLE", "trip_lease_active": True},
    {"robot_mode": "IDLE", "nav_state": "IDLE", "calibration_active": True},
    {"robot_mode": "IDLE", "nav_state": "IDLE", "trip_lease_active": None},
    {"robot_mode": "IDLE", "nav_state": "IDLE", "calibration_active": None},
    {"robot_mode": "IDLE", "nav_state": "IDLE", "docking_state": "DOCKING"},
    {"robot_mode": "IDLE", "nav_state": "IDLE", "velocity_linear": 0.05},
    "{corrupt",
])
def test_run_exits_before_pairing_when_status_inputs_busy_or_corrupt(robot_root, inputs):
    status_path = robot_root / "run/rosy/status-inputs.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(inputs if isinstance(inputs, str) else json.dumps(inputs), encoding="utf-8")
    never = lambda core, log: pytest.fail("must not re-measure")  # noqa: E731
    assert nr.run(robot_root, FakeCore(), sleep=lambda s: None, reapprove_fn=never,
                  pair_fn=lambda c: pytest.fail("must not pair when busy")) != "approved and navigation started"


def test_approved_robot_auto_starts_navigation_once_per_boot_when_idle_and_unguarded(tmp_path, monkeypatch):
    boot_file = tmp_path / "proc/sys/kernel/random/boot_id"
    boot_file.parent.mkdir(parents=True)
    boot_file.write_text("boot-uuid-1\n", encoding="utf-8")
    status_path = tmp_path / "run/rosy/status-inputs.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({"robot_mode": "IDLE", "nav_state": "IDLE", "estop": False}), encoding="utf-8")
    monkeypatch.setattr(nr.mapping_approval, "check", lambda root: {"ready": True})
    monkeypatch.setattr(nr.rosy_claim, "check", lambda root: None)
    calls = []
    nav_up = {"active": False}
    def fake_runner(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "is-active":
            return subprocess.CompletedProcess(argv, 0 if nav_up["active"] else 3, "", "")
        if argv[1] == "start":
            nav_up["active"] = True
        return subprocess.CompletedProcess(argv, 0, "", "")
    assert nr.run(tmp_path, runner=fake_runner) == "navigation auto-started"
    assert [c[1] for c in calls] == ["is-active", "start", "is-active"]
    assert nr.run(tmp_path, runner=fake_runner) == "approved"
    assert len(calls) == 3
    # If start succeeds synchronously but ExecCondition/runtime fails to stay active, marker is withheld to retry.
    boot_file.write_text("boot-uuid-1b\n", encoding="utf-8")
    nav_up["active"] = False
    calls.clear()
    def flaky_runner(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "is-active":
            return subprocess.CompletedProcess(argv, 3, "", "")
        return subprocess.CompletedProcess(argv, 0, "", "")
    assert nr.run(tmp_path, runner=flaky_runner) == "approved"
    assert not (tmp_path / "run/rosy/nav-auto-started").read_text(encoding="utf-8").strip() == "boot-uuid-1b"
    # Motion hold env blocks auto-start on a fresh boot.
    boot_file.write_text("boot-uuid-2\n", encoding="utf-8")
    guard = tmp_path / "run/rosy-os-update/motion.env"
    guard.parent.mkdir(parents=True)
    guard.write_text("ROSY_IO_DRIVE_ENABLED=false\n", encoding="utf-8")
    assert nr.run(tmp_path, runner=fake_runner) == "approved"
    assert len(calls) == 3


def test_run_restores_shared_approvals_before_auto_start(tmp_path, monkeypatch):
    (tmp_path / "var/lib/rosy-device/approvals").mkdir(parents=True)
    (tmp_path / "var/lib/rosy-device/approvals/g4.bundle.json").write_text("{}", encoding="utf-8")
    restored = []
    monkeypatch.setattr(nr.mapping_approval, "restore_approvals_from_shared", lambda root: restored.append(root) or True)
    monkeypatch.setattr(nr.mapping_approval, "check", lambda root: {"ready": True})
    assert nr.run(tmp_path) == "approved"
    assert restored == [tmp_path]
