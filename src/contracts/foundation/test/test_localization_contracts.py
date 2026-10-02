"""D-395 §4 wire models: additive, frame-explicit, one decision target."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from core_common.protocol.localization import (
    CHECKING, CandidateReport, DecisionSource, LocalizationDecision, LocalizationStatus, LocState, PoseFrame)
from core_common.protocol.schemas import StateSnapshot

REFERENCE = Path(__file__).resolve().parents[4] / "docs" / "reference" / "ROSY API & Protocol Reference.md"


def _report(**over):
    doc = {"robot_id": "rosy_01", "request_id": "rosy_01-7",
           "candidates": [{"x": -1.26, "y": .49, "yaw": -1.57, "scan_fit": .99, "paint_score": .97},
                          {"x": 1.26, "y": -.49, "yaw": 1.57, "scan_fit": .99}],
           "unmapped_objects": [{"x": .6, "y": .1}],
           "square_sightings": [{"bearing_rad": .1, "range_m": .3, "confidence": .9}],
           "pickup": False, "stamp": 1760000000.5}
    doc.update(over)
    return doc


def test_a_snapshot_without_localization_is_a_pre_d395_robot():
    snap = StateSnapshot(robot_id="rosy_01")
    assert snap.localization is None
    assert "localization" in snap.model_dump()


def test_a_snapshot_carries_state_and_frame():
    snap = StateSnapshot.model_validate({"robot_id": "rosy_01", "localization": {
        "state": "LOCALIZED", "pose_frame": "map", "confidence": .93, "request_id": "rosy_01-7"}})
    assert snap.localization.state is LocState.LOCALIZED
    assert snap.localization.pose_frame is PoseFrame.MAP
    assert snap.model_dump(mode="json")["localization"]["pose_frame"] == "map"


@pytest.mark.parametrize("bad", [
    {"state": "LOST", "pose_frame": "map"},
    {"state": "UNKNOWN", "pose_frame": "base_link"},
    {"state": "UNKNOWN", "pose_frame": "odom", "confidence": 1.5},
    {"state": "UNKNOWN", "pose_frame": "odom", "request_id": "has space"},
    {"state": "UNKNOWN", "pose_frame": "odom", "extra": 1},
])
def test_status_rejects_unknown_values(bad):
    with pytest.raises(ValidationError):
        LocalizationStatus.model_validate(bad)


def test_a_candidate_report_round_trips():
    report = CandidateReport.model_validate(_report())
    assert report.candidates[1].paint_score is None
    assert CandidateReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize("over", [
    {"candidates": []},
    {"candidates": [{"x": 0., "y": 0., "yaw": 0., "scan_fit": .9}] * 9},
    {"candidates": [{"x": math.nan, "y": 0., "yaw": 0., "scan_fit": .9}]},
    {"candidates": [{"x": 0., "y": 0., "yaw": 0., "scan_fit": 1.2}]},
    {"square_sightings": [{"bearing_rad": 0., "range_m": 0., "confidence": .5}]},
    {"stamp": math.inf},
    {"request_id": ""},
])
def test_a_candidate_report_rejects_malformed_fields(over):
    with pytest.raises(ValidationError):
        CandidateReport.model_validate(_report(**over))


def test_a_decision_names_a_candidate_or_a_pose_never_both():
    by_index = LocalizationDecision(request_id="rosy_01-7", candidate_index=0, source="candidate",
                                    cues=["slot"])
    assert by_index.source is DecisionSource.CANDIDATE and by_index.pose is None
    direct = LocalizationDecision(request_id="rosy_01-7", pose={"x": -1.2, "y": .5, "yaw": 0.},
                                  source="homing_ref", cues=["square"])
    assert direct.pose.x == -1.2
    for bad in ({"candidate_index": 0, "pose": {"x": 0., "y": 0., "yaw": 0.}, "source": "candidate"},
                {"source": "candidate"},
                {"candidate_index": 0, "source": "overhead"},
                {"pose": {"x": 0., "y": 0., "yaw": 0.}, "source": "candidate"},
                {"candidate_index": True, "source": "candidate"},
                {"candidate_index": 8, "source": "candidate"}):
        with pytest.raises(ValidationError):
            LocalizationDecision(request_id="rosy_01-7", cues=["slot"], **bad)


def test_a_decision_lifetime_is_relative_and_its_cues_are_named():
    """D-395 rev. 3: ttl_s runs from receipt (no shared clock); cues name what carried it."""
    d = LocalizationDecision(request_id="rosy_01-7", candidate_index=0, source="candidate", cues=["paint"])
    assert d.ttl_s == 5.0 and [c.value for c in d.cues] == ["paint"]
    assert LocalizationDecision(request_id="rosy_01-7", pose={"x": 0., "y": 0., "yaw": 0.},
                                source="human").cues == []
    for bad in ({"ttl_s": 0.}, {"ttl_s": 31.}, {"cues": ["gut_feeling"]}, {"expires_at": 1.}):
        with pytest.raises(ValidationError):
            LocalizationDecision(request_id="rosy_01-7", candidate_index=0, source="candidate", **bad)


def test_the_api_reference_documents_the_field_and_the_models():
    text = REFERENCE.read_text(encoding="utf-8")
    assert '"localization": {' in text
    assert "## 7.9 Fleet 보조 위치 확정 모델" in text
    for name in ("CandidateReport", "LocalizationDecision", "square_sightings", "pose_frame", "ttl_s", "cues"):
        assert name in text


def test_a_localized_status_carries_its_unmapped_objects_with_their_scan_stamp():
    """D-395 rev. 4 §5 follow-up (S1 R1): LOCALIZED robots keep reporting what they see."""
    status = LocalizationStatus.model_validate({
        "state": "LOCALIZED", "pose_frame": "map", "unmapped_objects": [{"x": .6, "y": -.1}],
        "objects_stamp": 12.5})
    assert status.unmapped_objects[0].x == .6 and status.objects_stamp == 12.5
    assert LocalizationStatus.model_validate_json(status.model_dump_json()) == status
    bare = LocalizationStatus(state="UNKNOWN", pose_frame="odom")
    assert bare.unmapped_objects == [] and bare.objects_stamp is None
    for bad in ({"unmapped_objects": [{"x": 0., "y": 0.}] * 17},
                {"unmapped_objects": [{"x": math.nan, "y": 0.}]},
                {"objects_stamp": math.inf}):
        with pytest.raises(ValidationError):
            LocalizationStatus.model_validate({"state": "LOCALIZED", "pose_frame": "map", **bad})


def test_a_running_check_is_the_candidates_reason_checking():
    """S1 re-run R6: the robot shows its 3 s injection check; Fleet and CORE pause on it."""
    status = LocalizationStatus(state="CANDIDATES", pose_frame="odom", reason=CHECKING,
                                request_id="rosy_01-7")
    assert status.reason == "checking" and len(CHECKING) <= 64
