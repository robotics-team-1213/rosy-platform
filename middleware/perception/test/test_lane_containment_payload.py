"""D-468 producer reports observed support and unknown geometry uncertainty."""
from types import SimpleNamespace
import pytest
from control.sensing.perception.lane_containment import containment_payload


def ground():
    return SimpleNamespace(height_m=.055, pitch_rad=.21, focal_px=281.6,
        principal_x=160., principal_y=120., max_range_m=1.)


def test_payload_preserves_original_image_and_measured_support():
    keeper = {"boundaries": [dict(selected=True, side="left",
                ends_m=[[.2,.1],[.4,.12]])]}
    raw = containment_payload(keeper, ground(), stamp=1.25, source="NOMINAL", camera_x=.033)
    assert raw["stamp"] == 1.25
    assert raw["uncertainty_m"] is None
    assert raw["boundaries"][0]["observed_x_min_m"] == .2
    assert raw["boundaries"][0]["intercept_m"] == pytest.approx(.08)


def test_geometry_change_invalidates_identity_and_unselected_edges_are_ignored():
    keeper = {"boundaries": [dict(selected=False, side="left", ends_m=[[.2,.1],[.4,.12]])]}
    g = ground()
    before = containment_payload(keeper, g, stamp=1., source="NOMINAL", camera_x=.033)
    g.pitch_rad += .01
    after = containment_payload(keeper, g, stamp=2., source="NOMINAL", camera_x=.033)
    assert before["geometry_id"] != after["geometry_id"]
    assert before["boundaries"] == []


def test_absent_ground_does_not_fabricate_calibration():
    assert containment_payload({}, None, stamp=1., source="NOMINAL", camera_x=.033) is None


@pytest.mark.parametrize("source", ["NOMINAL", "CALIBRATED"])
def test_device_grounds_keep_unknown_uncertainty(source):
    assert containment_payload({}, ground(), stamp=1., source=source, camera_x=.033)["uncertainty_m"] is None


def test_gazebo_ground_declares_the_detector_pixel_error_only():
    # Exact sim camera geometry: 2 px lateral at the farthest ground range, nothing else.
    g = ground()
    g.max_range_m = .6
    raw = containment_payload({}, g, stamp=1., source="GAZEBO", camera_x=.033)
    assert raw["uncertainty_m"] == pytest.approx(2 * .6 / 281.6)
    assert raw["uncertainty_m"] < .015  # inside the D-468 receiver's MAX_UNCERTAINTY_M
