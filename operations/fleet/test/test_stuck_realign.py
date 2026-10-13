"""D-622 standalone REALIGN: coherent map geometry, finite budgets and CORE transport."""
import asyncio
import json
import math

import httpx
import pytest

from fleet.stuck.realign import RealignConfig, select
from fleet.stuck.resolver import Answer, ResolverConfig, StuckResolver
from fleet.stuck.loop import StuckResolverLoop
from fleet.stuck.board import LineStuckBoard
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient


def config():
    return RealignConfig.from_mapping({"realign_robots": ["r1"], "realign_areas": [
        {"map_revision": "rev1", "polygon": [[-1,-1],[1,-1],[1,1],[-1,1]]}]})


def row():
    return {"robot_id": "r1", "online": True,
        "capabilities": {"controls":{"items":[{"kind":"base_velocity", "robot_kind":"pinky_pro",
                                                 "stuck_realign":["PIVOT", "KTURN"]}]}},
        "state": {"safety": {"estop": False},
        "line_follow": {"mode": "CAMERA_LINE", "crosswalk": None, "stuck": {
            "stuck_id": "s1", "cause": "no_motion", "phase": "CONSOLE_ONLY",
            "local_enabled": True, "decisions": ["WAIT", "REALIGN"]}}},
        "realign_evidence": {"status": "heading_compared", "turn_deg": -45.,
            "pose_stamp": 100., "map_version": "rev1", "map_id": "site", "edge_id": "road",
            "x": 0., "y": 0., "yaw": 0., "u_m": .018, "offset_m": 0., "turn_spot": True},
        "clearance_evidence": {"stuck_id": "s1", "inquiry_observed_at": 10.,
            "rear_state": "clear", "rear_clearance_m": .3,
            "inquiry": {"observations": {"scan_age_s": .02, "geometry_known": True}}}}


def test_known_turn_spot_and_continuous_body_sweep_produce_pivot():
    candidate, why = select(row(), [row()], config(), now=10.1, attempt=1)
    assert why is None and candidate["kind"] == "PIVOT"
    assert candidate["angle_rad"] == pytest.approx(-math.pi/4)
    assert candidate["turn_spot"] is True and candidate["pose_stamp"] == 100.


def test_rear_verified_kturn_has_existing_core_limits():
    r = row(); r["realign_evidence"]["turn_spot"] = False
    candidate, why = select(r, [r], config(), now=10.1, attempt=1)
    assert why is None and candidate["kind"] == "KTURN"
    assert 0 < candidate["back_m"] <= .08
    assert candidate["back_radius_m"] >= .05 and candidate["fwd_radius_m"] >= .02


@pytest.mark.parametrize("change", ["trip", "stale", "unknown_rear", "wrong_map", "angle", "nan", "peer"])
def test_unknown_or_unsafe_evidence_never_selects_motion(change):
    r = row(); r["realign_evidence"]["turn_spot"] = False
    rows = [r]
    if change == "trip": r["trip"] = True
    if change == "stale": r["clearance_evidence"]["inquiry_observed_at"] = 8.
    if change == "unknown_rear": r["clearance_evidence"]["rear_state"] = "unknown"
    if change == "wrong_map": r["realign_evidence"]["map_version"] = "rev2"
    if change == "angle": r["realign_evidence"]["turn_deg"] = 91.
    if change == "nan": r["realign_evidence"]["u_m"] = float("nan")
    if change == "peer": rows.append({"robot_id": "r2", "online": True})
    candidate, why = select(r, rows, config(), now=10.1, attempt=1)
    assert candidate is None and why


def test_default_disabled_and_exhaustion_are_holds():
    assert select(row(), [row()], RealignConfig(), now=10.1, attempt=1)[0] is None
    assert select(row(), [row()], config(), now=10.1, attempt=3)[0] is None


def test_real_active_map_integer_version_is_supported_and_body_is_required():
    r = row(); r["realign_evidence"]["map_version"] = 5
    cfg = RealignConfig.from_mapping({"realign_robots":["r1"], "realign_areas":[
        {"map_revision":5, "polygon":[[-1,-1],[1,-1],[1,1],[-1,1]]}]})
    assert select(r, [r], cfg, now=10.1, attempt=1)[0] is not None
    r["capabilities"] = None
    assert select(r, [r], cfg, now=10.1, attempt=1)[0] is None


@pytest.mark.parametrize("caps", ["malformed", {"controls":"bad"},
    {"controls":{"items":None}}, {"controls":{"items":[{"kind":"base_velocity",
        "robot_kind":"pinky_pro", "stuck_realign":"PIVOT"}]}}])
def test_malformed_capabilities_fail_closed(caps):
    r = row(); r["capabilities"] = caps
    assert select(r, [r], config(), now=10.1, attempt=1)[0] is None


def test_body_near_area_edge_cannot_turn_even_with_turn_spot():
    r = row(); r["realign_evidence"]["x"] = .95
    assert select(r, [r], config(), now=10.1, attempt=1)[0] is None


@pytest.mark.parametrize("raw", [{"realign_robots": "r1"}, {"realign_areas": [{}]},
    {"realign_areas": [{"map_revision":"r", "polygon":[[0,0],[1,0],[.3,.2],[0,1]]}]}])
def test_configuration_rejects_malformed_or_concave_areas(raw):
    with pytest.raises(ValueError): RealignConfig.from_mapping(raw)


def test_resolver_and_transport_preserve_realignment_body():
    r = row()
    resolver = StuckResolver(ResolverConfig(), realign=config(), wall=lambda: 10.1)
    actions = resolver.step(1., [r])
    assert len(actions) == 1 and isinstance(actions[0], Answer)
    answer = actions[0]
    assert answer.decision == "REALIGN" and answer.realign["attempt"] == 1
    seen = []
    def handler(request):
        seen.append(json.loads(request.content)); return httpx.Response(200, json={"outcome":"realign"})
    client = HttpRobotClient(RobotEndpoint("r1", "http://robot", "op-token"),
                             http=httpx.AsyncClient(base_url="http://robot", transport=httpx.MockTransport(handler)))
    asyncio.run(client.line_stuck_decision("s1", answer.decision, realign=answer.realign))
    assert seen[0] == {"stuck_id":"s1", "decision":"REALIGN", "realign":answer.realign}


def test_loop_forwards_realignment_and_unknown_outcome_never_replays():
    r = row()
    resolver = StuckResolver(ResolverConfig(), realign=config(), wall=lambda: 10.1)
    answer = resolver.step(1., [r])[0]
    seen = []
    class Client:
        async def line_stuck_decision(self, stuck_id, decision, **extra):
            seen.append(extra)
            raise httpx.ReadTimeout("response lost after request")
    async def snapshot(): return {"robots": [r]}
    board = LineStuckBoard(clock=lambda: 1.)
    board.observe([r])
    loop = StuckResolverLoop(snapshot, board, resolver, clients=lambda: {"r1":Client()})
    asyncio.run(loop._answer(answer, 1.))
    assert seen == [{"realign":answer.realign}]
    assert resolver.step(2., [r]) == []
    assert board.resolver_note("r1", "s1")["tier"] == "human"


def test_cli_default_and_opt_in_configuration(tmp_path):
    from types import SimpleNamespace
    from fleet.cli import _realign_config
    args = SimpleNamespace(site_config=None)
    assert _realign_config(args) == RealignConfig()
    path = tmp_path / "site.yaml"
    path.write_text("fleet:\n  stuck_resolver:\n    realign_robots: [r1]\n", encoding="utf-8")
    args.site_config = path
    assert _realign_config(args).robots == frozenset({"r1"})


def test_autonomous_robot_does_not_reopen_a_held_realignment_on_the_same_stuck():
    r = row()
    r["state"]["line_follow"]["stuck"]["phase"] = "ASKING"
    r["clearance_evidence"]["inquiry_observed_at"] = 8.
    resolver = StuckResolver(ResolverConfig(), realign=config(), wall=lambda: 10.1)
    resolver.autonomous_robots = frozenset({"r1"})
    held = resolver.step(1., [r])[0]
    assert (held.decision, held.escalate) == ("WAIT", "realign_hold:clearance_stale")
    resolver.sent(held, 1.)
    assert resolver.result(held, code=None).reason == "realign_hold:clearance_stale"
    r["clearance_evidence"]["inquiry_observed_at"] = 10.
    assert select(r, [r], config(), now=10.1, attempt=1)[0] is not None
    assert resolver.step(2., [r]) == [] and resolver.step(3., [r]) == []
