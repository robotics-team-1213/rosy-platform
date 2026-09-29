"""D-353 §3: NOMINAL floor model from the estimated Pinky Pro camera profile."""
from pathlib import Path

import pytest
import yaml

from control.sensing.perception.camera_ground import nominal_ground_plane
from control.sensing.perception.lane import line_observation_payload, LaneObservation

PKG = Path(__file__).resolve().parents[1]
PROFILE = yaml.safe_load((PKG / "config" / "camera_nominal_pinky_pro.yaml").read_text(encoding="utf-8"))


def _plane(width=320, height=240, **kw):
    args = dict(source="NOMINAL", allowed=True, width_px=width, height_px=height, profile=PROFILE)
    args.update(kw)
    return nominal_ground_plane(**args)


def test_profile_reproduces_measured_horizon_and_scales_with_frame():
    assert _plane().horizon_row == pytest.approx(80.3, abs=0.3)
    big = _plane(640, 480)
    assert big.horizon_row == pytest.approx(160.6, abs=0.6)
    assert big.distance(big.principal_y) == pytest.approx(_plane().distance(120), rel=1e-6)


@pytest.mark.parametrize("kw", [dict(source="PINKY"), dict(source="GAZEBO"), dict(allowed=False),
                                dict(allowed="true"), dict(width=320, height=180),
                                dict(profile={"width": 320})])
def test_needs_both_opt_ins_matching_aspect_and_full_profile(kw):
    assert _plane(**kw) is None


def test_payload_labels_nominal_camera_evidence_only():
    obs = LaneObservation(error=0.1, confidence=0.8)
    assert line_observation_payload("CAMERA_LINE", 1.0, obs, ground="NOMINAL")["ground"] == "NOMINAL"
    assert "ground" not in line_observation_payload("CAMERA_LINE", 1.0, obs)
    with pytest.raises(ValueError):
        line_observation_payload("IR_LINE", 1.0, obs, ground="NOMINAL")
    with pytest.raises(ValueError):
        line_observation_payload("CAMERA_LINE", 1.0, obs, ground="GUESS")


def test_node_wires_nominal_ground_behind_read_only_opt_in():
    text = (PKG / "control" / "line_observer_node.py").read_text(encoding="utf-8")
    assert "self.declare_parameter('allow_nominal_ground', False, _READ_ONLY)" in text
    assert "nominal_ground_plane(" in text and "ground=(self._ground_label()" in text
