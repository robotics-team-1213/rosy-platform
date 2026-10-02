"""D-395 Phase 2 cross-lane contract: robot node (A) <-> CORE (B) <-> Fleet (C).

Contract: docs/plans/2026-10-01-d395-phase2-interfaces.md §1-§3. Each lane has
its own tests against its reading of the contract; this file runs the three
real pieces against one another on the host, with ROS replaced by the JSON the
topics carry:

- lane A's pure core (`control.loc_assist.LocAssist`) builds the
  `localization/state|candidates|result` payloads, serialised the way
  `loc_assist_node.publish` does (json.dumps, sort_keys);
- lane B's `services.localization` parses them as `ros_bridge` relays them, and
  its decision/suspect publishers are captured and serialised as the bridge does
  (json.dumps) before lane A's `on_decision`/`on_suspect` reads them;
- lane C's `HttpRobotClient` calls lane B's FastAPI app in process (ASGI), and
  lane C's `Arbiter` makes the decision from the report it fetched.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_FLEET = Path(__file__).resolve().parents[3] / "site" / "fleet"
if str(_FLEET) not in sys.path:
    sys.path.insert(0, str(_FLEET))

httpx = pytest.importorskip("httpx")
pytest.importorskip("numpy")

from control.loc_assist import LocAssist  # noqa: E402
from fleet.localization.arbiter import Arbiter, Context  # noqa: E402
from fleet.swarm.robots import RobotEndpoint  # noqa: E402
from fleet.swarm.transport import HttpRobotClient  # noqa: E402

ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
FLEET_TOKEN = "fleet-site-operator-token-0001"


class _Robot:
    """Lane A's core with the node's JSON wire format, on one robot clock."""

    def __init__(self) -> None:
        self.now = 10.0
        self.core = LocAssist(lambda: "req-1", hold_s=1.0)
        self.injected = []

    def wire(self, outputs) -> dict:
        """What `loc_assist_node.publish` puts on each topic, by kind."""
        topics = {}
        for kind, payload in outputs:
            if kind == "inject":
                self.injected.append(payload)
            else:
                topics.setdefault(kind, []).append(json.dumps(payload, sort_keys=True))
        return topics


def _relay(services, topics: dict) -> None:
    """`ros_bridge` callbacks: the raw String data into lane B."""
    loc = services.localization
    for raw in topics.get("state", []):
        loc.on_state(raw)
    for raw in topics.get("candidates", []):
        loc.on_candidates(raw)
    for raw in topics.get("result", []):
        loc.on_result(raw)


@pytest.fixture
def stack(core_client):
    client, services = core_client()
    robot = _Robot()
    loc = services.localization
    sent = {"decision": [], "suspect": []}
    # ros_bridge binds these to String(data=json.dumps(body)) and the ROS clock.
    loc.publish_decision = lambda body: sent["decision"].append(json.dumps(body))
    loc.publish_suspect = lambda body: sent["suspect"].append(json.dumps(body))
    loc.clock = lambda: robot.now
    made = client.post("/api/v1/system/tokens", headers=ADMIN, json={
        "role": "operator", "label": "site:fleet", "token": FLEET_TOKEN})
    assert made.status_code == 201
    return SimpleNamespace(client=client, services=services, robot=robot, sent=sent)


def _fleet_call(stack, robot_id: str, call):
    """Run one lane C client call against lane B's app."""

    async def go():
        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=stack.client.app),
                                 base_url="http://robot")
        client = HttpRobotClient(RobotEndpoint(robot_id, "http://robot", FLEET_TOKEN), http=http)
        try:
            return await call(client)
        finally:
            await http.aclose()

    return asyncio.run(go())


def _to_candidates(stack) -> None:
    """Lane A: power-on state, one search with a paint-carried leader and its mirror."""
    robot = stack.robot
    robot.core.on_amcl_pose((0.0, 0.0, 0.0))
    _relay(stack.services, robot.wire(robot.core.tick(robot.now)))
    robot.core.search_started(robot.now, (0.0, 0.0, 0.0))
    robot.now += 0.5
    found = [SimpleNamespace(x=1.0, y=2.0, yaw=0.0, scan_fit=0.9),
             SimpleNamespace(x=1.0, y=2.0, yaw=3.14159, scan_fit=0.9)]
    _relay(stack.services, robot.wire(robot.core.search_finished(
        robot.now, (0.0, 0.0, 0.0), found, unmapped=[(1.5, 2.5)], paint_scores=[0.9, 0.0],
        evidence_s=robot.now)))


def _robot_state(stack) -> dict:
    return stack.client.get("/api/v1/robot/state", headers=OPERATOR).json()["localization"]


def test_state_and_candidates_from_lane_a_parse_in_lane_b(stack):
    _to_candidates(stack)
    status = _robot_state(stack)
    assert status["state"] == "CANDIDATES" and status["request_id"] == "req-1"
    assert status["pose_frame"] == "map"
    report = stack.services.localization.candidates()
    assert report is not None and report.request_id == "req-1"
    assert [(c.x, c.y, c.paint_score) for c in report.candidates] == [
        (1.0, 2.0, 0.9), (1.0, 2.0, 0.0)]
    assert [(o.x, o.y) for o in report.unmapped_objects] == [(1.5, 2.5)]


def _localize_through_fleet(stack) -> str:
    """C fetches B's report, arbitrates and posts; A checks the pose; B sees LOCALIZED."""
    _to_candidates(stack)
    robot_id = stack.services.localization.candidates().robot_id
    arbiter = Arbiter(hold_s=0.0)

    async def fetch_and_decide(client):
        decision = None
        for _ in range(2):          # the arbiter's lead needs a second look
            report = await client.localization_candidates()
            assert report is not None and report.robot_id == robot_id
            decision = arbiter.observe(report, Context(), stack.robot.now) or decision
        assert decision is not None and decision.candidate_index == 0
        assert [c.value for c in decision.cues] == ["paint"]
        return await client.localization_decision(decision)

    assert _fleet_call(stack, robot_id, fetch_and_decide) == {"request_id": "req-1"}

    # CORE -> robot: B's decision payload is what A's on_decision accepts.
    [raw] = stack.sent["decision"]
    robot = stack.robot
    robot.now += 0.1
    topics = robot.wire(robot.core.on_decision(robot.now, json.loads(raw)))
    assert "result" not in topics, topics.get("result")
    [injection] = robot.injected
    assert injection.pose == (1.0, 2.0, 0.0) and injection.source == "candidate"

    # settle 0.5 s + hold 1 s of good fits; A's result and LOCALIZED state parse in B.
    for _ in range(20):
        robot.now += 0.1
        _relay(stack.services, robot.wire(robot.core.on_fit(robot.now, 0.95)))
    return robot_id


def test_fleet_decision_round_trip_localizes_the_robot(stack):
    _localize_through_fleet(stack)
    results = [e.data for e in stack.services.events.history() if e.type == "localization.result"]
    assert results == [{"request_id": "req-1", "accepted": True, "reason": None,
                        "state": "LOCALIZED", "source": "candidate", "cues": ["paint"]}]
    assert _robot_state(stack)["state"] == "LOCALIZED"
    assert stack.services.localization.autonomy_allowed()


def test_fleet_suspect_reaches_the_robot(stack):
    robot_id = _localize_through_fleet(stack)
    assert _fleet_call(stack, robot_id,
                       lambda client: client.localization_suspect("fleet_monitor")) == {
        "accepted": True}
    [raw] = stack.sent["suspect"]
    robot = stack.robot
    robot.now += 0.1
    _relay(stack.services, robot.wire(robot.core.on_suspect(robot.now, json.loads(raw))))
    status = _robot_state(stack)
    assert status["state"] == "SUSPECT" and status["reason"] == "fleet_monitor"
    assert not stack.services.localization.autonomy_allowed()


def test_legacy_initialpose_becomes_a_human_decision_the_robot_accepts(stack):
    _to_candidates(stack)
    resp = stack.client.post("/api/v1/localization/initialpose", headers=OPERATOR,
                             json={"x": 0.5, "y": 0.25, "yaw": 1.0})
    assert resp.status_code == 200 and resp.json() == {"accepted": True}
    [raw] = stack.sent["decision"]
    robot = stack.robot
    topics = robot.wire(robot.core.on_decision(robot.now, json.loads(raw)))
    assert "result" not in topics, topics.get("result")
    [injection] = robot.injected
    assert injection.pose == (0.5, 0.25, 1.0) and injection.source == "human"


# --- D-395 S1 finding 6: which clock each localization time runs on ------------------
#
# The robot node stamps everything on its node (ROS) clock: sim seconds under
# `use_sim_time`, system (epoch) time on the device. CORE's bridge has two clocks:
# the ROS clock of its own node (same setting, so the robot's clock) and the line
# clock (`traffic_gate.line_clock`: the ROS clock under use_sim_time, else
# `time.monotonic`). The stale window runs on the line clock; `received_s` must run
# on the ROS clock, because the robot counts its ttl from it.

#: (robot ROS clock at start, CORE line clock at start) per setup.
_SETUPS = {"sim": (10.0, None), "device": (1.79e9, 5000.0)}


@pytest.fixture(params=sorted(_SETUPS))
def clocked(stack, request):
    robot_now, mono = _SETUPS[request.param]
    stack.robot.now = robot_now
    line = SimpleNamespace(now=mono)
    # ros_bridge: loc.clock = the node ROS clock; loc.bind_clock(line_clock).
    stack.services.localization.clock = lambda: stack.robot.now
    if mono is None:                       # use_sim_time: the line clock is the ROS clock
        stack.services.localization.bind_clock(lambda: stack.robot.now)
    else:
        stack.services.localization.bind_clock(lambda: line.now)
    stack.line = line
    return stack


def _advance(stack, seconds: float) -> None:
    stack.robot.now += seconds
    if stack.line.now is not None:
        stack.line.now += seconds


def test_received_s_is_within_the_robots_bad_receipt_rule(clocked):
    from control.loc_assist import RECEIPT_AHEAD_S
    _to_candidates(clocked)
    resp = clocked.client.post("/api/v1/localization/initialpose", headers=OPERATOR,
                               json={"x": 0.5, "y": 0.25, "yaw": 1.0})
    assert resp.status_code == 200
    [raw] = clocked.sent["decision"]
    payload = json.loads(raw)
    robot = clocked.robot
    assert payload["received_s"] - robot.now <= RECEIPT_AHEAD_S
    topics = robot.wire(robot.core.on_decision(robot.now, payload))
    assert "result" not in topics, topics.get("result")
    assert [i.source for i in robot.injected] == ["human"]


def test_a_receipt_on_the_device_line_clock_would_be_refused(stack):
    """Why `received_s` is not the line clock: monotonic is not the robot's epoch clock."""
    robot_now, mono = _SETUPS["device"]
    stack.robot.now = robot_now
    _to_candidates(stack)
    stack.services.localization.clock = lambda: mono
    stack.client.post("/api/v1/localization/initialpose", headers=OPERATOR,
                      json={"x": 0.5, "y": 0.25, "yaw": 1.0})
    [raw] = stack.sent["decision"]
    robot = stack.robot
    topics = robot.wire(robot.core.on_decision(robot.now, json.loads(raw)))
    [result] = [json.loads(r) for r in topics["result"]]
    assert result["accepted"] is False and robot.injected == []


def test_the_stale_window_runs_on_the_line_clock(clocked):
    _localize_through_fleet(clocked)
    robot = clocked.robot
    _advance(clocked, 0.5)                 # the robot's state cadence: one heartbeat
    heartbeat = robot.wire(robot.core.tick(robot.now))
    assert heartbeat.get("state"), "the robot re-publishes its state on its own clock"
    _relay(clocked.services, heartbeat)
    status = clocked.services.localization.status
    _advance(clocked, 2.9)
    assert status().state.value == "LOCALIZED"
    _advance(clocked, 0.2)
    assert status().reason == "state_stale"


def test_the_bridge_binds_the_line_clock_and_stamps_receipts_on_the_ros_clock():
    import ast
    source = (Path(__file__).resolve().parents[1] / "core" / "bridge" / "ros_bridge.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    binds = [ast.unparse(n.args[0]) for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "bind_clock"
             and ast.unparse(n.func.value) == "loc"]
    assert binds == ["self._line_clock"]
    stamps = [ast.unparse(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign)
              and [ast.unparse(t) for t in n.targets] == ["loc.clock"]]
    assert stamps == ["lambda: self._node.get_clock().now().nanoseconds / 1000000000.0"]


def test_the_map_pose_freshness_behind_pose_frame_runs_on_the_line_clock():
    """The 2 s map-pose TTL decides `pose_frame` (and so autonomy); the state timer and
    the TF it reads move at sim rate, so the TTL must too."""
    import ast
    source = (Path(__file__).resolve().parents[1] / "core" / "bridge" / "ros_bridge.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    stamps = [ast.unparse(n.value) for n in ast.walk(tree)
              if (isinstance(n, ast.Assign) and "self._map_pose_ts" in map(ast.unparse, n.targets))
              or (isinstance(n, ast.AnnAssign) and ast.unparse(n.target) == "self._map_pose_ts")]
    assert stamps == ["float('-inf')", "self._line_clock()"]
    checks = [ast.unparse(n.args[1]) for n in ast.walk(tree) if isinstance(n, ast.Call)
              and ast.unparse(n.func) == "odometry.odom_owns_pose"]
    assert checks == ["self._line_clock()", "self._line_clock()"]
    from core.bridge.odometry import odom_owns_pose
    assert odom_owns_pose(float("-inf"), 0.0)       # sim second 0: no map pose seen yet


def test_fleet_mission_runs_in_core_and_the_robot_searches_after_it(stack):
    """P2-7: C asks B for a rotate; B drives and ends it; A searches again after the end."""
    from fleet.swarm.transport import RobotApiError

    _to_candidates(stack)
    services, robot = stack.services, stack.robot
    mission = services.loc_mission
    published = []
    mission.publish = lambda body: published.append(json.dumps(body))   # as ros_bridge does
    clock = SimpleNamespace(now=100.0)
    mission._clock = lambda: clock.now
    sample = {"ranges": [2.0] * 360, "angle_min": 0.0, "angle_max": 6.2657,
              "range_min": 0.05, "range_max": 8.0}
    mission.observe_scan(sample)
    mission.observe_odom(0.0, 0.0, 0.0)
    robot_id = services.localization.candidates().robot_id

    started = _fleet_call(stack, robot_id, lambda client: client.localization_mission(
        "rotate_in_place", max_distance_m=0.0, max_time_s=30.0))
    assert started["state"] == "running"
    with pytest.raises(RobotApiError) as refused:
        _fleet_call(stack, robot_id, lambda client: client.localization_mission(
            "to_square", max_distance_m=1.0, max_time_s=60.0, target={"square": [0.86, -0.52]}))
    assert refused.value.status == 409 and refused.value.code == "unsupported"

    robot.core.on_mission(robot.now, json.loads(published[0]))
    assert not robot.core.search_due(robot.now, (0.0, 0.0, 0.0))     # moving: no search
    yaw = 0.0
    for _ in range(45):
        clock.now += 0.05
        yaw += 0.15
        mission.observe_odom(0.0, 0.0, yaw)
        mission.observe_scan(sample)
        mission.tick()
    assert mission.status() == {"kind": "rotate_in_place", "state": "done", "reason": "done"}
    robot.core.on_mission(robot.now, json.loads(published[-1]))
    # S1 re-run R3: the search also waits until the robot has stood still for 0.5 s.
    for dt in (0.0, 0.3, 0.6):
        robot.core.on_twist(robot.now + dt, 0.0, 0.0)
    assert robot.core.search_due(robot.now + 0.6, (0.0, 0.0, 0.1))   # fresh candidates now
