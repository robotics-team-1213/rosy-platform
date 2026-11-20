"""D-1051: ReparkExecutor turns a site shift into a robot-body shift, sends it, and closes the request."""

import asyncio
import math

from fleet.server.repark_exec import ReparkExecutor, site_to_body


def test_site_to_body_follows_the_robot_heading():
    f, l = site_to_body([0.0, 0.038], 0.0)          # facing +x: site +y is the robot's left
    assert abs(f) < 1e-9 and abs(l - 0.038) < 1e-9
    f, l = site_to_body({"x": 0.0, "y": 0.038}, math.pi)  # facing -x (S3 arrival): site +y is the right
    assert abs(f) < 1e-9 and abs(l + 0.038) < 1e-9


class _Client:
    def __init__(self, states):
        self.states, self.sent = list(states), []

    async def repark(self, forward_m, left_m, operator_name):
        self.sent.append((forward_m, left_m, operator_name))
        return {"state": "running"}

    async def repark_status(self):
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    async def repark_stop(self):
        self.sent.append("stop")


def _run(req, client, yaw=math.pi):
    async def yaw_of(_):
        return yaw
    closed = []

    async def close(*args):
        closed.append(args)
    ex = ReparkExecutor(lambda: {"b8xy": client}, yaw_of, close, poll_s=0.0, timeout_s=0.05)
    return asyncio.run(ex.execute(req)), ex


REQ = {"request_id": "r1", "robot_id": "b8xy", "state": "REQUESTED", "need_site_dxdy_m": [0.0, 0.038]}


def test_done_is_closed_with_the_measured_move():
    moved = {"forward_m": 0.002, "left_m": -0.037}
    client = _Client([{"state": "running"}, {"state": "done", "moved_robot_dxdy_m": moved}])
    (state, rid, body), _ = _run(REQ, client)
    assert (state, rid, body) == ("DONE", "r1", {"state": "DONE", "moved_robot_dxdy_m": moved})
    assert client.sent[0][1] == -0.038


def test_failures_close_failed_with_a_reason():
    (s, _, body), _ = _run({**REQ, "need_site_dxdy_m": None}, _Client([{}]))
    assert s == "FAILED" and body["reason"] == "no_site_delta"
    client = _Client([{"state": "aborted", "reason": "obstacle", "moved_robot_dxdy_m": {"forward_m": 0, "left_m": 0}}])
    (s, _, body), _ = _run(REQ, client)
    assert s == "FAILED" and body["reason"] == "core_aborted: obstacle"
    stuck = _Client([{"state": "running"}])                        # never ends: stopped and failed
    (s, _, body), _ = _run(REQ, stuck)
    assert s == "FAILED" and body["reason"] == "timeout" and stuck.sent[-1] == "stop"


def test_tick_starts_only_requested_once():
    async def go():
        client = _Client([{"state": "done"}])
        closed = []

        async def yaw_of(_):
            return 0.0

        async def close(*a):
            closed.append(a)
        ex = ReparkExecutor(lambda: {"b8xy": client}, yaw_of, close, poll_s=0.0)
        await ex.tick([REQ, {**REQ, "request_id": "r2", "state": "DONE"}])
        await ex.tick([REQ])
        await asyncio.sleep(0.05)
        return closed
    closed = asyncio.run(go())
    assert [c[1] for c in closed] == ["r1"]
