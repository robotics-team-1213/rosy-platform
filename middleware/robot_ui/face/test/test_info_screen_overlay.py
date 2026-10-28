"""Cards must render in the actual area reserved below the LCD status bar."""

import os
from pathlib import Path

from PIL import ImageChops
import pytest

from emotion import info_screen as I


@pytest.mark.parametrize("kind", ["info", "drive"])
def test_explicit_card_size_takes_precedence_over_the_profile(kind):
    profile = I.DisplayProfile("synthetic-panel", (480, 320), animation=False)
    image = I.render_card({"kind": kind}, size=(320, 208), profile=profile)
    assert image.size == (320, 208)


def test_card_without_an_explicit_size_uses_the_display_profile():
    profile = I.DisplayProfile("synthetic-panel", (480, 320), animation=False)
    assert I.render_card({}, profile=profile).size == profile.size


@pytest.mark.parametrize("kind", ["info", "drive"])
def test_overlay_contains_the_whole_card_drawn_for_the_expression_area(kind):
    payload = {"kind": kind, "robot_id": "fixture", "battery_percent": 73,
               "battery_voltage": 12.1, "mode": "MANUAL", "navigation": "IDLE",
               "health": "OK", "address": "http://192.0.2.7:8080", "speed": 0.12}
    box = I.expression_box()
    render = I.render_drive if kind == "drive" else I.render
    expected = render(payload, size=(box[2] - box[0], box[3] - box[1]))
    actual = I.render_overlay(payload)
    capture = os.environ.get("ROSY_FACE_CAPTURE_DIR")
    if capture:
        image = actual.copy()
        bar, mask = I.render_bar("Fixture", "ok", 73, False)
        image.paste(bar, (0, 0), mask)
        out = Path(capture)
        out.mkdir(parents=True, exist_ok=True)
        image.save(out / f"robot-face-overlay-{kind}.png")
    assert ImageChops.difference(actual.crop(box), expected).getbbox() is None
