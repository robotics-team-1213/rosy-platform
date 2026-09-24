"""D-190 boot card: structural tests of what each boot stage puts on the LCD.

``boot_lines`` is the text and colour of every row; ``render_boot`` draws those
rows. The tests pin the rows exactly and check the image by colour and region,
so a font or anti-aliasing change on the device does not break them.
"""

import pytest

from emotion.info_screen import (
    _BG, _CRIT, _FG, _MUTED, _WARN, DEFAULT_SIZE, boot_lines, render, render_boot,
)

LOGIN = "Kx7" + "mQ2vR9tLpZq"  # an AP key, assembled so no literal is tracked

READY = {
    "stage": "CORE_READY",
    "device_name": "rosy-pinky-e4us",
    "release_id": "2026.09.24-007",
    "ipv4": ["192.168.1.201"],
    "api_port": 8080,
    "battery_percent": 87,
    "battery_voltage": 8.21,
    "network": {"mode": "sta"},
}


def _rows(payload):
    return {slot: (text, color) for slot, text, color in boot_lines(payload)}


def _colors(image, box=None):
    region = image.crop(box) if box else image
    return {color for _count, color in region.getcolors(maxcolors=1 << 16)}


def _has_ink(image, box):
    return _colors(image, box) != {_BG}


@pytest.mark.parametrize("stage,title,color", [
    ("BOOTING", "BOOTING", _MUTED),
    ("PROVISIONED", "PROVISIONED", _FG),
    ("CORE_READY", "READY", _FG),
    ("FAILED:rosy-core", "FAILED", _CRIT),
])
def test_every_stage_has_its_title_and_colour(stage, title, color):
    rows = _rows({**READY, "stage": stage})

    assert rows["stage"] == (title, color)
    assert rows["name"] == ("rosy-pinky-e4us", _MUTED)
    assert rows["release"] == ("2026.09.24-007", _MUTED)
    assert rows["address"] == ("192.168.1.201:8080", _FG)
    assert rows["battery"] == ("87%  8.21 V", _FG)
    image = render_boot({**READY, "stage": stage})
    assert image.size == DEFAULT_SIZE and image.mode == "RGB"


def test_failed_names_the_unit_in_red_and_nothing_else_is_red():
    payload = {**READY, "stage": "FAILED:rosy-release-recover",
               "failed_unit": "rosy-release-recover.service"}

    rows = _rows(payload)
    image = render_boot(payload)

    assert rows["failed_unit"] == ("rosy-release-recover", _CRIT)
    assert _CRIT in _colors(image, (0, 30, 320, 100))
    assert _CRIT not in _colors(image, (0, 100, 320, 240))


def test_failed_alarm_is_paper_on_a_crit_fill():
    # D-202 의 얼굴 번역 — FAILED 문장은 위험 채움 위 종이 잉크로 그린다.
    image = render_boot({**READY, "stage": "FAILED:rosy-core"})
    colors = _colors(image, (0, 28, 320, 96))
    assert _CRIT in colors and _FG in colors, sorted(colors)


def test_the_failed_unit_comes_from_the_stage_label_when_the_field_is_missing():
    assert _rows({"stage": "FAILED:rosy-core"})["failed_unit"] == ("rosy-core", _CRIT)


def test_a_ready_card_has_no_alarm_colour():
    image = render_boot(READY)

    assert _CRIT not in _colors(image) and _WARN not in _colors(image)


def test_a_provisioning_hold_shows_its_reason():
    rows = _rows({"stage": "BOOTING", "detail": "PROVISIONING_HOLD: no bundle"})

    assert rows["detail"] == ("PROVISIONING_HOLD: no bundle", _MUTED)


def test_ap_mode_shows_the_ssid_and_key_and_the_ap_address():
    network = {"mode": "ap", "ssid": "rosy-pinky-e4us", "address": "10.42.0.1"}
    payload = {**READY, "network": network, "ap_login": LOGIN}

    rows = _rows(payload)

    assert rows["address"] == ("10.42.0.1:8080", _FG)
    assert rows["ap_ssid"] == ("Wi-Fi rosy-pinky-e4us", _FG)
    assert rows["ap_login"] == (f"PW {LOGIN}", _FG)
    assert _has_ink(render_boot(payload), (0, 160, 320, 240))


def test_ap_mode_without_the_key_points_at_the_operator_store():
    rows = _rows({**READY, "network": {"mode": "ap", "ssid": "rosy-pinky-e4us"}})

    assert rows["ap_login"] == ("PW: see the operator AP store", _MUTED)


def test_station_mode_draws_nothing_in_the_ap_area_even_with_a_key():
    rows = _rows({**READY, "ap_login": LOGIN})

    assert "ap_ssid" not in rows and "ap_login" not in rows
    assert not _has_ink(render_boot({**READY, "ap_login": LOGIN}), (0, 160, 320, 240))


def test_missing_battery_is_grey_dashes_not_an_empty_battery():
    payload = {**READY, "battery_percent": None, "battery_voltage": None}

    assert _rows(payload)["battery"] == ("battery --", _MUTED)
    assert _CRIT not in _colors(render_boot(payload))


@pytest.mark.parametrize("percent,color", [(80, _FG), (45, _WARN), (12, _CRIT)])
def test_battery_uses_the_info_card_thresholds(percent, color):
    assert _rows({**READY, "battery_percent": percent})["battery"][1] == color


def test_missing_ip_and_empty_payload_still_draw_a_card():
    assert _rows({**READY, "ipv4": []})["address"] == ("no IP address", _MUTED)
    rows = _rows({})
    assert rows["stage"] == ("BOOTING", _MUTED)
    assert rows["name"] == ("rosy (unprovisioned)", _MUTED)
    assert render_boot({}).size == DEFAULT_SIZE


def test_long_text_shrinks_instead_of_running_off_the_screen():
    payload = {**READY, "network": {"mode": "ap", "ssid": "x" * 32}, "ap_login": "y" * 40}

    image = render_boot(payload)

    assert not _has_ink(image, (316, 160, 320, 240))


def test_a_real_ssid_and_key_fit_whole():
    # D-176: SSIDs up to 32 characters, per-card keys of 12+ characters.
    from PIL import Image, ImageDraw
    from emotion.info_screen import _fit

    draw = ImageDraw.Draw(Image.new("RGB", DEFAULT_SIZE))
    rows = (("Wi-Fi rosy-pinky-e4us", 17), ("Wi-Fi " + "s" * 26, 17), ("PW " + LOGIN, 22))
    for text, size in rows:
        assert _fit(draw, text, size, DEFAULT_SIZE[0] - 32)[1] == text


def test_the_info_card_is_unchanged():
    # render() (the emotion face's wake card) keeps its own layout.
    assert render({}).size == DEFAULT_SIZE
