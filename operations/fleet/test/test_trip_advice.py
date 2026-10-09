"""D-551 6: Fleet sends each trip robot the signal ahead as display-only advice, after the authority."""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace

from core_common.protocol.line_advice import LineAdviceRequest
from fleet.server.console_view import trip_caps
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_ports import TripConfig
from fleet.server.trip_runner import TripRunner
from fleet.traffic.config import _traffic_signal_advice
from fleet.traffic.trip_advice import FLEET_EPOCH, AdviceSender
from test_lane_traffic import _trip
from test_routing import demo_site
from test_trip_authority import AUTH, AuthFleet

AHEAD = {"robot_id": "a", "signal_id": "sig", "approach": "ring_in", "distance_m": 0.8, "may_enter": False,
         "lamp": "red", "left_s": 3.0, "green_in_s": 4.5, "exact": True, "virtual": True, "advisory": True}


class Port:
    def __init__(self, answer=None, error=None):
        self.bodies, self.answer, self.error = [], answer or {"accepted": True}, error

    async def send_advice(self, robot_id, body):
        self.bodies.append(body)
        if self.error is not None:
            raise self.error
        return self.answer


class Traffic:
    def __init__(self, ahead=AHEAD):
        self.ahead, self.rows = ahead, [{"robot_id": "a"}]

    def signal_ahead(self, robot_id):
        return self.ahead

    def view(self):
        return {"robots": self.rows}


def _live(caps=True, stamp=5.0, trip="t", route_rev=0, waiting=()):
    return SimpleNamespace(
        traffic={"front_d_m": 1.0, "pose_stamp": stamp, "waiting_for": list(waiting)}, route_rev=route_rev, open=True,
        view={"robot_id": "a", "trip_id": trip, "map_version": 3, "caps": {"line_follow_advice": caps}})


def _run(sender, live, n=1, slow=frozenset()):
    async def go():
        for _ in range(n):
            sender.period([live], slow)
            await asyncio.gather(*[f for f in sender._inflight.values() if not f.done()])
    asyncio.run(go())


def test_gate_off_by_config_or_capability_sends_nothing():
    for enabled, caps in ((False, True), (True, False)):
        port = Port()
        _run(AdviceSender(port, Traffic(), enabled), _live(caps=caps), n=2)
        assert port.bodies == []


def test_the_capability_is_read_from_the_controls_descriptor():
    item = {"kind": "base_velocity", "robot_kind": "pinky_pro", "drive_modes": ["lane"], "trip_max_linear": 0.1}
    assert trip_caps({"controls": {"items": [item]}}).line_follow_advice is False
    item["line_follow_advice"] = True
    assert trip_caps({"controls": {"items": [item]}}).line_follow_advice is True


def test_site_config_key_defaults_off(tmp_path):
    path = tmp_path / "site.yaml"
    path.write_text("fleet:\n  traffic:\n    authority: true\n", encoding="utf-8")
    assert _traffic_signal_advice(SimpleNamespace(site_config=path)) is False
    path.write_text("fleet:\n  traffic:\n    signal_advice: true\n", encoding="utf-8")
    assert _traffic_signal_advice(SimpleNamespace(site_config=path)) is True


def test_payload_validates_and_seq_counts_per_leg():
    port, traffic = Port(), Traffic()
    sender = AdviceSender(port, traffic, True)
    live = _live()
    _run(sender, live, n=3)
    live.route_rev = 1  # an operator-confirmed replan is a new leg
    _run(sender, live, n=2)
    assert [(b["leg_id"], b["seq"]) for b in port.bodies] == [("t:0", 0), ("t:0", 1), ("t:0", 2), ("t:1", 0),
                                                              ("t:1", 1)]
    assert len({b["advice_id"] for b in port.bodies}) == 5
    for body in port.bodies:
        LineAdviceRequest.model_validate(body)
    body = port.bodies[0]
    assert body["pose_stamp"] == 5.0 and body["ttl_s"] == 2.0 and body["map_version"] == 3
    assert body["signal"]["stop_m"] == 0.8 and body["signal"]["lamp"] == "red"
    assert traffic.rows[0]["advice"]["sent_seq"] == 0 and traffic.rows[0]["advice"]["accepted"] is True


def test_fleet_epoch_is_one_per_process():
    ports = Port(), Port()
    for port in ports:
        _run(AdviceSender(port, Traffic(), True), _live())
    assert ports[0].bodies[0]["fleet_epoch"] == ports[1].bodies[0]["fleet_epoch"] == FLEET_EPOCH


def test_unknown_lamp_is_null_and_one_null_follows_a_signal():
    traffic, port = Traffic({**AHEAD, "lamp": "unknown"}), Port()
    sender = AdviceSender(port, traffic, True)
    _run(sender, _live(), n=2)
    assert port.bodies == []  # nothing was ever shown: nothing to clear
    traffic.ahead = AHEAD
    _run(sender, _live())
    traffic.ahead = {**AHEAD, "lamp": None}
    _run(sender, _live(), n=3)
    assert [b["signal"] is None for b in port.bodies] == [False, True]
    LineAdviceRequest.model_validate(port.bodies[1])


def test_no_stamp_pose_jump_or_slow_authority_sends_nothing():
    port = Port()
    sender = AdviceSender(port, Traffic(), True)
    _run(sender, _live(stamp=None))
    _run(sender, _live(waiting=["pose_jump"]))
    _run(sender, _live(), slow={"a"})
    assert port.bodies == []


def test_a_failure_is_recorded_and_swallowed():
    traffic = Traffic()
    sender = AdviceSender(Port(error=TimeoutError()), traffic, True)
    _run(sender, _live(), n=2)
    assert traffic.rows[0]["advice"]["accepted"] is False and traffic.rows[0]["advice"]["reason"] == "TimeoutError"


class SlowAdvice(AuthFleet):
    async def send_advice(self, robot_id, body):
        await asyncio.sleep(5)


class BadAdvice(AuthFleet):
    async def send_advice(self, robot_id, body):
        raise RuntimeError("robot down")


def test_advice_failure_never_affects_the_authority(monkeypatch):
    for cls in (SlowAdvice, BadAdvice):
        caps = {"a": dataclasses.replace(AUTH, line_follow_advice=True)}
        fleet = cls(tuple(caps), caps)
        store = SiteMapStore(None, clock=lambda: fleet.now)
        store.import_if_empty(demo_site(), source="test")
        runner = TripRunner(store=store, routing_config=store.routing_config, caps=fleet.caps_for, poses=fleet,
                            junction=fleet, goal=fleet.goal, cancel_goal=fleet.cancel_goal,
                            blocked=lambda: fleet.blocked, clock=lambda: fleet.now, config=TripConfig(),
                            authority=True, signal_advice=True)
        monkeypatch.setattr(runner.traffic, "signal_ahead", lambda robot_id: AHEAD)
        _trip(runner, store, fleet, "a", "east:fwd", 0.3)
        assert runner.view("a")["caps"]["line_follow_advice"] is True

        async def go():
            for _ in range(3):
                fleet.advance(0.5)
                await runner.tick()
                await asyncio.gather(*[f for f in runner.authority._inflight.values() if not f.done()])
        asyncio.run(go())
        assert len(fleet.bodies["a"]) == 3  # an authority every period, advice hung or failing
        assert runner.advice._inflight  # the advice was tried
