"""D-511 rev 1: the Fleet return loop — classify, debounce, crosswalk hint, the cue to CORE."""

import asyncio
import math

from fleet.localization.lane_compliance import (OFF_LANE, OFF_MAP, ON_LANE, ON_LINE, UNSEEN, WRONG_WAY,
                                                LaneComplianceConfig, ReturnTracker, classify)
from fleet.localization.map_pose import MapPose
from fleet.routing.graph import build_graph
from fleet.server.lane_compliance_service import LaneComplianceMonitor
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
    off = classify(0.5, -0.3, 0.0, 0.0, GRAPH, CW)
    assert off.state == OFF_LANE and off.side == "left" and off.bearing_deg > 0
    assert classify(5.0, 0.0, 0.0, 0.0, GRAPH, CW).state == OFF_MAP
    assert classify(0.5, 0.0, math.pi, math.pi, GRAPH, CW).state == WRONG_WAY
    # turning in place (body yaw reversed, travel still along) is not wrong way yet
    assert classify(0.5, 0.0, math.pi, 0.0, GRAPH, CW).state == ON_LANE


def test_crosswalk_is_on_lane_and_hinted_ahead():
    ahead = classify(0.7, 0.0, 0.0, 0.0, GRAPH, CW).crosswalk_ahead
    assert ahead["id"] == "cw" and 0.1 < ahead["distance_m"] < 0.3 and abs(ahead["length_m"] - 0.12) < 0.02
    inside = classify(1.06, 0.07, 0.0, 0.0, GRAPH, CW)      # off-centre inside a crosswalk
    assert inside.state == ON_LANE and inside.crosswalk == "cw"
    assert classify(0.7, 0.0, math.pi, math.pi, GRAPH, CW).crosswalk_ahead is None  # wrong way: no hint


def test_tracker_debounces_and_wrong_way_needs_travel():
    tr = ReturnTracker(LaneComplianceConfig(return_persist_s=1.0, wrong_way_min_m=0.1))
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
    poses = Poses(MapPose(0.5, -0.3, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, map_id="m"))
    monitor = LaneComplianceMonitor(lambda: ["r1"], poses=poses, site_maps=Maps(),
                                    wall=lambda: clock[0], clients=lambda: {"r1": client})
    for _ in range(4):
        asyncio.run(monitor.tick())
        clock[0] += 0.5
    assert monitor.view("r1")["return"]["state"] == OFF_LANE
    assert client.sent and client.sent[-1]["state"] == OFF_LANE and client.sent[-1]["side"] == "left"
    assert client.sent[-1]["ttl_s"] <= 1.0
    poses.pose = MapPose(0.3, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, map_id="m")
    for _ in range(6):
        asyncio.run(monitor.tick())
        clock[0] += 0.5
    states = [b["state"] for b in client.sent]
    assert states.count(ON_LANE) == 1 and states[-1] == ON_LANE
