"""SAF-003 wiring through CoreServices.build and the REST surface (D-419).

The monitor's rules are in src/runtime/services/test/test_fleet_loss.py; this file checks
that a real robot gets them: config validation, legacy policy values, the FleetAgent
link, REST goals carrying a Fleet correlation id, and `GET /safety/state`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
DEFAULTS = yaml.safe_load(
    (Path(__file__).resolve().parents[3] / "contracts" / "foundation" / "config"
     / "rosy_default.yaml").read_text(encoding="utf-8"))
FLEET = {"hub_url": "ws://127.0.0.1:1/ws/robots", "pairing_token": "pair-token"}


def _safety(**extra) -> dict:
    return {"safety": {**DEFAULTS["safety"], **extra}}


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Executor:
    def __init__(self) -> None:
        self.cancelled = 0

    def send_goal(self, spec, *, correlation_id=None):
        pass

    def cancel_goal(self):
        self.cancelled += 1


def test_safety_state_reports_an_unconfigured_fleet_link(core_client):
    tc, _svc = core_client()
    body = tc.get("/api/v1/safety/state", headers=VIEWER).json()
    assert body["fleet_loss_policy"] == "STOP"
    assert body["fleet_link"] == {
        "configured": False, "connected": False, "lost": False, "timeout_s": 5.0,
        "applied": None, "correlation_id": None, "disconnected_s": None, "held_goal": None}


@pytest.mark.parametrize("bad", [0, 0.5, 3.0, 3.9, 120, "fast"])
def test_out_of_range_timeout_fails_the_build_with_a_fleet_link(core_client, bad):
    with pytest.raises(ValueError, match="fleet_loss_timeout_s"):
        core_client(config_overrides={**_safety(fleet_loss_timeout_s=bad), "fleet": FLEET})


@pytest.mark.parametrize("override", [
    _safety(fleet_loss_timeout_s=0.5),
    {**_safety(fleet_loss_timeout_s=4.0), "fleet": {"heartbeat_reply_timeout_s": 3.0}},
    {"fleet": {"heartbeat_reply_timeout_s": 0.1}},
])
def test_robot_without_fleet_boots_on_bad_fleet_settings(core_client, caplog, override):
    """Round 3 MEDIUM 1 (ADR scope): no Fleet link, so a bad SAF-003/Fleet setting is a
    warning, never a failed boot."""
    import logging
    with caplog.at_level(logging.WARNING):
        _tc, svc = core_client(config_overrides=override)
    assert svc.fleet_agent.enabled is False
    assert svc.fleet_loss.status()["timeout_s"] == 5.0
    assert any("without a Fleet link" in r.getMessage() for r in caplog.records)


def test_timeout_shorter_than_heartbeat_plus_reply_deadline_fails_the_build(core_client):
    """4 s is in range, but with a 3 s reply deadline a healthy link can be silent for
    1 + 3 s; the build refuses rather than STOP on a healthy link."""
    with pytest.raises(ValueError, match="heartbeat_reply_timeout_s"):
        core_client(config_overrides={**_safety(fleet_loss_timeout_s=4.0),
                                      "fleet": {**FLEET, "heartbeat_reply_timeout_s": 3.0}})
    _tc, svc = core_client(config_overrides={**_safety(fleet_loss_timeout_s=5.0),
                                             "fleet": {**FLEET, "heartbeat_reply_timeout_s": 3.0}})
    assert svc.fleet_loss.freshness_s == pytest.approx(1.0 + 3.0 + 0.5)


def test_bad_reply_timeout_fails_the_build_with_a_fleet_link(core_client):
    with pytest.raises(ValueError, match="heartbeat_reply_timeout_s"):
        core_client(config_overrides={"fleet": {**FLEET, "heartbeat_reply_timeout_s": 0.1}})


@pytest.mark.parametrize("stored, live", [
    ("PANIC", "STOP"), ("CONTINUE_CURRENT_NAVIGATION", "CONTINUE"), ("hold", "HOLD")])
def test_stored_policy_is_normalised_at_startup(core_client, stored, live):
    _tc, svc = core_client(config_overrides=_safety(fleet_loss_policy=stored))
    assert svc.safety.fleet_loss_policy == live


def test_put_still_accepts_every_saf003_policy(core_client, tmp_path, monkeypatch):
    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", tmp_path / "rosy.yaml")
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    tc, svc = core_client()
    for policy, live in (("RETURN_HOME", "RETURN_HOME"), ("CONTINUE_CURRENT_NAVIGATION", "CONTINUE"),
                         ("HOLD", "HOLD"), ("STOP", "STOP")):
        reply = tc.put("/api/v1/safety/limits", json={"fleet_loss_policy": policy}, headers=ADMIN)
        assert reply.status_code == 200 and svc.safety.fleet_loss_policy == live
    assert tc.put("/api/v1/safety/limits", json={"fleet_loss_policy": "PANIC"},
                  headers=ADMIN).status_code == 400


def test_put_return_home_is_accepted_with_a_warning(core_client, tmp_path, monkeypatch):
    monkeypatch.setattr("core_common.config.LOCAL_CONFIG_PATH", tmp_path / "rosy.yaml")
    monkeypatch.delenv("ROSY_CONFIG", raising=False)
    tc, _svc = core_client()
    body = tc.put("/api/v1/safety/limits", json={"fleet_loss_policy": "RETURN_HOME"},
                  headers=ADMIN).json()
    assert body["fleet_loss_policy"] == "RETURN_HOME"
    assert "drives to __home__ at the same time" in body["warning"]
    stop = tc.put("/api/v1/safety/limits", json={"fleet_loss_policy": "STOP"}, headers=ADMIN).json()
    assert "warning" not in stop


def test_configured_is_fixed_at_build_so_a_stopped_agent_is_a_lost_link(core_client):
    """Review I1: a rejected hello or stop() flips `enabled`; the monitor must keep judging."""
    _tc, svc = core_client(config_overrides={"fleet": FLEET})
    svc.fleet_agent.stop()
    assert svc.fleet_agent.enabled is False
    assert svc.fleet_loss.status()["configured"] is True


class _Gate:
    def __init__(self) -> None:
        self.entered = 0

    def __enter__(self):
        self.entered += 1

    def __exit__(self, *exc):
        return False


def test_wiring_return_home_is_refused_when_not_localized():
    """M5: the RETURN_HOME closure goes through the D-395 gate and never calls home()."""
    from types import SimpleNamespace
    from core.fleet_loss_wiring import build_fleet_loss

    calls = []
    gate = _Gate()
    nav = SimpleNamespace(fleet_goal=lambda: None, cancel=lambda **_: True,
                          home=lambda source: calls.append(source))
    localization = SimpleNamespace(gate=gate, autonomy_allowed=lambda: False)
    safety = SimpleNamespace(fleet_loss_policy="RETURN_HOME")
    agent = SimpleNamespace(enabled=True, connected=True, last_rx=None,
                            reply_timeout_s=2.0, link_fresh_s=3.5)
    monitor = build_fleet_loss({"safety": {}}, events=None, fleet_agent=agent, nav=nav,
                               safety=safety, localization=localization)
    with pytest.raises(RuntimeError, match="LOCALIZED"):
        monitor._return_home()
    assert calls == [] and gate.entered == 1

    localization.autonomy_allowed = lambda: True
    monitor._return_home()
    assert calls == ["fleet_loss"] and gate.entered == 2


def test_power_timer_ticks_the_monitor_inside_a_guard():
    """M5/M2, structural only (test_bridge_timers forbids driving ticks): `_tick_power`
    calls `fleet_loss.tick()` inside `try/except Exception`."""
    import ast
    source = (Path(__file__).resolve().parents[1] / "core" / "bridge" / "ros_bridge.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    func = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "_tick_power")
    guarded = [
        node for node in ast.walk(func) if isinstance(node, ast.Try)
        and any(isinstance(h.type, ast.Name) and h.type.id == "Exception" for h in node.handlers)
        and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "tick" and "fleet_loss" in ast.unparse(call.func)
                for stmt in node.body for call in ast.walk(stmt))
    ]
    assert len(guarded) == 1


def test_rest_fleet_goal_is_stopped_after_the_link_drops(core_client, monkeypatch):
    """No TestClient context: the lifespan (and so the agent's socket task) never starts,
    so the test owns `connected`."""
    tc, svc = core_client(config_overrides={"fleet": FLEET})
    # Same bypass as test_api's correlation test: the core runtime mode withholds goals.
    monkeypatch.setattr("core_api_web.api.v1.navigation.require_kept", lambda *_: None)
    assert svc.fleet_agent.enabled and svc.fleet_loss is not None
    executor = Executor()
    svc.nav.executor = executor
    clock = Clock()
    svc.fleet_loss.clock = clock
    svc.fleet_agent.connected = True
    svc.fleet_agent.last_rx = clock.now      # the agent's monotonic stamp, on the test clock
    svc.fleet_loss.tick()

    reply = tc.post("/api/v1/navigation/goal",
                    json={"x": 1.0, "y": 0.5, "yaw": 0.0, "correlation_id": "attempt-7"},
                    headers=OPERATOR)
    assert reply.status_code in (200, 202), reply.text
    svc.nav.on_goal_accepted()

    svc.fleet_agent.connected = False
    svc.fleet_loss.tick()
    clock.now += 4.9
    svc.fleet_loss.tick()
    assert executor.cancelled == 0           # timeout counts from last_rx: 5 s by default
    clock.now += 0.2
    svc.fleet_loss.tick()

    assert executor.cancelled == 1
    events = [ev for ev in svc.events.history() if ev.type == "safety.fleet_lost"]
    assert len(events) == 1 and events[0].data["correlation_id"] == "attempt-7"
    body = tc.get("/api/v1/safety/state", headers=VIEWER).json()
    assert body["fleet_link"]["lost"] and body["fleet_link"]["applied"] == "STOP"
