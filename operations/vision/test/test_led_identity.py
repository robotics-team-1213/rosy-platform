"""D-472 LED identity detector on synthetic frames (provisional thresholds)."""

import numpy as np
import pytest

from rosy_vision.track.led_identity import Blob, LedConfig, decide, sample_frame

BLUE, AMBER = (255, 0, 0), (0, 85, 255)  # BGR: hue ~120 and ~10
LEFT = Blob(80.0, 120.0, 20.0, 0.5, 1.0)
RIGHT = Blob(240.0, 120.0, 20.0, 1.5, 1.0)
FPS = 3.0


def _blinking(t: float) -> bool:
    """rosy-face identify: on 1 s, off 1 s, on 1 s, starting 1 s into the window."""
    return 1.0 <= t < 2.0 or 3.0 <= t < 4.0


def _frame(lit: dict) -> np.ndarray:
    image = np.full((240, 320, 3), 90, np.uint8)
    for blob, color in lit.items():
        x, y = int(blob.x_px) + 22, int(blob.y_px)  # the rear lamp sits in the ring
        image[y - 4:y + 4, x - 6:x + 6] = color
    return image


def _samples(lit_at, *, blobs=(LEFT, RIGHT), color="blue", drop=(), revision=lambda t: "rev-1",
             hidden=lambda t: ()):
    out = []
    for i in range(int(6.0 * FPS) + 1):
        t = i / FPS
        if any(a <= t < b for a, b in drop):
            continue
        present = tuple(b for b in blobs if b not in hidden(t))
        out.append(sample_frame(_frame(lit_at(t)), captured_at=t, calibration_revision=revision(t),
                                blobs=present, color=color))
    return out


def _decide(samples, now=6.0):
    return decide(samples, not_before=0.0, not_after=6.0, now=now)


def test_the_one_blinking_blob_of_two_is_matched_with_evidence():
    result = _decide(_samples(lambda t: {LEFT: BLUE} if _blinking(t) else {}))
    assert result["state"] == "matched"
    assert (result["x"], result["y"]) == (LEFT.map_x, LEFT.map_y)
    found = result["evidence"]["candidates"][0]
    assert 0.5 <= found["off_s"] <= 1.8 and found["min_on_share"] > found["max_off_share"]
    assert result["evidence"]["frames"] == 19


def test_two_blobs_blinking_the_colour_is_ambiguous():
    result = _decide(_samples(lambda t: {LEFT: BLUE, RIGHT: BLUE} if _blinking(t) else {}))
    assert (result["state"], result["reason"]) == ("ambiguous", "multiple")


def test_the_wrong_colour_or_a_steady_light_does_not_match():
    amber = _decide(_samples(lambda t: {LEFT: AMBER} if _blinking(t) else {}))
    assert (amber["state"], amber["reason"]) == ("ambiguous", "none")
    steady = _decide(_samples(lambda t: {LEFT: BLUE}))
    assert steady["reason"] == "none"
    # The same amber blink is found when amber was asked for.
    asked = _decide(_samples(lambda t: {LEFT: AMBER} if _blinking(t) else {}, color="amber"))
    assert asked["state"] == "matched"


def test_occlusion_through_the_off_phase_breaks_the_chain():
    result = _decide(_samples(lambda t: {LEFT: BLUE} if _blinking(t) else {},
                              hidden=lambda t: (LEFT,) if 2.0 <= t < 3.0 else ()))
    assert (result["state"], result["reason"]) == ("ambiguous", "none")


def test_dropped_frames_stale_frames_and_recalibration_are_ambiguous():
    lit = lambda t: {LEFT: BLUE} if _blinking(t) else {}
    assert _decide(_samples(lit, drop=[(1.9, 3.1)]))["reason"] == "frames_missing"
    assert _decide(_samples(lit, drop=[(5.0, 7.0)]))["reason"] == "frames_missing"  # tail gap
    assert _decide([])["reason"] == "frames_missing"
    assert _decide(_samples(lit), now=9.0)["reason"] == "stale"
    changed = _samples(lit, revision=lambda t: "rev-1" if t < 3.0 else "rev-2")
    assert _decide(changed)["reason"] == "calibration_changed"


def test_thresholds_are_config():
    lit = lambda t: {LEFT: BLUE} if _blinking(t) else {}
    strict = LedConfig(on_fraction=0.99)
    samples = [sample_frame(_frame(lit(i / FPS)), captured_at=i / FPS, calibration_revision="r",
                            blobs=(LEFT,), color="blue", config=strict) for i in range(19)]
    assert decide(samples, not_before=0.0, not_after=6.0, now=6.0, config=strict)["reason"] == "none"
    with pytest.raises(KeyError):
        sample_frame(_frame({}), captured_at=0.0, calibration_revision="r", blobs=(LEFT,), color="red")
