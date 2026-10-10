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
             hidden=lambda t: (), fps=FPS):
    out = []
    for i in range(int(6.0 * fps) + 1):
        t = i / fps
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


# D-596 3: a 2-3 fps camera with a dropped frame still decodes; a one-frame flicker does not.

def test_one_dropped_frame_at_two_fps_still_matches():
    lit = lambda t: {LEFT: BLUE} if _blinking(t) else {}
    for drop in ((2.4, 2.6), (2.9, 3.1)):  # inside the off phase, and the first frame back on
        result = _decide(_samples(lit, fps=2.0, drop=[drop]))
        assert result["state"] == "matched", (drop, result)
        assert result["evidence"]["max_gap_s"] == pytest.approx(1.0)
    old = LedConfig(min_off_s=0.5, max_off_s=1.8, max_gap_s=0.7)  # D-472 start values
    assert decide(_samples(lit, fps=2.0, drop=[(2.9, 3.1)]), not_before=0.0, not_after=6.0, now=6.0,
                  config=old)["state"] == "ambiguous"


def test_a_hole_over_max_gap_is_frames_missing():
    lit = lambda t: {LEFT: BLUE} if _blinking(t) else {}
    assert _decide(_samples(lit, drop=[(1.9, 2.8)]))["reason"] == "frames_missing"  # 1.33 s hole


def test_a_one_frame_flicker_is_not_a_blink():
    flicker = lambda t: {LEFT: BLUE} if 1.0 <= t < 3.0 and not 1.9 < t < 2.1 else {}
    assert _decide(_samples(flicker))["reason"] == "none"  # off 0.67 s < min_off_s 0.8 s


def test_steady_colour_tags_the_single_anonymous_blob():
    on_late = lambda t: {LEFT: BLUE} if t >= 1.0 else {}   # turned on, never seen off again
    single = _decide(_samples(on_late, blobs=(LEFT,)))
    assert single["state"] == "matched" and single["evidence"]["mode"] == "steady"
    assert (single["x"], single["y"]) == (LEFT.map_x, LEFT.map_y)
    assert _decide(_samples(on_late))["reason"] == "none"                     # two blobs: no tag
    assert _decide(_samples(lambda t: {LEFT: BLUE}, blobs=(LEFT,)))["reason"] == "none"  # never off
    blink = _decide(_samples(lambda t: {LEFT: BLUE} if _blinking(t) else {}, blobs=(LEFT,)))
    assert blink["state"] == "matched" and "mode" not in blink["evidence"]  # the blink wins


def test_a_caution_lamp_decodes_like_the_amber_identify():
    """D-596 7: caution is amber 1 s on / 1 s off, so Vision alone cannot tell it from an amber identify.
    Fleet therefore never asks amber automatically and gates the verdict on the asked robot's place."""
    caution = lambda t: {RIGHT: AMBER} if int(t) % 2 == 0 else {}
    decoy = _decide(_samples(caution, color="amber"))
    assert decoy["state"] == "matched" and (decoy["x"], decoy["y"]) == (RIGHT.map_x, RIGHT.map_y)
    assert _decide(_samples(caution, color="blue"))["reason"] == "none"


def test_a_dim_floor_glow_beside_the_robot_is_read():
    """led-identity/3, site ceiling_north 2026-10-10 11:23 (rosy_40 asked blue): the lamp lights the
    floor ~1.8 blob radii from the robot centre, pale (HSV ~120/85/135). The /2 ring (to 1.6 r) and
    floors (S 110, V 150) read 0.0005 on vs 0.0 off and answered "none"."""
    glow = (135, 90, 90)                                          # BGR of HSV (120, 85, 135)

    def frame(on: bool) -> np.ndarray:
        image = np.full((240, 320, 3), 90, np.uint8)
        if on:
            x, y = int(LEFT.x_px + 1.8 * LEFT.radius_px), int(LEFT.y_px)
            image[y - 7:y + 7, x - 9:x + 9] = glow
        return image

    samples = [sample_frame(frame(_blinking(i / FPS)), captured_at=i / FPS, calibration_revision="r",
                            blobs=(LEFT, RIGHT), color="blue") for i in range(19)]
    result = _decide(samples)
    assert result["state"] == "matched" and (result["x"], result["y"]) == (LEFT.map_x, LEFT.map_y)
    old = LedConfig(min_saturation=110, min_value=150, ring_outer=1.6)
    assert decide([sample_frame(frame(_blinking(i / FPS)), captured_at=i / FPS, calibration_revision="r",
                                blobs=(LEFT, RIGHT), color="blue", config=old) for i in range(19)],
                  not_before=0.0, not_after=6.0, now=6.0, config=old)["reason"] == "none"
