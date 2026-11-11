"""The camera draft entrance: Vision's draft-map proposal becomes a save-ready draft body.

The browser fetched Vision's ``draft-map`` proposal with a Fleet-issued lease (the D-375
pattern) and posts it here. The server turns the candidates — already in map metres on the
rectified plane — into a complete ``rosy.site_map/1`` body (survey reference, junction
places at the lane ends, two-way edges, exclusion facilities) that validates, and returns
it for operator review. Nothing is written: saving is the operator's existing PUT draft.
"""

from __future__ import annotations

from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.site_map import SiteMap
from fleet.swarm.robots import RobotEndpoint

OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}
ROBOT = "rosy_60"
PATH = "/api/fleet/site-map/draft-from-camera"


def _client(tmp_path) -> TestClient:
    robot = FakeRobot(ROBOT, state={"robot_id": ROBOT, "mode": "IDLE"})
    console = FleetConsole([RobotEndpoint(ROBOT, "http://127.0.0.1:8080", "t")], [robot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={ROBOT})
    users = {sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"},
             sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    return TestClient(create_app(console, task_service=tasks, site_users=users))


def _body() -> dict:
    """One kept lane, one too-short lane to skip, one exclusion zone: Vision's draft-map shape."""
    return {
        "source_id": "ceiling_north",
        "plane": {"bounds_m": [-1.15, -0.65, 1.15, 0.65], "px_per_m": 400.0,
                  "calibration_revision": "paint-test"},
        "detector": {"version": "draft-map-1"},
        "lanes": [
            {"polyline_m": [[-0.5, 0.05], [0.5, 0.05]], "width_px": 40.0},
            {"polyline_m": [[0.0, 0.3], [0.05, 0.3]], "width_px": 40.0},
        ],
        "zones": [
            {"polygon_m": [[-0.4, -0.4], [-0.1, -0.4], [-0.1, -0.1], [-0.4, -0.1]],
             "kind": "exclusion"},
        ],
    }


def test_a_viewer_cannot_ask_for_a_camera_draft(tmp_path):
    response = _client(tmp_path).post(PATH, json=_body(), headers=VIEWER)
    assert response.status_code == 403


def test_the_camera_draft_becomes_a_valid_map_body(tmp_path):
    response = _client(tmp_path).post(PATH, json=_body(), headers=OPERATOR)
    assert response.status_code == 200, response.text
    body = response.json()
    draft = SiteMap.model_validate(body["map"])          # save-ready as-is
    assert draft.survey.scale_source == "measured"
    assert draft.survey.revision == "camera-paint-test"
    assert len(draft.places) == 2 and len(draft.edges) == 1
    edge = draft.edges[0]
    assert edge.width_m == 0.1 and edge.direction == "two_way"
    assert edge.evidence.source == "camera" and edge.evidence.reference_revision == draft.survey.revision
    assert len(draft.facilities) == 1 and draft.facilities[0].kind == "exclusion"
    assert len(draft.facilities[0].geometry) == 4
    assert body["provenance"] == {"source_id": "ceiling_north", "calibration_revision": "paint-test",
                                  "detector_version": "draft-map-1", "lanes": 1, "zones": 1,
                                  "skipped": [{"index": 1, "reason": "shorter than 0.15 m"}]}


def test_the_camera_draft_is_idempotent_and_writes_nothing(tmp_path):
    client = _client(tmp_path)
    before = client.get("/api/fleet/site-map/draft")
    first = client.post(PATH, json=_body(), headers=OPERATOR)
    second = client.post(PATH, json=_body(), headers=OPERATOR)
    assert first.status_code == 200 and first.json() == second.json()
    after = client.get("/api/fleet/site-map/draft")          # the draft is untouched
    assert after.status_code == before.status_code and after.json() == before.json()


def test_a_lane_snapped_short_between_shared_junctions_is_skipped(tmp_path):
    body = _body()
    body["lanes"] = [
        {"polyline_m": [[0.0, 0.0], [0.5, 0.0]], "width_px": 40.0},
        {"polyline_m": [[0.0, 0.09], [0.5, 0.09]], "width_px": 40.0},
        # a kept zigzag whose ends snap to the two near junctions above: pinned < MIN_EDGE_M
        {"polyline_m": [[0.01, 0.01], [0.25, 0.3], [0.01, 0.08]], "width_px": 40.0},
    ]
    body["zones"] = []
    response = _client(tmp_path).post(PATH, json=body, headers=OPERATOR)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["provenance"]["lanes"] == 2
    assert result["provenance"]["skipped"] == [{"index": 2, "reason": "its ends share junctions less than 0.10 m apart"}]


def test_a_lane_of_one_point_is_refused_whole(tmp_path):
    body = _body()
    body["lanes"][0]["polyline_m"] = [[0.0, 0.0]]
    response = _client(tmp_path).post(PATH, json=body, headers=OPERATOR)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SITE_MAP_CAMERA_INVALID"


def test_a_proposal_with_no_candidates_is_refused(tmp_path):
    body = _body()
    body["lanes"] = []
    body["zones"] = []
    response = _client(tmp_path).post(PATH, json=body, headers=OPERATOR)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SITE_MAP_CAMERA_INVALID"
