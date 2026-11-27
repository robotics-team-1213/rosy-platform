"""Tests for coupled MuJoCo S3 intake & cell-stage bridge (D-1088 Slice 3)."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIM_DIR = ROOT / "tools" / "sim"
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

import coupled_mujoco_bridge as cmb  # noqa: E402
import coupled_sim_controller as csc  # noqa: E402

MAP_SHA = "ef" * 32


class _VirtualClock:
    """Deterministic instantaneous clock/sleeper pair for WallClockPacer tests."""

    def __init__(self, *, step_wall_s: float = 0.0) -> None:
        self.now = 0.0
        self.step_wall_s = step_wall_s
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleeper(self, dt: float) -> None:
        self.sleeps.append(dt)
        self.now += dt

    def advance_step(self, _idx: int) -> None:
        self.now += self.step_wall_s


def _make_pacer(*, step_wall_s: float = 0.002) -> cmb.WallClockPacer:
    vc = _VirtualClock(step_wall_s=step_wall_s)

    def _clock() -> float:
        return vc.now

    def _sleep(dt: float) -> None:
        vc.sleeper(dt)

    class _InstantPacer(cmb.WallClockPacer):
        def run_steps(self, count: int, step_fn: Any = None) -> float:
            def _wrapped(idx: int) -> None:
                if step_fn is not None:
                    step_fn(idx)
                vc.advance_step(idx)

            return super().run_steps(count, _wrapped)

    return _InstantPacer(step_dt_s=0.02, pace_factor=1.0, clock=_clock, sleeper=_sleep)


@contextmanager
def _controller_server() -> Iterator[tuple[csc.CoupledSimController, str]]:
    ctrl = csc.CoupledSimController(site_map_sha256=MAP_SHA)
    server = csc.build_server(ctrl, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield ctrl, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_wall_clock_pacer_nominal_slow_and_nonpositive() -> None:
    vc_fast = _VirtualClock()
    pacer_fast = cmb.WallClockPacer(step_dt_s=0.02, pace_factor=1.0, clock=vc_fast.clock, sleeper=vc_fast.sleeper)
    assert pacer_fast.run_steps(0) == 1.0
    assert pacer_fast.run_steps(-2) == 1.0
    assert vc_fast.sleeps == []

    rtf_fast = pacer_fast.run_steps(5)
    assert rtf_fast == pytest.approx(1.0)
    assert len(vc_fast.sleeps) == 5

    pacer_slow = _make_pacer(step_wall_s=0.04)  # 0.04s per 0.02s sim step -> RTF = 0.5
    assert pacer_slow.run_steps(5) == pytest.approx(0.5)


def test_nominal_s3_handoff_reaches_on_ship_and_permits_departure() -> None:
    with _controller_server() as (ctrl, url):
        s3 = ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.015, dy_m=-0.01, dyaw_rad=0.04)
        assert s3["accepted"] is True

        runner = cmb.MujocoCellRunner(backend="stub", pacer=_make_pacer(step_wall_s=0.002))
        bridge = cmb.CoupledMujocoBridge(url, runner=runner)
        res = bridge.poll_once()

        assert res["action"] == "advanced"
        assert res["cargo_state"] == "ON_SHIP"
        assert res["clear_reply"]["pinky_departure_permitted"] is True

        snap = ctrl.state_snapshot()
        assert snap["cargo_state"] == "ON_SHIP"
        assert snap["pinky_has_cargo"] is False
        assert snap["arm_in_bed_zone"] is False
        assert snap["inconclusive"] is False
        clear_events = [ev for ev in snap["events"] if ev["event"] == "CELL_BED_CLEAR"]
        assert len(clear_events) == 1 and clear_events[0]["accepted"] is True


def test_out_of_envelope_s3_pose_triggers_cargo_fault_and_blocks_departure() -> None:
    with _controller_server() as (ctrl, url):
        ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.09, dy_m=0.0, dyaw_rad=0.0)
        runner = cmb.MujocoCellRunner(backend="stub", pacer=_make_pacer(step_wall_s=0.002))
        bridge = cmb.CoupledMujocoBridge(url, runner=runner)

        res = bridge.poll_once()
        assert res["action"] == "cargo_lifted_held"
        assert res["cargo_state"] == "CARGO_FAULT"
        assert res["grasp"]["reason"] == "POSE_OUT_OF_ENVELOPE"

        depart = ctrl.handle_cell_bed_clear(arm_in_bed_zone=False)
        assert depart["accepted"] is False
        assert depart["pinky_departure_permitted"] is False
        assert depart["reason"] == "CARGO_FAULT_HOLD"


def test_slow_pacer_marks_controller_inconclusive() -> None:
    with _controller_server() as (ctrl, url):
        ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.01, dy_m=0.01, dyaw_rad=0.02)
        slow_runner = cmb.MujocoCellRunner(backend="stub", pacer=_make_pacer(step_wall_s=0.04))
        bridge = cmb.CoupledMujocoBridge(url, runner=slow_runner)

        res = bridge.poll_once()
        assert res["cargo_state"] == "ON_SHIP"

        snap = ctrl.state_snapshot()
        assert snap["min_rtf"] == pytest.approx(0.5)
        assert snap["inconclusive"] is True


def test_arm_usb_unplugged_holds_then_recovers_to_on_ship() -> None:
    with _controller_server() as (ctrl, url):
        ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.01, dy_m=0.0, dyaw_rad=0.0)
        ctrl.faults.enable("arm.usb_unplugged", {"arm_id": "arm_s"})

        runner = cmb.MujocoCellRunner(backend="stub", pacer=_make_pacer(step_wall_s=0.002))
        bridge = cmb.CoupledMujocoBridge(url, runner=runner)

        held_s3 = bridge.poll_once()
        assert held_s3["action"] == "cargo_lifted_held"
        assert held_s3["cargo_state"] == "HANDOFF_AT_S3"

        ctrl.faults.disable("arm.usb_unplugged")
        recovered = bridge.poll_once()
        assert recovered["action"] == "advanced"
        assert recovered["cargo_state"] == "ON_SHIP"

        ctrl.reset(clear_faults=True)
        ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.01, dy_m=0.0, dyaw_rad=0.0)
        ctrl.faults.enable("arm.usb_unplugged", {"arm_id": "arm_b"})

        held_ab = bridge.poll_once()
        assert held_ab["action"] == "stage_held"
        assert held_ab["cargo_state"] == "ON_BELT"

        ctrl.faults.disable("arm.usb_unplugged")
        resumed = bridge.poll_once()
        assert resumed["action"] == "advanced"
        assert resumed["cargo_state"] == "ON_SHIP"


def test_act_policy_client_fail_closed_and_refusal() -> None:
    mode = {"status": 200, "body": {"ok": False, "reason": "POLICY_HOLD"}}

    class _ActHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _send(self, code: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "NOT_FOUND"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            _ = self.rfile.read(length)
            self._send(int(mode["status"]), dict(mode["body"]))  # type: ignore[arg-type]

    server = ThreadingHTTPServer(("127.0.0.1", 0), _ActHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = cmb.ActPolicyClient(f"http://127.0.0.1:{server.server_port}")
        assert client.health() == {"ok": True}

        runner = cmb.MujocoCellRunner(backend="stub", pacer=_make_pacer(step_wall_s=0.002))
        refused = runner.execute_s3_grasp(dx_m=0.01, dy_m=0.0, dyaw_rad=0.0, act_client=client)
        assert refused["lifted"] is False
        assert refused["reason"] == "POLICY_HOLD"

        mode["status"] = 500
        mode["body"] = {"error": "INFERENCE_CRASH"}
        with pytest.raises(RuntimeError, match="HTTP_500"):
            runner.execute_s3_grasp(dx_m=0.01, dy_m=0.0, dyaw_rad=0.0, act_client=client)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    bad_client = cmb.ActPolicyClient("http://127.0.0.1:1", timeout_s=0.2)
    with pytest.raises(RuntimeError):
        bad_client.health()


def test_mujoco_backend_real_physics_if_installed() -> None:
    try:
        import mujoco  # noqa: F401
    except (ImportError, OSError) as exc:
        pytest.skip(f"mujoco unavailable: {exc}")
    runner = cmb.MujocoCellRunner(backend="mujoco", pacer=_make_pacer(step_wall_s=0.002))
    ok = runner.execute_s3_grasp(dx_m=0.012, dy_m=-0.008, dyaw_rad=0.03)
    assert ok["backend"] == "mujoco"
    assert ok["lifted"] is True and ok["bilateral_lift"] is True and ok["arm_in_bed_zone"] is False

    bad = runner.execute_s3_grasp(dx_m=0.10, dy_m=0.0, dyaw_rad=0.0)
    assert bad["backend"] == "mujoco"
    assert bad["lifted"] is False and bad["reason"] == "POSE_OUT_OF_ENVELOPE"
