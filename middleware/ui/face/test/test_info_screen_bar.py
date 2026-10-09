"""D-433 amendment (2026-10-09): the status bar over the expression area."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
import pytest

from emotion import info_screen as I

SIZE = I.DEFAULT_SIZE
BAR_BOX = (0, 0, SIZE[0], I.BAR_HEIGHT)


def _bar(text="Waiting", level="ok", percent=80.0, charging=False):
    return I.render_bar(text, level, percent, charging)


def _colours(image, box):
    return set(image.crop(box).getdata())


def test_the_bar_owns_the_top_rows_and_nothing_else():
    _image, mask = _bar()
    assert mask.size == SIZE and mask.getbbox() == BAR_BOX
    assert I.expression_box() == (0, I.BAR_HEIGHT, SIZE[0], SIZE[1])


@pytest.mark.parametrize("level, fill", [("ok", I._BG), ("caution", I._WARN), ("danger", I._CRIT)])
def test_the_level_is_the_whole_bar_colour(level, fill):
    image, _mask = _bar(level=level)
    assert image.getpixel((SIZE[0] // 2, 4)) == fill and image.getpixel((2, 2)) == fill


def test_a_long_text_is_fitted_and_never_leaves_the_bar():
    image, _mask = _bar(text="Recovering: returning to lane", level="caution", percent=100.0, charging=True)
    below = image.crop((0, I.BAR_HEIGHT, SIZE[0], SIZE[1]))
    assert _colours(below, (0, 0, SIZE[0], SIZE[1] - I.BAR_HEIGHT)) == {I._BG}
    text_columns = [x for x in range(8, SIZE[0] - 80) for y in range(I.BAR_HEIGHT)
                    if image.getpixel((x, y)) == I._BG]
    assert text_columns  # drawn left of the battery group


def test_unknown_battery_is_dashes_and_an_empty_outline_never_zero_percent():
    unknown, _ = _bar(percent=None)
    zero, _ = _bar(percent=0.0)
    assert unknown.tobytes() != zero.tobytes()
    assert I._MUTED in _colours(unknown, (SIZE[0] - 30, 4, SIZE[0] - 4, I.BAR_HEIGHT - 4))  # quiet, not an alarm
    assert I._CRIT not in _colours(unknown, BAR_BOX)


def test_battery_fill_grows_with_the_charge_and_charging_marks_the_icon():
    body = (SIZE[0] - 34, 8, SIZE[0] - 10, I.BAR_HEIGHT - 8)

    def lit(percent):
        return sum(1 for pixel in _bar(percent=percent)[0].crop(body).getdata() if pixel == I._FG)

    assert lit(100.0) > lit(50.0) > lit(10.0)
    plain, bolt = _bar(percent=60.0)[0], _bar(percent=60.0, charging=True)[0]
    assert plain.crop(body).tobytes() != bolt.crop(body).tobytes()


def test_a_low_battery_never_paints_crit_on_the_dark_bar():
    image, _ = _bar(percent=5.0)  # ok level with a crit charge: ink on ground, not 2.2:1 red
    assert I._CRIT not in _colours(image, BAR_BOX)


def test_the_expression_area_is_the_gif_cut_not_scaled():
    frame = Image.new("RGB", SIZE, (0, 0, 0))
    frame.putpixel((10, I.FACE_CROP_TOP), (1, 2, 3))      # the first cut row lands at the area's top
    frame.putpixel((10, I.FACE_CROP_TOP - 1), (9, 9, 9))  # above the cut: gone
    face = I.compose_face(frame)
    assert face.size == SIZE and face.getpixel((10, I.BAR_HEIGHT)) == (1, 2, 3)
    assert (9, 9, 9) not in set(face.getdata())
    assert face.getpixel((0, 0)) == I._BG  # the bar's rows are left for the bar


def test_the_real_faces_fit_the_cut():
    import numpy as np

    area = I.expression_box()[3] - I.BAR_HEIGHT
    for gif in sorted(Path(I.__file__).parent.glob("*.gif")):
        image = Image.open(gif)
        for index in range(image.n_frames):
            image.seek(index)
            ink = np.where(np.asarray(image.convert("RGB")).sum(axis=2) > 60)[0]
            assert not len(ink) or (ink.min() >= I.FACE_CROP_TOP and ink.max() < I.FACE_CROP_TOP + area), gif.name


def test_a_drive_card_takes_the_expression_area_and_leaves_the_bar_rows():
    image = I.render_overlay({"kind": "drive", "robot_id": "rosy", "mode": "NAVIGATION",
                              "navigation": "NAVIGATING", "battery_percent": 64})
    assert image.size == SIZE and _colours(image, BAR_BOX) == {I._BG}
    assert len(_colours(image, (0, I.BAR_HEIGHT, SIZE[0], SIZE[1]))) > 1
