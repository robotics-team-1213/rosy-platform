"""D-395 Phase 2 client routes (contract §2): candidates, decision, suspect; mission is P2-7."""

import asyncio
import json

import httpx
import pytest

from core_common.protocol.localization import CandidateReport, LocalizationDecision
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient, RobotApiError

from fakes import FakeRobot

EP = RobotEndpoint("rosy_02", "http://robot:8080", "op-token")

REPORT = {
    "robot_id": "rosy_02", "request_id": "rosy_02-7", "stamp": 12.5,
    "candidates": [{"x": 0.1, "y": 0.2, "yaw": 0.0, "scan_fit": 0.9},
                   {"x": -0.1, "y": -0.2, "yaw": 3.14, "scan_fit": 0.9}],
}


def run(coro):
    return asyncio.run(coro)


def _client(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=EP.base_url)
    return HttpRobotClient(EP, http=http)


def _recording(seen, status=200, body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"method": request.method, "path": request.url.path,
                     "auth": request.headers.get("authorization"),
                     "body": json.loads(request.content) if request.content else None})
        return httpx.Response(status, json=body if body is not None else {})
    return handler


def test_candidates_reads_the_report_as_a_model():
    seen = []
    got = run(_client(_recording(seen, body=REPORT)).localization_candidates())
    assert isinstance(got, CandidateReport)
    assert got.request_id == "rosy_02-7" and len(got.candidates) == 2
    assert seen == [{"method": "GET", "path": "/api/v1/localization/candidates",
                     "auth": "Bearer op-token", "body": None}]


@pytest.mark.parametrize("body", [{"code": "NO_CANDIDATES"},
                                  {"error": {"code": "NO_CANDIDATES", "message": "not in CANDIDATES"}},
                                  {"detail": "Not Found"}])
def test_no_candidates_is_none_not_an_error(body):
    assert run(_client(_recording([], status=404, body=body)).localization_candidates()) is None


def test_a_malformed_report_is_a_bad_response():
    with pytest.raises(RobotApiError) as exc:
        run(_client(_recording([], body={"robot_id": "rosy_02"})).localization_candidates())
    assert exc.value.code == "BAD_RESPONSE"


def test_decision_posts_the_wire_model():
    seen = []
    decision = LocalizationDecision(request_id="rosy_02-7", candidate_index=1, source="candidate",
                                    cues=["slot"], evidence={"margin": 1.5}, ttl_s=5.0)
    got = run(_client(_recording(seen, status=202, body={"request_id": "rosy_02-7"}))
              .localization_decision(decision))
    assert got == {"request_id": "rosy_02-7"}
    assert seen[0]["method"] == "POST" and seen[0]["path"] == "/api/v1/localization/decision"
    assert seen[0]["body"] == decision.model_dump(mode="json")


def test_a_stale_decision_surfaces_the_robots_code():
    body = {"error": {"code": "STALE_REQUEST", "message": "not the open request"}}
    decision = LocalizationDecision(request_id="old", candidate_index=0, source="candidate")
    with pytest.raises(RobotApiError) as exc:
        run(_client(_recording([], status=409, body=body)).localization_decision(decision))
    assert exc.value.status == 409 and exc.value.code == "STALE_REQUEST"


def test_suspect_posts_the_reason():
    seen = []
    run(_client(_recording(seen)).localization_suspect("fleet_monitor"))
    assert seen[0]["path"] == "/api/v1/localization/suspect"
    assert seen[0]["body"] == {"reason": "fleet_monitor"}


def test_suspect_refuses_a_reason_over_64_chars_before_sending():
    seen = []
    with pytest.raises(ValueError):
        run(_client(_recording(seen)).localization_suspect("x" * 65))
    assert seen == []


def test_mission_is_a_p2_7_stub_and_sends_nothing():
    seen = []
    with pytest.raises(NotImplementedError, match="P2-7"):
        run(_client(_recording(seen)).localization_mission("rotate_in_place", max_distance_m=0.0,
                                                           max_time_s=10.0))
    assert seen == []


def test_the_fake_robot_records_the_localization_calls():
    robot = FakeRobot("rosy_02")
    assert run(robot.localization_candidates()) is None
    robot.candidates = CandidateReport.model_validate(REPORT)
    assert run(robot.localization_candidates()).request_id == "rosy_02-7"
    decision = LocalizationDecision(request_id="rosy_02-7", candidate_index=0, source="candidate")
    run(robot.localization_decision(decision))
    run(robot.localization_suspect("fleet_monitor"))
    assert robot.decisions == [decision] and robot.suspects == ["fleet_monitor"]
    with pytest.raises(NotImplementedError):
        run(robot.localization_mission("rotate_in_place", max_distance_m=0.0, max_time_s=1.0))
