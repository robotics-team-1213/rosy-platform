import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
repo = Path(__file__).resolve().parents[3]
sys.path.extend(str(repo / part) for part in ("operations/overhead", "contracts/foundation", "operations/apps/games"))
from ceiling_marker_led_yaw import combine, estimate_led
from ceiling_marker_yaw import EstimateError


def test_independent_cues_wrap_and_refuse_conflict():
    cargo = {"candidate_offset_deg": 179}
    led = {"candidate_offset_deg": -179, "led_request_id": "window"}
    assert combine(cargo, led)["cue_difference_deg"] == -2
    assert combine(None, led) == led
    with pytest.raises(EstimateError, match="disagree"):
        combine(cargo, {**led, "candidate_offset_deg": 89})


def test_stationary_marker_and_blink_from_recorded_frames():
    import cv2
    import numpy as np
    from rosy_vision.detect import generate_marker_image

    record = {"source_id": "ceiling", "map_id": "site", "calibration_revision": "r",
              "map_to_image": [500, 0, 320, 0, -500, 240, 0, 0, 1],
              "image": {"width": 640, "height": 480},
              "track_bounds_m": {"min_x": -1, "max_x": 1, "min_y": -1, "max_y": 1},
              "lens": {"kind": "standard", "focal_mm": 5.4, "hfov_deg": 67.8}}
    challenge = {"robot_id": "rosy_45", "request_id": "window", "sources": ["ceiling"],
                 "color": "blue", "not_before": 100, "not_after": 106}
    frames = []
    for i in range(25):
        image = np.full((480, 640, 3), 190, np.uint8)
        image[229:251, 309:331] = cv2.cvtColor(generate_marker_image(45, 22), cv2.COLOR_GRAY2BGR)
        cv2.circle(image, (337, 240), 4, (255, 0, 0), -1)
        if i / 4 < 1 or 2 <= i / 4 < 3:
            cv2.circle(image, (281, 240), 11, (255, 0, 0), -1)
        frames.append((100 + i / 4, cv2.imencode(".jpg", image)[1].tobytes()))
    kwargs = dict(source="ceiling", marker=45, heading_edge=(0, 1), challenge=challenge, robot="rosy_45")
    result = estimate_led(frames, record, **kwargs)
    assert result["candidate_offset_deg"] == pytest.approx(90, abs=4)
    assert result["use"] == "candidate-only"
    with pytest.raises(EstimateError, match="named blue"):
        estimate_led(frames, record, **{**kwargs, "robot": "rosy_46"})
