"""D-511 rev 1: the Fleet return loop — classify, debounce, crosswalk hint, the cue to CORE."""

import asyncio
import math

from fleet.localization.lane_compliance import (OFF_LANE, OFF_MAP, ON_LANE, ON_LINE, UNSEEN, WRONG_WAY,
                                                LaneComplianceConfig, ReturnTracker, classify)
from fleet.localization.map_pose import MapPose
from fleet.routing.graph import build_graph
from fleet.server.lane_compliance_service import LaneComplianceMonitor

WW = LaneComplianceConfig(wrong_way=True)
from fleet.site_map import SiteMap

# One-way lane A(0,0) -> B(2,0), 0.185 m wide like map_v2_fleet; a crosswalk at x 1.0-1.12.
SITE = SiteMap.model_validate({
    "places": [{"id": "A", "name": "A", "x": 0, "y": 0, "kind": "junction"},
               {"id": "B", "name": "B", "x": 2, "y": 0, "kind": "junction"}],
    "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [2, 0]], "width_m": 0.185,
               "speed_cap_mps": 0.2}],
    "crosswalks": [{"id": "cw", "revision": "t", "polygon": [[1.0, -0.1], [1.12, -0.1], [1.12, 0.1], [1.0, 0.1]]}]})
GRAPH = build_graph(SITE)
CW = [(c.id, [tuple(p) for p in c.polygon]) for c in SITE.crosswalks]


def test_classify_states_and_side():
    assert classify(0.5, 0.0, 0.0, 0.0, GRAPH, CW).state == ON_LANE
    line = classify(0.5, 0.06, 0.0, 0.0, GRAPH, CW)
    assert line.state == ON_LINE and line.side == "right"       # left of the lane: centre is right
    off = classify(0.5, -0.3, 0.0, 0.0, GRAPH, CW, LaneComplianceConfig(off_map_pad_m=0.5))
    assert off.state == OFF_LANE and off.side == "left" and off.bearing_deg > 0
    assert classify(5.0, 0.0, 0.0, 0.0, GRAPH, CW).state == OFF_MAP
    assert classify(0.5, 0.0, math.pi, math.pi, GRAPH, CW).state == ON_LANE      # off by default
    assert classify(0.5, 0.0, math.pi, math.pi, GRAPH, CW, WW).state == WRONG_WAY
    # D-587 yaw wins over motion: a body turned back is wrong way; turned along is not
    assert classify(0.5, 0.0, math.pi, 0.0, GRAPH, CW, WW).state == WRONG_WAY
    assert classify(0.5, 0.0, 0.0, math.pi, GRAPH, CW, WW).state == ON_LANE
    guide = classify(0.5, 0.0, 0.0, None, GRAPH, CW).guide
    assert guide["next_place_id"] == "B" and abs(guide["to_end_m"] - 1.5) < 1e-6 and guide["ring"] is False


def test_crosswalk_is_on_lane_and_hinted_ahead():
    ahead = classify(0.7, 0.0, 0.0, 0.0, GRAPH, CW).crosswalk_ahead
    assert ahead["id"] == "cw" and abs(ahead["near_m"] - 0.3) < 0.02 and abs(ahead["far_m"] - 0.42) < 0.02
    assert ahead["source"] == "fleet_map" and ahead["uncertainty_m"] > 0
    inside = classify(1.06, 0.07, 0.0, 0.0, GRAPH, CW)      # off-centre inside a crosswalk
    assert inside.state == ON_LANE and inside.crosswalk == "cw"
    assert classify(0.7, 0.0, math.pi, math.pi, GRAPH, CW, WW).crosswalk_ahead is None  # wrong way: no hint


def test_tracker_debounces_and_wrong_way_needs_travel():
    tr = ReturnTracker(LaneComplianceConfig(return_persist_s=1.0, wrong_way_min_m=0.1, wrong_way=True))
    tr.update(0.0, 0.5, 0.0, None, GRAPH, CW)
    assert tr.state == UNSEEN
    tr.update(1.0, 0.5, 0.0, None, GRAPH, CW)
    assert tr.state == ON_LANE
    tr.update(1.5, 0.5, -0.3, None, GRAPH, CW)                # one off sample: not yet
    tr.update(1.8, 0.5, 0.0, None, GRAPH, CW)
    assert tr.state == ON_LANE
    for k, x in enumerate((1.6, 1.5, 1.4, 1.3, 1.2)):        # drive back along the lane
        tr.update(3.0 + k * 0.5, x, 0.0, None, GRAPH, CW)
    assert tr.state == WRONG_WAY
    tr.update(9.0, None, None, None, GRAPH, CW, moving=True)  # not seen while moving
    tr.update(12.5, None, None, None, GRAPH, CW, moving=True)
    assert tr.state == OFF_MAP


class Poses:
    def __init__(self, pose):
        self.pose = pose

    def moved(self, *_):
        return False

    async def refresh(self, *_a, **_k):
        return None

    def arbitrated_pose(self, _):
        return self.pose


class Maps:
    def active(self):
        return (3, SITE, GRAPH, None)


class Client:
    def __init__(self):
        self.sent = []

    async def line_follow_lane_cue(self, body):
        self.sent.append(body)
        return {"accepted": True}


def test_monitor_sends_cue_off_lane_and_clears_once():
    clock = [100.0]
    client = Client()
    poses = Poses(MapPose(0.5, -0.3, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, map_id="m", odom_stamp=5.0))
    monitor = LaneComplianceMonitor(lambda: ["r1"], poses=poses, site_maps=Maps(),
                                    config=LaneComplianceConfig(off_map_pad_m=0.5),
                                    wall=lambda: clock[0], clients=lambda: {"r1": client})
    for _ in range(4):
        asyncio.run(monitor.tick())
        clock[0] += 0.5
    assert monitor.view("r1")["return"]["state"] == OFF_LANE
    assert client.sent and client.sent[-1]["state"] == OFF_LANE and client.sent[-1]["side"] == "left"
    assert client.sent[-1]["pose_stamp"] == 5.0
    assert client.sent[-1]["ttl_s"] <= 1.0 and "guide" in client.sent[-1] and "crosswalk_ahead" not in client.sent[-1]
    poses.pose = MapPose(0.3, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, map_id="m", odom_stamp=6.0)
    for _ in range(6):
        asyncio.run(monitor.tick())
        clock[0] += 0.5
    states = [b["state"] for b in client.sent]
    assert states.count(ON_LANE) == 1 and states[-1] == ON_LANE


def test_resolver_never_resumes_at_a_mapped_crosswalk_it_waits_for_a_human():
    # XW removed after independent Safety-Review 2026-10-10: RESUME at a crosswalk could drive across with
    # no look for people (CORE gate off) or override a "person present" hold. WAIT + a human instead.
    from fleet.stuck.resolver import Answer, ResolverConfig, StuckResolver
    for cause in ("no_motion", "lane_lost"):
        for trip in (False, True):
            resolver = StuckResolver(ResolverConfig())
            resolver.at_crosswalk = lambda rid: rid == "r1"
            row = {"robot_id": "r1", "online": True, "state": {"line_follow": {
                "mode": "CAMERA_LINE", "stuck": {"stuck_id": "s1", "cause": cause, "local_enabled": True,
                                                 "attempts": 0, "max_attempts": 2}, "crosswalk": None}}}
            if trip:
                row["trip"] = True
            row["ai_proposal"] = {"robot_id": "r1", "stuck_id": "s1", "decision": "BACK_AND_RETRY",
                                  "reason": "x", "confidence": 0.9, "evidence": {},
                                  "source": "analyzer:stuck_scene@1", "observed_at": 0.0, "ttl_s": 6.0}
            assert resolver.step(0.0, [row]) == [Answer("r1", "s1", "WAIT", "R5", escalate="crosswalk_human")]


def test_resolver_never_auto_resumes_at_a_mapped_crosswalk():
    # The XW crosswalk RESUME rule was removed as unsafe (independent review 2026-10-10).
    from fleet.stuck.resolver import ResolverConfig, StuckResolver
    resolver = StuckResolver(ResolverConfig())
    resolver.at_crosswalk = lambda rid: rid == "r1"
    row = {"robot_id": "r1", "online": True, "state": {"line_follow": {
        "mode": "CAMERA_LINE", "stuck": {"stuck_id": "s1", "cause": "no_motion"}}}}
    answers = resolver.step(0.0, [row])
    assert not any(getattr(a, "decision", None) == "RESUME" and getattr(a, "rule", None) == "XW" for a in answers)


def test_a_refused_cue_is_not_counted_as_sent():
    clock = [100.0]

    class Refusing(Client):
        async def line_follow_lane_cue(self, body):
            self.sent.append(body)
            return {"accepted": False, "reason": "pose_stale"}

    client = Refusing()
    poses = Poses(MapPose(0.5, -0.3, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, map_id="m", odom_stamp=5.0))
    monitor = LaneComplianceMonitor(lambda: ["r1"], poses=poses, site_maps=Maps(),
                                    config=LaneComplianceConfig(off_map_pad_m=0.5),
                                    wall=lambda: clock[0], clients=lambda: {"r1": client})
    for _ in range(4):
        asyncio.run(monitor.tick())
        clock[0] += 0.5
    assert client.sent and monitor._cue_sent.get("r1") is None and monitor._cue_refused["r1"] == "pose_stale"


def test_no_cue_while_the_robot_has_an_open_stuck_except_off_map():
    clock = [100.0]
    client = Client()
    poses = Poses(MapPose(0.5, -0.3, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, map_id="m", odom_stamp=5.0))
    monitor = LaneComplianceMonitor(lambda: ["r1"], poses=poses, site_maps=Maps(),
                                    config=LaneComplianceConfig(off_map_pad_m=0.5), wall=lambda: clock[0],
                                    clients=lambda: {"r1": client}, stuck_open=lambda rid: True)
    for _ in range(4):
        asyncio.run(monitor.tick())
        clock[0] += 0.5
    assert monitor.view("r1")["return"]["state"] == OFF_LANE and client.sent == []


def test_turn_spot_only_on_a_configured_spot():
    cfg = LaneComplianceConfig.from_mapping({"turn_spots": [{"x": 0.5, "y": 0.0}], "turn_spot_tolerance_m": 0.018})
    assert classify(0.51, 0.0, 0.0, 0.0, GRAPH, CW, cfg).turn_spot is True
    assert classify(0.53, 0.0, 0.0, 0.0, GRAPH, CW, cfg).turn_spot is False
    assert classify(0.5, 0.0, 0.0, 0.0, GRAPH, CW).turn_spot is False          # none configured


def test_site_example_turn_spots_parse():
    import yaml
    from pathlib import Path
    example = Path(__file__).resolve().parents[3] / "deploy" / "site" / "fleet-site.yaml.example"
    cfg = LaneComplianceConfig.from_mapping(yaml.safe_load(example.read_text(encoding="utf-8"))["fleet"]["lane_compliance"])
    assert len(cfg.turn_spots) == 4 and cfg.turn_spot_tolerance_m == 0.018 and cfg.wrong_way is False


def test_lap_context_names_the_next_feature_and_headings():
    from types import SimpleNamespace
    from fleet.localization.lap_context import build_lap, context

    class _Arc(SimpleNamespace):
        def point_at(self, s):
            s = min(max(s, 0.0), self.length_m)
            return self.x0 + s * math.cos(self.h), self.y0 + s * math.sin(self.h), self.h

    arcs = {f"a{i}": _Arc(edge_id=f"e{i}", length_m=1.0, end_place=f"p{i}", h=i * math.pi / 2,
                          x0=[0, 1, 1, 0][i], y0=[0, 0, 1, 1][i]) for i in range(4)}
    lap = build_lap(SimpleNamespace(arcs=arcs, out_of={"p0": ("a1", "x")}), ["a0", "a1", "a2", "a3"],
                    crosswalks=(),
                    turn_spots=[(1.0, 0.5)])
    c = context(lap, "a0", 0.5, 0.01, 0.1, 0.3)
    assert c["next"] == {"kind": "junction", "ds_m": c["next"]["ds_m"], "action": "left", "ref": "p0"}
    assert abs(c["next"]["ds_m"] - 0.5) < 0.02 and abs(c["heading_deg"]) < 1e-6
    c = context(lap, "a1", 0.2, 0.0, 0.1, 0.3)
    assert c["next"]["kind"] == "turn_spot" and abs(c["next"]["ds_m"] - 0.3) < 0.02
    assert c["heading_ahead_deg"] == 90.0 and context(lap, "zz", 0.1, 0.0, 0.1, 0.3) is None


def test_site_example_lap_builds_on_map_v5():
    import json
    import yaml
    from pathlib import Path
    from fleet.localization.lap_context import build_lap
    root = Path(__file__).resolve().parents[3]
    raw = yaml.safe_load((root / "deploy/site/fleet-site.yaml.example").read_text(encoding="utf-8"))
    cfg = LaneComplianceConfig.from_mapping(raw["fleet"]["lane_compliance"])
    site = SiteMap.model_validate(json.loads((root / "deploy/site/site-maps/map_v2_fleet-v5.json").read_text(encoding="utf-8")))
    cws = [(c.id, [tuple(p) for p in c.polygon]) for c in site.crosswalks]
    lap = build_lap(build_graph(site), cfg.lap_arcs, cws, cfg.turn_spots)
    kinds = [f[1] for f in lap.features]
    assert lap is not None and cfg.guide_context is False
    assert kinds.count("crosswalk") == 2 and kinds.count("ring_entry") == 2 and 7.0 < lap.length_m < 7.8
