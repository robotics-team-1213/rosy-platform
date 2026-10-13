"""D-24 amendment (2026-10-04): what may wake a sleeping robot, and what may not.

Three defects found on the live 9dfk STANDBY run are pinned here:

* (a) presence noise — invalid samples and hysteresis-band samples did not break
  the "consecutive" count, so two stray echoes minutes apart woke the robot;
* (b) the battery alert woke on every voltage sample below WARNING and pinned
  the robot ACTIVE (main already wakes only when the alert level changes; the
  cases here pin that rule);
* (c) "command" was implicit. It is now an explicit `on_command(source)`, fed by
  accepted command REST calls (table in core_api_web.api.command_activity) and a
  nonzero final cmd_vel. GET / telemetry / WS subscriptions never count.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from core_api_web.api.app import create_app
from core_api_web.api.command_activity import COMMAND_ROUTES, command_source
from core_common.profile import RobotProfile, robot_config_dir
from core_common.protocol.schemas import PowerMode
from core.services import CoreServices
from core_features.power.manager import PowerConfig, PowerManager, PresenceConfig

CONFIG_DIR = Path(__file__).resolve().parents[4] / "contracts" / "foundation" / "config"
NAN = float("nan")
INF = float("inf")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _standby_manager(clock: Clock) -> PowerManager:
    # Explicit dwell: main's defaults are 600 s / 1800 s; the cases only need "asleep".
    mgr = PowerManager(PowerConfig(idle_after_s=60.0, standby_after_s=300.0,
                                   presence=PresenceConfig()), clock=clock)
    clock.now += 400.0
    mgr.tick()
    assert mgr.mode == PowerMode.STANDBY
    return mgr


def _feed(mgr: PowerManager, clock: Clock, samples) -> None:
    """samples: (dt_before_s, range_m) pairs, fed through on_range."""
    for dt, range_m in samples:
        clock.now += dt
        mgr.on_range(range_m)


def _every(period_s: float, range_m: float, n: int):
    return [(period_s, range_m)] * n


# --- (a) presence -------------------------------------------------------------

NOISE_MUST_NOT_WAKE = {
    # The 9dfk case: one echo, then minutes of no-echo (inf), then another echo.
    "two echoes minutes apart, dropouts between": [
        (0.5, 0.20), *_every(0.5, INF, 240), (0.5, 0.20), *_every(0.5, INF, 10)],
    "two echoes minutes apart, nothing between": [(0.5, 0.20), (180.0, 0.20)],
    "echoes separated by hysteresis-band samples": [
        (0.5, 0.20), (0.5, 0.30), (0.5, 0.20), (0.5, 0.30), (0.5, 0.20), (0.5, 0.30)],
    "echoes separated by NaN": [(0.05, 0.20), (0.05, NAN)] * 10,
    "short burst at 20 Hz (0.15 s)": [*_every(0.05, 0.20, 4), *_every(0.05, 1.5, 5)],
    "echoes slower than max_gap_s": _every(1.5, 0.20, 10),
    "far and out-of-range only": [*_every(0.5, 1.2, 20), *_every(0.5, 5.0, 20)],
}

APPROACH_MUST_WAKE = {
    "20 Hz, 0.5 s in front": (_every(0.05, 0.20, 11), "proximity"),
    "5 Hz (IDLE rate), 0.6 s": (_every(0.2, 0.20, 4), "proximity"),
    "2 Hz (STANDBY rate), two samples": (_every(0.5, 0.20, 2), "proximity"),
    "walk-in from far then stays": ([*_every(0.5, 1.0, 3), *_every(0.5, 0.40, 2),
                                     *_every(0.5, 0.20, 2)], "proximity"),
    "hand on the sensor": (_every(0.1, 0.03, 6), "contact"),
}


@pytest.mark.parametrize("samples", NOISE_MUST_NOT_WAKE.values(), ids=NOISE_MUST_NOT_WAKE.keys())
def test_presence_noise_does_not_wake(samples):
    clock = Clock()
    mgr = _standby_manager(clock)
    _feed(mgr, clock, samples)
    assert mgr.last_wake_reason is None
    assert mgr.info_visible() is False


@pytest.mark.parametrize("case", APPROACH_MUST_WAKE.values(), ids=APPROACH_MUST_WAKE.keys())
def test_real_approach_wakes(case):
    samples, reason = case
    clock = Clock()
    mgr = _standby_manager(clock)
    _feed(mgr, clock, samples)
    assert mgr.mode == PowerMode.ACTIVE
    assert mgr.last_wake_reason == reason


def test_dropout_does_not_release_a_held_presence():
    clock = Clock()
    mgr = _standby_manager(clock)
    _feed(mgr, clock, _every(0.1, 0.20, 6))
    _feed(mgr, clock, _every(0.1, NAN, 10))
    assert mgr.presence.value == "near"


# --- (b) battery edge ---------------------------------------------------------

@pytest.mark.parametrize("levels,wakes", [
    (["ok", "ok", "ok"], 0),
    (["ok", "warning", "warning", "warning", "warning"], 1),
    (["warning"] * 50, 1),
    (["ok", "warning", "critical", "critical"], 2),
    (["warning", "ok", "warning"], 2),                # a new crossing wakes again
])
def test_battery_alert_is_edge_triggered(levels, wakes):
    clock = Clock()
    mgr = PowerManager(PowerConfig(), clock=clock)
    seen = []

    class Bus:
        def publish(self, type_, **_):
            if type_ == "power.wake":
                seen.append(type_)

    mgr._events = Bus()
    for level in levels:
        mgr.on_battery_alert(level)
    assert len(seen) == wakes


def test_sustained_warning_no_longer_pins_active():
    clock = Clock()
    mgr = PowerManager(PowerConfig(), clock=clock)
    mgr.on_battery_alert("warning")
    for _ in range(400):              # one voltage sample a second for 400 s
        clock.now += 1.0
        mgr.on_battery_alert("warning")
        mgr.tick()
    assert mgr.mode == PowerMode.STANDBY


# --- (c) command --------------------------------------------------------------

def test_on_command_wakes_without_info_window():
    clock = Clock()
    mgr = _standby_manager(clock)
    mgr.on_command("teleop")
    assert mgr.mode == PowerMode.ACTIVE
    assert mgr.last_wake_reason == "command"
    assert mgr.info_visible() is False
    assert mgr.status().idle_seconds == 0.0


def test_on_command_while_active_keeps_previous_wake_reason():
    clock = Clock()
    mgr = PowerManager(PowerConfig(), clock=clock)
    mgr.on_command("teleop")
    assert mgr.last_wake_reason is None


COMMANDS = [
    ("POST", "/api/v1/teleop", "teleop"),
    ("POST", "/api/v1/mode", "mode"),
    ("POST", "/api/v1/navigation/goal", "navigation"),
    ("POST", "/api/v1/navigation/home", "navigation"),
    ("POST", "/api/v1/navigation/cancel", "navigation"),
    ("POST", "/api/v1/motion/rotate_to", "navigation"),
    ("POST", "/api/v1/localization/mission", "mission"),
    ("POST", "/api/v1/docking/dock", "docking"),
    ("PUT", "/api/v1/line-follow/mode", "line_follow"),
    ("POST", "/api/v1/swarm/follow", "fleet_task"),
    ("POST", "/api/v1/do", "intent"),
]

NOT_COMMANDS = [
    ("GET", "/api/v1/robot/state"),
    ("GET", "/api/v1/power"),
    ("GET", "/api/v1/teleop"),
    ("POST", "/api/v1/power/mode"),      # a sleep request must never count as activity
    ("POST", "/api/v1/power/wake"),      # handles its own wake (reason api)
    ("POST", "/api/v1/auth/pair"),
    ("POST", "/api/v1/waypoints"),
    ("PUT", "/api/v1/system/info"),
    ("GET", "/ws/state"),
    ("GET", "/api/v1/navigation/goal"),
]


@pytest.mark.parametrize("method,path,source", COMMANDS)
def test_command_routes(method, path, source):
    assert command_source(method, path) == source


@pytest.mark.parametrize("method,path", NOT_COMMANDS)
def test_non_command_routes(method, path):
    assert command_source(method, path) is None


def test_every_command_route_exists_in_the_app(client):
    api, _ = client
    import re
    routes = {(m.upper(), path) for path, ops in api.app.openapi()["paths"].items() for m in ops}
    for method, pattern, _source in COMMAND_ROUTES:
        assert any(m == method and re.fullmatch(pattern, p) for m, p in routes), pattern


@pytest.fixture
def client():
    config = yaml.safe_load((CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8"))
    dev_auth = yaml.safe_load((CONFIG_DIR / "rosy_dev_auth.yaml").read_text(encoding="utf-8"))
    config["auth"] = {**config["auth"], **dev_auth["auth"]}
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    caps = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    svc = CoreServices.build(config, profile, caps, Path(tempfile.mkdtemp()) / "waypoints.json")
    return TestClient(create_app(config, svc)), svc


OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


def test_accepted_rest_command_wakes(client):
    api, svc = client
    svc.power.request_mode(PowerMode.STANDBY, source="test")
    assert api.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert svc.power.mode == PowerMode.ACTIVE
    assert svc.power.last_wake_reason == "command"


def test_refused_command_does_not_wake(client):
    api, svc = client
    svc.power.request_mode(PowerMode.STANDBY, source="test")
    assert api.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=VIEWER).status_code == 403
    assert svc.power.mode == PowerMode.STANDBY


def test_reads_do_not_wake(client):
    api, svc = client
    svc.power.request_mode(PowerMode.STANDBY, source="test")
    for path in ("/api/v1/robot/state", "/api/v1/power"):
        assert api.get(path, headers=VIEWER).status_code == 200
    with api.websocket_connect("/ws/state") as ws:
        ws.send_json({"type": "auth", "token": "rosy-dev-viewer"})
        ws.receive_json()
    assert svc.power.mode == PowerMode.STANDBY


def test_operator_sleep_request_is_not_undone_by_its_own_answer(client):
    api, svc = client
    body = api.post("/api/v1/power/mode", json={"mode": "STANDBY"}, headers=OPERATOR).json()
    assert body["mode"] == "STANDBY"
    assert svc.power.mode == PowerMode.STANDBY
