"""D-619: device-neutral, unverified observations never become execution authority."""
import pytest

from core_common.protocol.situation import build_assessment, validate_assessment

VIEWS = {"front": {"frame_id": "front:1"}, "rosy_cam": {"frame_id": "ceiling:2"}}
RAW = {"type": "geometry", "direction": "reobserve", "observations": {
    "front": "A curved white boundary and a wall are visible.",
    "rosy_cam": "A robot is near the outside edge of the track."},
    "uncertainties": ["Body clearance and heading need sensor confirmation."]}


@pytest.mark.parametrize("domain", ["mobility", "manipulation"])
def test_same_contract_binds_observations_to_actual_frames_in_both_domains(domain):
    assessment = build_assessment(RAW, domain, VIEWS)
    assert assessment["domain"] == domain and assessment["verification"] == "unverified"
    assert assessment["observations"][0]["frame_id"] == "front:1"
    validate_assessment(assessment, VIEWS)


@pytest.mark.parametrize("change", [
    {"type": "grasp_success"}, {"direction": "joint_move"}, {"verification": "verified"},
    {"observations": {"invented_camera": "A wall is visible."}}, {"uncertainties": "none"},
])
def test_bad_or_self_verified_model_answer_is_rejected(change):
    with pytest.raises(ValueError):
        build_assessment({**RAW, **change}, "mobility", VIEWS)


def test_wire_assessment_cannot_substitute_a_frame_or_claim_verification():
    assessment = build_assessment(RAW, "mobility", VIEWS)
    for change in ({"verification": "verified"}, {"domain": "unknown"},
                   {"observations": [{"source": "front", "frame_id": "other:9", "description": "A wall is visible."}]}):
        with pytest.raises(ValueError):
            validate_assessment({**assessment, **change}, VIEWS)
