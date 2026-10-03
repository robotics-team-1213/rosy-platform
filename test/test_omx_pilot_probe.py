"""D-411 C: the Pilot SIM HTTP probe, run end to end against the real SIM API and runtime.

The arm is a fake that behaves like the Gazebo owner (owner "active" while a goal runs, goals
settle after their duration, a gripper closing on an object stops at the object), so the probe's
own logic -- paced absolute gripper goals, close then open, the stall/holding gate -- is checked
on the host. It is not ROS-SIM evidence.
"""

from __future__ import annotations

import contextlib
import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
for extra in ("src/products/omx/adapter", "src/contracts/foundation"):
    if str(ROOT / extra) not in sys.path:
        sys.path.insert(0, str(ROOT / extra))

uvicorn = pytest.importorskip("uvicorn")

from omx_adapter.command_owner import ArmCommandConfig, CommandDecision, JointStateSnapshot  # noqa: E402
from omx_adapter.pilot_sim_api import create_pilot_sim_app  # noqa: E402
from omx_adapter.pilot_sim_runtime import (PilotSimRuntime, sim_admission_limits,  # noqa: E402
                                           urdf_position_limits, urdf_velocity_limits)
from omx_adapter.pose_plan import CellPlanningProfile  # noqa: E402
from omx_adapter.ros_goal_contract import RosGoalEvent  # noqa: E402

SPEC = importlib.util.spec_from_file_location("omx_pilot_probe", ROOT / "deploy/robot/omx/probe_pilot_sim_http.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

CELL = CellPlanningProfile.load(ROOT / "deploy/robot/omx/sim/cell_profile.yaml")
TIME_SCALE = 0.1          # fake goals settle in a tenth of their duration


class FakeArm:
    """Owner-like arm: 'active' while a goal runs, settles to the target after its duration."""

    def __init__(self, *, fail_close=False, gripper_lag_s=0.0, mismatches=0):
        config = ArmCommandConfig(
            enabled=True, workcell_id="sim", instance_id="omx_pilot_sim_01", joint_names=CELL.joint_names,
            position_limits=sim_admission_limits(CELL.position_limits, urdf_position_limits()),
            allowed_owners=("pilot_sim",), calibration_revision="sim", max_joint_state_age_s=0.5,
            max_goal_duration_s=2.0, action_timeout_s=8.0)
        self.owner = SimpleNamespace(config=config, state="ready", session_id="session")
        self.action_port = SimpleNamespace(server_is_ready=lambda: True)
        self.positions = {name: 0.0 for name in CELL.joint_names}
        self.sequence = 0
        self.object_at = None            # gripper position where the fingers meet a spawned cube
        self.fail_close = fail_close
        # Gazebo: the gripper goal tolerance is 0.0, so SUCCEEDED can arrive before the fingers do.
        self.gripper_lag_s = gripper_lag_s
        self.mismatches = mismatches     # owner refusals "joint_state_sequence_mismatch" still to give
        self.runtime = None
        self.commands = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._publish()
        threading.Thread(target=self._spin, daemon=True).start()

    def _publish(self):
        with self._lock:
            self._publish_locked()

    def _publish_locked(self):
        self.sequence += 1
        self.latest_joint_state = JointStateSnapshot(positions=dict(self.positions), sequence=self.sequence,
                                                     received_at=time.monotonic(), calibration_revision="sim")

    def _spin(self):
        while not self._stop.wait(0.02):
            self._publish()

    def close(self):
        self._stop.set()

    def submit(self, command):
        if self.mismatches:
            self.mismatches -= 1
            return CommandDecision(False, "ready", "joint_state_sequence_mismatch", command.command_id)
        self.commands.append(command)
        self.owner.state = "active"
        threading.Thread(target=self._run, args=(command,), daemon=True).start()
        return CommandDecision(True, "active", "submitted", command.command_id)

    def _event(self, command, goal_id, kind, sequence, **facts):
        self.runtime.on_goal_event(RosGoalEvent(kind=kind, command_id=command.command_id, phase_id=None,
                                                goal_id=goal_id, observed_at_monotonic_s=time.monotonic(),
                                                sequence=sequence, **facts))

    def _run(self, command):
        goal_id = str(uuid4())
        self._event(command, goal_id, "GOAL_ACCEPTED", 1)
        time.sleep(command.duration_s * TIME_SCALE)
        target = dict(command.positions)
        gripper = CELL.gripper_joint
        closing_on_object = self.object_at is not None and target[gripper] < self.object_at
        if closing_on_object:
            target[gripper] = self.object_at
        late = self.gripper_lag_s and target[gripper] != self.positions[gripper]
        if late:
            final, target[gripper] = target[gripper], self.positions[gripper] + 0.6 * (target[gripper] - self.positions[gripper])
        self.positions.update(target)
        self._publish()
        if late:
            def arrive():   # the fingers keep moving after SUCCEEDED, then stop at the target
                start, steps = self.positions[gripper], max(1, round(self.gripper_lag_s / 0.02))
                for step in range(1, steps + 1):
                    time.sleep(0.02)
                    self.positions[gripper] = start + (final - start) * step / steps
            threading.Thread(target=arrive, daemon=True).start()
        if closing_on_object and self.fail_close:
            self.owner.state = "hold"
            self._event(command, goal_id, "TERMINAL_RESULT", 2, status=6, result_code=-5)
            return
        self.owner.state = "ready"
        self._event(command, goal_id, "TERMINAL_RESULT", 2, status=4, result_code=0)

    def cancel(self, *, command_id, owner):
        self.owner.state = "hold"
        return CommandDecision(False, "hold", "cancel_requested", command_id, "call_returned")


@contextlib.contextmanager
def _server(arm):
    runtime = PilotSimRuntime(
        arm, gripper=CELL.gripper_joint, range_inset_rad=CELL.start_state_tolerance_rad,
        gripper_open=CELL.gripper_open, gripper_closed=CELL.gripper_closed,
        gripper_velocity=min(CELL.velocity_limits[CELL.gripper_joint], urdf_velocity_limits()[CELL.gripper_joint]),
        gripper_preload=CELL.gripper_preload_rad)
    arm.runtime = runtime
    original_cancel = arm.cancel

    def cancel(*, command_id, owner):
        decision = original_cancel(command_id=command_id, owner=owner)

        def canceled():   # the ROS cancel result arrives after the request returns
            time.sleep(0.1)
            runtime.on_goal_event(RosGoalEvent(kind="TERMINAL_RESULT", command_id=command_id, phase_id=None,
                                               goal_id=str(uuid4()), observed_at_monotonic_s=time.monotonic(),
                                               sequence=9, status=5, result_code=0))

        threading.Thread(target=canceled, daemon=True).start()
        return decision

    arm.cancel = cancel
    app = create_pilot_sim_app(runtime=runtime, pilot_root=ROOT / "middleware/ui/pilot",
                               common_root=ROOT / "shared/web", pairing_code="ABCD-EFGH")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            thread.join(0.05)
        assert server.started
        yield f"http://127.0.0.1:{port}/api/v1/sim/omx", runtime
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        arm.close()


def test_basic_probe_jogs_paces_the_gripper_and_closes_then_opens(capsys):
    arm = FakeArm()
    with _server(arm) as (base, _):
        assert probe.main(["--inside"], base=base, code="ABCD-EFGH") == 0
    out = capsys.readouterr().out
    # Gazebo 2026-10-03 D1: the nudge was resent three times (rounded target never "arrived").
    nudges = [command for command in arm.commands if command.positions[CELL.gripper_joint] == pytest.approx(0.02)]
    assert len(nudges) == 1, [command.positions for command in arm.commands]
    for line in ("joint1_goal=SUCCEEDED", "gripper_nudge=SUCCEEDED", "gripper_close=SUCCEEDED",
                 "gripper_open=SUCCEEDED", "cancel_terminal=CANCELED"):
        assert line in out, out
    # Every gripper goal went through the runtime's speed check (a refusal would have failed the probe).
    gripper_targets = [command.positions[CELL.gripper_joint] for command in arm.commands]
    assert {0.02, 0.0, 1.0} <= set(gripper_targets)


def test_stall_probe_records_terminal_facts_and_holds_through_three_jogs(capsys):
    arm = FakeArm()
    spawned = []

    def spawn(size, x, y, z, yaw):
        spawned.append((size, x, y, z, yaw))
        arm.object_at = 0.3

    with _server(arm) as (base, _):
        code = probe.main(["--inside", "--stall"], base=base, code="ABCD-EFGH",
                          spawner=(spawn, lambda: spawned.append("removed")))
    out = capsys.readouterr().out
    assert code == 0, out
    report = probe.json.loads(next(line for line in out.splitlines() if line.startswith("stall_probe="))[12:])
    assert report["terminal_state"] == "SUCCEEDED" and (report["status"], report["result_code"]) == (4, 0)
    assert report["gripper_state"] == "holding" and report["passed"] is True
    assert abs(report["gripper_readback"] - 0.3) < 1e-9 and report["time_to_terminal_s"] > 0
    assert CELL.gripper_joint in report["peak_speed_last_0_5s"]
    assert [jog["state"] for jog in report["holding_jogs"]] == ["SUCCEEDED"] * 3
    assert {jog["gripper_state"] for jog in report["holding_jogs"]} == {"holding"}
    # The arm jogs while holding squeeze by the profile preload past the stall, never to closed.
    squeezes = [command.positions[CELL.gripper_joint] for command in arm.commands[-3:]]
    assert squeezes == [pytest.approx(0.3 - CELL.gripper_preload_rad)] * 3
    assert spawned[0][0] == 0.025 and spawned[-1] == "removed"
    # The holding close is re-issued at stall + preload before the jogs (Gazebo grip loosening, L1).
    assert report["hold_target"] == pytest.approx(0.3 - CELL.gripper_preload_rad)
    assert arm.commands[-4].command_id.startswith("hold-")
    assert report["open_readback"] == 1.0 and report["close_goals"] == 2 and report["pace_margin"] == 0.9


def test_stall_probe_reports_a_failed_close_and_does_not_pass(capsys):
    arm = FakeArm(fail_close=True)

    def spawn(*_):
        arm.object_at = 0.3

    with _server(arm) as (base, _):
        code = probe.main(["--inside", "--stall"], base=base, code="ABCD-EFGH", spawner=(spawn, lambda: None))
    out = capsys.readouterr().out
    report = probe.json.loads(next(line for line in out.splitlines() if line.startswith("stall_probe="))[12:])
    assert code == 2
    assert report["terminal_state"] == "UNKNOWN_HOLD" and (report["status"], report["result_code"]) == (6, -5)
    assert report["gripper_state"] == "unknown" and report["holding_jogs"] == [] and report["passed"] is False


def test_paced_gripper_goal_never_exceeds_the_speed():
    fake = SimpleNamespace(gripper={"open": 1.0, "closed": 0.0, "max_velocity": 0.5})
    goal = probe.Probe.gripper_goal
    # pace margin 0.9: 0.45 rad/s, reach 0.9 rad in 2.0 s; within reach the EXACT target is returned.
    assert goal(fake, 0.0168 + 0.02, 0.0168) == (0.0168 + 0.02, 0.2)
    assert goal(fake, 1.0, 0.0) == (0.9, 2.0)
    assert goal(fake, 1.0, -0.011) == (0.889, 2.0)        # clipped to what 2.0 s reaches
    assert goal(fake, 0.0, 0.333) == (0.0, 0.74)
    fake.pace_margin = 1.0
    assert goal(fake, 1.0, 0.0) == (1.0, 2.0)
    assert probe.terminal_facts({"state": "UNKNOWN_HOLD", "reason": "terminal_status_6_result_-5"}) == {
        "status": 6, "result_code": -5}
    assert probe.peak_speeds([(0.0, {"j": 0.0}), (0.1, {"j": 0.05}), (0.2, {"j": 0.05})]) == {"j": 0.5}


def test_move_gripper_reports_the_readback_before_its_first_goal():
    calls = []

    class Fake(probe.Probe):
        def __init__(self):
            self.gripper = {"joint": "g", "open": 1.0, "closed": 0.0, "max_velocity": 0.5}
            self.pace_margin = 0.9
            self.readback = 0.0

        def ready_state(self, timeout_s=30.0):
            return {"positions": {"g": self.readback}, "instance_id": "i", "state_sequence": 1}

        def _post(self, path, fields, current):
            calls.append(fields["position"])
            self.readback = fields["position"]
            return "id"

        def follow(self, command_id, samples=None, timeout_s=60.0):
            return {"state": "SUCCEEDED"}, 0.1

        def call(self, path, **kwargs):
            return {"positions": {"g": self.readback}}

    result = Fake().move_gripper(1.0)
    assert calls == [0.9, 1.0] and result["before"] == 0.0 and result["goals"] == 2


def test_gz_service_runs_with_the_ros_environment_sourced(monkeypatch):
    seen = []
    monkeypatch.setattr(probe.subprocess, "run", lambda cmd, **kwargs: seen.append(cmd))
    spawn, remove = probe.gz_spawner("rosy-omx-pilot-sim")
    spawn(0.025, 0.18, 0.0, 0.0125, 0.0)
    remove()
    for cmd in seen:
        assert cmd[:7] == ["docker", "exec", "rosy-omx-pilot-sim", "bash", "-c",
                           'source /opt/ros/jazzy/setup.bash; exec "$@"', "gz"]
        assert cmd[7:9] == ["gz", "service"]
    assert [cmd[10] for cmd in seen] == ["/world/omx_pilot_workcell/create", "/world/omx_pilot_workcell/remove"]
    seen.clear()
    probe.gz_spawner("--inside")[1]()
    assert seen[0][:2] == ["bash", "-c"]


def test_probe_waits_for_the_fingers_after_an_early_success(capsys):
    """Gazebo gate 2026-10-03: open SUCCEEDED 0.027-0.056 rad short; the probe must wait for stillness."""
    arm = FakeArm(gripper_lag_s=0.3)
    with _server(arm) as (base, _):
        assert probe.main(["--inside"], base=base, code="ABCD-EFGH") == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "gripper_open=SUCCEEDED" in out and "after=1.0000" in out


def test_probe_retries_one_sequence_mismatch(capsys):
    arm = FakeArm(mismatches=1)
    with _server(arm) as (base, _):
        assert probe.main(["--inside"], base=base, code="ABCD-EFGH") == 0, capsys.readouterr()
    assert arm.mismatches == 0


def test_stall_report_carries_holding_drift_without_gating(capsys):
    arm = FakeArm()
    drift = iter([0.01, 0.02, 0.03])

    def spawn(*_):
        arm.object_at = 0.3

    original = arm._run

    def slipping(command):
        original(command)
        if command.command_id.startswith("hold-") or arm.object_at is None:
            return
        if command.positions[CELL.gripper_joint] == pytest.approx(0.3 - CELL.gripper_preload_rad):
            arm.positions[CELL.gripper_joint] = 0.3 + next(drift)    # the cube slips a little per jog

    arm._run = slipping
    with _server(arm) as (base, _):
        code = probe.main(["--inside", "--stall"], base=base, code="ABCD-EFGH", spawner=(spawn, lambda: None))
    out = capsys.readouterr().out
    report = probe.json.loads(next(line for line in out.splitlines() if line.startswith("stall_probe="))[12:])
    assert code == 0 and report["passed"] is True
    assert report["holding_drift_rad"] == pytest.approx(0.03, abs=1e-6)   # opened by 0.03 rad over the jogs
