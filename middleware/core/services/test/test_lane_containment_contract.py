"""Image clock and geometric evidence validation for local lane return."""
import pytest
from pydantic import ValidationError

from core_common.protocol.lane_containment import LaneContainmentEvidence


def evidence():
    return dict(stamp=1., geometry_id="rig-a", ground_source="NOMINAL",
                boundaries=[dict(side="left", slope=0., intercept_m=.10,
                                 observed_x_min_m=.1, observed_x_max_m=.4)])


def test_unknown_uncertainty_is_not_fabricated_by_contract():
    assert LaneContainmentEvidence.model_validate(evidence()).uncertainty_m is None


@pytest.mark.parametrize("field,value", [("stamp", float("nan")), ("stamp", True),
    ("geometry_id", ""), ("uncertainty_m", -.1)])
def test_bad_evidence_rejected(field, value):
    raw = evidence(); raw[field] = value
    with pytest.raises(ValidationError): LaneContainmentEvidence.model_validate(raw)


def test_duplicate_sides_and_motion_fields_rejected():
    raw = evidence(); raw["boundaries"] *= 2
    with pytest.raises(ValidationError): LaneContainmentEvidence.model_validate(raw)
    raw = evidence(); raw["linear"] = .03
    with pytest.raises(ValidationError): LaneContainmentEvidence.model_validate(raw)


@pytest.mark.parametrize("outer,inner", [(None, "NOMINAL"), ("NOMINAL", "CALIBRATED")])
def test_ground_provenance_cannot_bypass_nominal_driver_gate(outer, inner):
    from core_features.line_follow.model import LineFollowMode, LineObservation
    raw = evidence(); raw["ground_source"] = inner
    with pytest.raises(ValueError, match="provenance"):
        LineObservation(LineFollowMode.CAMERA_LINE, 1., True, 0., .9,
                        ground=outer, containment=LaneContainmentEvidence.model_validate(raw))


def test_containment_must_match_source_image_not_receive_time():
    from core_features.line_follow.model import LineFollowMode, LineObservation
    raw = evidence(); raw["stamp"] = 1.02
    with pytest.raises(ValueError, match="image stamp"):
        LineObservation(LineFollowMode.CAMERA_LINE, 1., True, 0., .9, ground="NOMINAL",
                        containment=LaneContainmentEvidence.model_validate(raw))


def test_crosswalk_extent_is_optional_and_ordered():
    """D-491 §4: the camera's crosswalk extent, metres ahead of base_footprint."""
    assert LaneContainmentEvidence.model_validate(evidence()).crosswalk is None
    raw = evidence(); raw["crosswalk"] = dict(near_m=.12, far_m=.24)
    assert LaneContainmentEvidence.model_validate(raw).crosswalk.far_m == .24
    for bad in (dict(near_m=.24, far_m=.12), dict(near_m=-.1, far_m=.1),
                dict(near_m=.1, far_m=.2, linear=.03)):
        raw = evidence(); raw["crosswalk"] = bad
        with pytest.raises(ValidationError): LaneContainmentEvidence.model_validate(raw)
