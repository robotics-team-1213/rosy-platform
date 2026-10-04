"""D-457 5-6: Fleet keeps 1.0 s of detections per source and pairs them with fresh map poses."""

import json
from pathlib import Path

import pytest

from core_common.protocol.overhead_detections import OverheadDetectionsPayload
from fleet.server.sightings import SightingSource
from fleet.server.tracking import TrackingError, TrackingService
from fleet.server.tracking_calibration import TrackingCalibrationStore

NOW = 1_790_000_000.0
TOKEN = "north-source-secret"
AUTH = f"Bearer {TOKEN}"
FIXTURE = json.loads((Path(__file__).resolve().parents[3]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in FIXTURE["cases"]}
APPROVAL = {
    "source_id": "ceiling_north", "map_id": None,
    "map_to_image": [100.0, 0.0, 0.0, 0.0, -100.0, 360.0, 0.0, 0.0, 1.0],
    "image": {"width": 640, "height": 360},
    "track_bounds_m": {"min_x": 0.0, "min_y": 0.0, "max_x": 6.4, "max_y": 3.6},
    "fit_score": 0.81, "lens": None, "frame_seq": 12,
}


class _Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def _source(**changes):
    fields = dict(source_id="ceiling_north", token=TOKEN, robot_ids=("rosy_01", "rosy_02"),
                  map_id="map_v2_fleet", calibration_revision="cal-v3",
                  corner_marker_ids=(30, 31, 32, 33))
    fields.update(changes)
    return SightingSource(**fields)


def _service():
    clock = _Clock()
    return TrackingService([_source()], calibrations=TrackingCalibrationStore(), clock=clock), clock


def _payload(**changes):
    body = dict(CASES["ok_two_detections"]["payload"])
    body["captured_at"] = NOW - 0.1
    body.update(changes)
    return OverheadDetectionsPayload.model_validate(body)


def _state(x, y, *, map_id="map_v2_fleet", localization=None):
    state = {"robot_id": "rosy_01", "map_id": map_id, "pose": {"x": x, "y": y, "yaw": 0.0}}
    if localization is not None:
        state["localization"] = localization
    return state


def _robots(**states):
    return [{"robot_id": rid, "online": True, "state": state} for rid, state in states.items()]


def _rows(service):
    return {row["robot_id"]: row for row in service.snapshot()["robots"]}


def test_marker_identity_wins_without_core_map_pose_and_expires():
    clock = _Clock()
    service = TrackingService([_source(robot_markers=(("rosy_01", 7),))],
                              calibrations=TrackingCalibrationStore(), clock=clock)
    service.accept(AUTH, _payload(calibration_revision="cal-v3", detections=[
        {"x": 1, "y": 1, "footprint_m": .165, "score": 1, "marker_id": 7},
        {"x": 1.02, "y": 1, "footprint_m": .18, "score": .8}]))
    row = _rows(service)["rosy_01"]
    assert row["status"] == "MARKER" and row["camera"]["x"] == 1
    assert row["pose"] is None
    assert service.snapshot()["unknown"] == []
    clock.now += 1.1
    assert _rows(service)["rosy_01"]["status"] == "CAMERA_UNAVAILABLE"
    service.accept(AUTH, _payload(calibration_revision="cal-v3", captured_at=clock.now,
        detections=[{"x": 1, "y": 1, "footprint_m": .18, "score": .8}]))
    assert _rows(service)["rosy_01"]["status"] == "NO_POSE"


def test_one_marker_removes_only_its_own_blob_and_keeps_an_adjacent_robot():
    service = TrackingService([_source(robot_markers=(("rosy_01", 7),))],
                              calibrations=TrackingCalibrationStore(), clock=_Clock())
    service.observe_states(_robots(rosy_02=_state(1.22, 1)))
    service.accept(AUTH, _payload(calibration_revision="cal-v3", detections=[
        {"x": 1, "y": 1, "footprint_m": .165, "score": 1, "marker_id": 7},
        {"x": 1, "y": 1, "footprint_m": .165, "score": .8},
        {"x": 1.22, "y": 1, "footprint_m": .26, "score": .8}]))
    assert _rows(service)["rosy_01"]["status"] == "MARKER"
    assert _rows(service)["rosy_02"]["status"] == "MATCHED"
    assert _rows(service)["rosy_02"]["camera"]["x"] == 1.22


def test_unknown_marker_cannot_claim_a_robot_identity():
    service, _ = _service()
    service.accept(AUTH, _payload(calibration_revision="cal-v3", detections=[
        {"x": 1, "y": 1, "footprint_m": .165, "score": 1, "marker_id": 99}]))
    assert all(row["status"] != "MARKER" for row in service.snapshot()["robots"])


def test_matched_robot_reports_the_offset_and_the_rest_is_unknown():
    service, _ = _service()
    record = service.approve(dict(APPROVAL), approved_by="operator-1")
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4, localization={
        "state": "LOCALIZED", "pose_frame": "map", "confidence": 0.9})))
    service.accept(AUTH, _payload(calibration_revision=record["calibration_revision"]))
    snap = service.snapshot()
    rows = {row["robot_id"]: row for row in snap["robots"]}
    assert rows["rosy_01"]["status"] == "MATCHED"
    assert rows["rosy_01"]["offset_m"] == pytest.approx(0.0471, abs=1e-4)
    assert rows["rosy_01"]["camera"] == {"x": 1.2345, "y": 0.4321, "footprint_m": 0.181, "score": 0.83}
    assert rows["rosy_01"]["pose"] == {"x": 1.2, "y": 0.4}
    assert rows["rosy_01"]["pose_frame_verified"] is True
    assert rows["rosy_02"]["status"] == "NO_POSE"
    assert [(row["x"], row["y"]) for row in snap["unknown"]] == [(2.5, 1.0)]
    assert snap["sources"][0]["status"] == "OK"
    assert snap["use"] == "display-only"


def test_marker_calibration_revision_is_accepted_without_a_record():
    service, _ = _service()
    assert service.accept(AUTH, _payload(calibration_revision="cal-v3")) == {
        "accepted": True, "source_id": "ceiling_north", "seq": 41, "status": "OK"}


def test_unknown_calibration_revision_is_409_and_shown_as_mismatch():
    service, _ = _service()
    with pytest.raises(TrackingError) as err:
        service.accept(AUTH, _payload())
    assert (err.value.status_code, err.value.code) == (409, "CALIBRATION_MISMATCH")
    assert service.snapshot()["sources"][0]["last_error"] == "CALIBRATION_MISMATCH"
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    assert service.snapshot()["sources"][0]["last_error"] is None


@pytest.mark.parametrize("authorization,changes,status,code", [
    (None, {}, 401, "DETECTION_UNAUTHORIZED"),
    ("Bearer wrong", {}, 401, "DETECTION_UNAUTHORIZED"),
    (AUTH, {"source_id": "ceiling_south"}, 403, "SOURCE_MISMATCH"),
    (AUTH, {"map_id": "other_map"}, 409, "MAP_MISMATCH"),
    (AUTH, {"captured_at": NOW - 1.5}, 409, "DETECTION_STALE"),
    (AUTH, {"captured_at": NOW + 1.0}, 409, "DETECTION_FUTURE"),
])
def test_rejected_payloads(authorization, changes, status, code):
    service, _ = _service()
    with pytest.raises(TrackingError) as err:
        service.accept(authorization, _payload(calibration_revision="cal-v3", **changes))
    assert (err.value.status_code, err.value.code) == (status, code)


@pytest.mark.parametrize("changes,code", [
    ({"captured_at": NOW - 1.5}, "DETECTION_STALE"),
    ({"captured_at": NOW + 1.0}, "DETECTION_FUTURE"),
])
def test_time_rejections_are_shown_as_the_last_error(changes, code):
    service, _ = _service()
    with pytest.raises(TrackingError):
        service.accept(AUTH, _payload(calibration_revision="cal-v3", **changes))
    assert service.snapshot()["sources"][0]["last_error"] == code


def test_capture_slightly_ahead_of_the_fleet_clock_is_accepted():
    service, _ = _service()
    assert service.accept(AUTH, _payload(calibration_revision="cal-v3", captured_at=NOW + 0.04))[
        "accepted"] is True
    assert service.snapshot()["sources"][0]["age_ms"] == 0


def test_out_of_order_payload_is_rejected():
    service, _ = _service()
    service.accept(AUTH, _payload(calibration_revision="cal-v3", seq=2))
    with pytest.raises(TrackingError) as err:
        service.accept(AUTH, _payload(calibration_revision="cal-v3", seq=3, captured_at=NOW - 0.2))
    assert err.value.code == "DETECTION_OUT_OF_ORDER"
    assert service.snapshot()["sources"][0]["last_error"] == "DETECTION_OUT_OF_ORDER"


@pytest.mark.parametrize("changes", [
    {"status": "CALIBRATION_REQUIRED", "calibration_revision": None, "detections": []},
    {"status": "SCENE_CHANGED", "calibration_revision": "cal-v3", "detections": []},
    {"status": "LEARNING", "calibration_revision": "cal-v3", "detections": []},
])
def test_non_ok_payload_is_accepted_and_robots_are_camera_unavailable(changes):
    service, _ = _service()
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4)))
    assert service.accept(AUTH, _payload(**changes))["status"] == changes["status"]
    snap = service.snapshot()
    assert snap["sources"][0]["status"] == changes["status"]
    assert {row["status"] for row in snap["robots"]} == {"CAMERA_UNAVAILABLE"}
    assert snap["unknown"] == []


SOUTH_TOKEN = "south-source-secret"


def _two_sources():
    clock = _Clock()
    sources = [_source(), _source(source_id="ceiling_south", token=SOUTH_TOKEN, robot_ids=("rosy_01",))]
    return TrackingService(sources, calibrations=TrackingCalibrationStore(), clock=clock)


def test_two_sources_merge_to_the_most_informative_row_and_name_its_source():
    service = _two_sources()
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4)))
    service.accept(AUTH, _payload(calibration_revision="cal-v3", detections=[]))
    service.accept(f"Bearer {SOUTH_TOKEN}", _payload(source_id="ceiling_south",
                                                     calibration_revision="cal-v3"))
    rows = _rows(service)
    assert (rows["rosy_01"]["status"], rows["rosy_01"]["source_id"]) == ("MATCHED", "ceiling_south")
    assert (rows["rosy_02"]["status"], rows["rosy_02"]["source_id"]) == ("NO_POSE", "ceiling_north")
    assert [(row["source_id"], row["x"]) for row in service.snapshot()["unknown"]] == [
        ("ceiling_south", 2.5)]


def test_equal_rank_keeps_the_first_configured_source():
    service = _two_sources()
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4)))
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    service.accept(f"Bearer {SOUTH_TOKEN}", _payload(source_id="ceiling_south",
                                                     calibration_revision="cal-v3"))
    assert _rows(service)["rosy_01"]["source_id"] == "ceiling_north"


def test_a_source_token_cannot_post_for_another_source():
    service = _two_sources()
    with pytest.raises(TrackingError) as err:
        service.accept(AUTH, _payload(source_id="ceiling_south", calibration_revision="cal-v3"))
    assert (err.value.status_code, err.value.code) == (403, "SOURCE_MISMATCH")
    assert service.snapshot()["sources"][1]["status"] == "NONE"


def test_state_observed_with_an_earlier_stamp_ages_from_that_stamp():
    service, _ = _service()
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4)), now=NOW - 2.5)
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    assert _rows(service)["rosy_01"]["status"] == "NO_POSE"


def test_payload_expires_after_the_lease_and_nothing_old_is_shown():
    service, clock = _service()
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4)))
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    clock.now = NOW + 1.0
    snap = service.snapshot()
    assert snap["sources"][0]["status"] == "STALE"
    assert {row["status"] for row in snap["robots"]} == {"CAMERA_UNAVAILABLE"}
    assert snap["unknown"] == []


def test_no_payload_yet_is_none_and_camera_unavailable():
    service, _ = _service()
    snap = service.snapshot()
    assert snap["sources"][0]["status"] == "NONE"
    assert {row["status"] for row in snap["robots"]} == {"CAMERA_UNAVAILABLE"}


def test_learning_status_means_camera_unavailable():
    service, _ = _service()
    service.accept(AUTH, _payload(calibration_revision="cal-v3", status="LEARNING", detections=[]))
    snap = service.snapshot()
    assert snap["sources"][0]["status"] == "LEARNING"
    assert {row["status"] for row in snap["robots"]} == {"CAMERA_UNAVAILABLE"}


@pytest.mark.parametrize("state", [
    _state(1.2, 0.4, map_id="other_map"),
    _state(1.2, 0.4, localization={"state": "LOCALIZED", "pose_frame": "odom"}),
    _state(1.2, 0.4, localization={"state": "SUSPECT", "pose_frame": "map"}),
    _state(1.2, 0.4, localization="LOCALIZED"),
    {"robot_id": "rosy_01", "map_id": "map_v2_fleet"},
    _state(float("nan"), 0.4),
])
def test_robot_without_a_trusted_map_pose_is_no_pose(state):
    service, _ = _service()
    service.observe_states(_robots(rosy_01=state))
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    assert _rows(service)["rosy_01"]["status"] == "NO_POSE"
    assert len(service.snapshot()["unknown"]) == 2


def test_robot_that_predates_d395_is_matched_but_marked_unverified():
    service, _ = _service()
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4)))
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    row = _rows(service)["rosy_01"]
    assert row["status"] == "MATCHED" and row["pose_frame_verified"] is False


def test_state_older_than_two_seconds_is_no_pose():
    service, clock = _service()
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4)))
    clock.now = NOW + 2.5
    service.accept(AUTH, _payload(calibration_revision="cal-v3", captured_at=NOW + 2.4))
    assert _rows(service)["rosy_01"]["status"] == "NO_POSE"


def test_offline_rows_are_ignored():
    service, _ = _service()
    service.observe_states([{"robot_id": "rosy_01", "online": False, "state": None}])
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    assert _rows(service)["rosy_01"]["status"] == "NO_POSE"


def test_robot_going_offline_drops_its_last_pose():
    service, _ = _service()
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4)))
    service.observe_states([{"robot_id": "rosy_01", "online": False, "state": None}])
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    assert _rows(service)["rosy_01"]["status"] == "NO_POSE"


@pytest.mark.parametrize("sources", [
    [_source(robot_ids=("rosy_01", "rosy_01"))],
    [_source(), _source(token="other-secret")],
    [_source(), _source(source_id="ceiling_south")],
    [_source(robot_markers=(("unknown", 7),))],
    [_source(robot_markers=(("rosy_01", 7), ("rosy_02", 7)))],
    [_source(robot_markers=(("rosy_01", 7), ("rosy_01", 8)))],
    [_source(robot_markers=(("rosy_01", -1),))],
])
def test_duplicate_robot_targets_source_ids_or_tokens_are_refused(sources):
    with pytest.raises(ValueError):
        TrackingService(sources, calibrations=TrackingCalibrationStore())


def test_config_returns_the_approved_record_and_relearn_counter():
    service, _ = _service()
    assert service.config_for(AUTH) == {"source_id": "ceiling_north", "map_id": "map_v2_fleet",
                                        "calibration": None, "relearn_seq": 0}
    record = service.approve(dict(APPROVAL), approved_by="operator-1")
    assert service.request_relearn("ceiling_north") == {"source_id": "ceiling_north", "relearn_seq": 1}
    config = service.config_for(AUTH)
    assert config["calibration"] == record and config["relearn_seq"] == 1
    assert record["approved_by"] == "operator-1" and record["map_id"] == "map_v2_fleet"
    assert record["calibration_revision"].startswith("paint-")
    assert service.calibration_listing() == {"calibrations": [record], "use": "display-only"}
    with pytest.raises(TrackingError) as err:
        service.config_for("Bearer wrong")
    assert err.value.status_code == 401


@pytest.mark.parametrize("changes,code", [
    ({"source_id": "nope"}, "UNKNOWN_SOURCE"),
    ({"map_id": "other_map"}, "MAP_MISMATCH"),
    ({"map_to_image": [0.0] * 9}, "INVALID_CALIBRATION"),
])
def test_approval_refuses_unknown_source_other_map_and_bad_matrix(changes, code):
    service, _ = _service()
    with pytest.raises(TrackingError) as err:
        service.approve({**APPROVAL, **changes}, approved_by="operator-1")
    assert err.value.code == code


def test_revoke_removes_the_record_and_unknown_sources_are_404():
    service, _ = _service()
    service.approve(dict(APPROVAL), approved_by="operator-1")
    assert service.revoke("ceiling_north", principal_id="operator-1") == {
        "source_id": "ceiling_north", "removed": True}
    assert service.config_for(AUTH)["calibration"] is None
    for call in (lambda: service.revoke("nope", principal_id="operator-1"),
                 lambda: service.request_relearn("nope")):
        with pytest.raises(TrackingError) as err:
            call()
        assert err.value.status_code == 404


def test_fps_counts_accepted_payloads_over_three_seconds():
    service, clock = _service()
    for index in range(6):
        clock.now = NOW + index / 3
        service.accept(AUTH, _payload(calibration_revision="cal-v3", seq=index,
                                      captured_at=clock.now - 0.05))
    assert service.snapshot()["sources"][0]["fps"] == 2.0
