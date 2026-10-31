"""Cards must render in the actual area reserved below the LCD status bar."""

import os
from pathlib import Path

from PIL import ImageChops, ImageDraw
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


@pytest.mark.parametrize("name, changes", [
    ("wake", {}),
    ("wake-estop", {"estop": True, "battery_percent": 15}),
    ("wake-assist", {"activity": "CALIBRATING", "hitl_requested": True}),
    ("drive-goal", {"kind": "drive", "mode": "NAVIGATION", "navigation": "NAVIGATING",
                    "goal_x": 1.2, "goal_y": 3.4}),
    ("drive-critical", {"kind": "drive", "mode": "NAVIGATION", "navigation": "NAVIGATING",
                        "goal_x": 1.2, "goal_y": 3.4, "battery_percent": 15}),
    ("drive-charging", {"kind": "drive", "mode": "NAVIGATION", "navigation": "NAVIGATING",
                        "goal_x": 1.2, "goal_y": 3.4, "charging": True}),
])
def test_compact_card_text_is_inside_its_area_without_overlapping(monkeypatch, name, changes):
    payload = {"robot_id": "fixture", "battery_percent": 73, "battery_voltage": 12.1,
               "mode": "MANUAL", "navigation": "IDLE", "health": "OK",
               "address": "http://192.0.2.7:8080", "speed": 0.12, **changes}
    painted = []
    original = ImageDraw.ImageDraw.text

    def record(draw, xy, text, *args, **kwargs):
        painted.append((text, draw.textbbox(xy, text, font=kwargs.get("font"), anchor=kwargs.get("anchor"))))
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record)
    image = I.render_card(payload, size=(320, 208))
    for index, (text, box) in enumerate(painted):
        left, top, right, bottom = box
        assert 0 <= left < right <= image.width and 0 <= top < bottom <= image.height, (text, box)
        for other, second in painted[index + 1:]:
            overlap = min(right, second[2]) > max(left, second[0]) and min(bottom, second[3]) > max(top, second[1])
            assert not overlap, (text, box, other, second)
    capture = os.environ.get("ROSY_FACE_CAPTURE_DIR")
    if capture:
        composed = I.render_overlay(payload)
        level = "danger" if payload.get("estop") else "caution" if payload.get("hitl_requested") else "ok"
        bar, mask = I.render_bar("Fixture", level, payload["battery_percent"], payload.get("charging"))
        composed.paste(bar, (0, 0), mask)
        out = Path(capture)
        out.mkdir(parents=True, exist_ok=True)
        composed.save(out / f"robot-face-overlay-{name}.png")
