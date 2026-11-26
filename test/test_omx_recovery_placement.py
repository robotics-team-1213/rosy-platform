"""Incident-bound placement ranks path length and commits at most one physical attempt."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
from cell_recovery_placement import place_nearest  # noqa: E402


def route(target, *points):
    return {"target": target, "path_xyz_m": [(0, 0, 0), *points]}


class Scene:
    def __init__(self, *routes):
        self.routes = routes
        self.events = []
        self.receipt = dict.fromkeys(("supported", "released", "verified", "retreated"), True)
        self.occupancy = {}
        self.reservable = True
        self.claimed = False

    def candidates(self):
        return self.routes

    def available(self, candidate):
        target = candidate["target"]
        self.events.append(("observe", target))
        states = self.occupancy.get(target)
        return states.pop(0) if states else True

    def reserve(self, candidate):
        self.events.append(("reserve", candidate["target"]))
        return self.reservable

    def release(self, candidate):
        self.events.append(("free", candidate["target"]))

    def place(self, candidate):
        self.events.append(("place", candidate["target"]))
        if isinstance(self.receipt, Exception):
            raise self.receipt
        return self.receipt

    def begin(self, incident_id, target):
        assert incident_id == "incident"
        self.events.append(("begin", target))
        if self.claimed:
            return False
        self.claimed = True
        return True

    def verified(self, incident_id, target):
        assert incident_id == "incident" and self.claimed
        self.events.append(("verified", target))
        return True

    def run(self, holding=True):
        return place_nearest(self, holding=holding, journal=self, incident_id="incident")


def test_ranks_complete_path_and_rechecks_after_acquiring_lease():
    scene = Scene(route("detour", (0, 2, 0), (0, 0.1, 0)), route("direct", (0, 0.3, 0)))
    assert scene.run() == {"result": "placed", "target": "direct", "path_length_m": 0.3,
                           "placement_receipt": scene.receipt}
    assert [op for op, _ in scene.events] == ["observe", "reserve", "observe", "begin", "place", "verified", "free"]


def test_new_occupant_before_motion_releases_claim_and_tries_next():
    scene = Scene(route("near", (0, 0.1, 0)), route("far", (0, 0.2, 0)))
    scene.occupancy["near"] = [True, False]
    assert scene.run()["target"] == "far"
    assert ("free", "near") in scene.events
    assert ("begin", "near") not in scene.events


@pytest.mark.parametrize("receipt", [TimeoutError("late"), None, {}, {"supported": True, "released": True,
                          "verified": True, "retreated": 1}])
def test_uncertain_motion_never_retries_or_frees_the_occupied_corridor(receipt):
    scene = Scene(route("near", (0, 0.1, 0)), route("far", (0, 0.2, 0)))
    scene.receipt = receipt
    assert scene.run()["reason"] == "PLACEMENT_UNVERIFIED"
    assert scene.events[-1] == ("place", "near")
    assert scene.claimed


def test_invalid_paths_unknown_grasp_and_reservation_refusal_do_not_issue_motion():
    scene = Scene(route("nonfinite", (0, 0, float("nan"))), route("2D", (0, 1)), route("valid", (0, 0, 1)))
    assert scene.run(holding=1)["reason"] == "GRASP_UNCONFIRMED"
    assert not scene.events
    scene.reservable = False
    assert scene.run()["reason"] == "NO_AVAILABLE_PLACEMENT"
    assert scene.events == [("observe", "valid"), ("reserve", "valid")]


def test_concurrent_claim_releases_unused_lease_and_avoids_motion():
    scene = Scene(route("fixed", (0, 0, 1)))
    scene.claimed = True
    assert scene.run()["reason"] == "PLACEMENT_ALREADY_PENDING"
    assert scene.events[-1] == ("free", "fixed")
    assert ("place", "fixed") not in scene.events
