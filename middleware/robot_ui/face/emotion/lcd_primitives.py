"""LCD fonts, measurements, QR drawing and panel packing; no ROS or hardware."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

from . import wifi_qr


DEFAULT_HOLD_S = 15.0

def hold_duration(raw: object) -> float:
    """Return a finite positive wake-card duration; malformed input gets the default."""
    if isinstance(raw, bool):
        return DEFAULT_HOLD_S
    try:
        duration = float(raw)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_HOLD_S
    return duration if math.isfinite(duration) and duration > 0 else DEFAULT_HOLD_S

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

def _font(size: int) -> ImageFont.ImageFont:
    """설치된 트루타입을 우선 쓰고, 없으면 기본 폰트로 떨어진다."""
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:      # Pillow < 10.1 — 크기 지정 불가
        return ImageFont.load_default()

def battery_measurement(raw: object, *, percent: bool = False) -> float | None:
    """Accept only a finite measured value; invalid input is missing evidence."""
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value < 0 or (percent and value > 100):
        return None
    return value

_MIN_FONT = 11

_QR_BOX = 148

_QR_QUIET = 2

_QR_TOP = 28

_QR_GAP = 6

_QR_DARK = (0, 0, 0)          # token-exempt: QR modules need full black/white contrast

_QR_LIGHT = (255, 255, 255)   # token-exempt: QR quiet zone

def ap_qr(payload: dict) -> list[list[bool]] | None:
    """The AP join matrix; only explicit open security may omit the key.

    Keys in a matrix are drawn only, never logged; oversized payloads give None.
    """
    network = payload.get("network") or {}
    login, ssid = payload.get("ap_login"), network.get("ssid")
    if network.get("mode") != "ap" or not ssid or (not login and network.get("security") != "open"):
        return None
    try:
        return wifi_qr.encode(wifi_qr.wifi_payload(str(ssid), str(login or ""),
                                                security=network.get("security", "wpa2")))
    except ValueError:
        return None

def _draw_qr(draw: ImageDraw.ImageDraw, matrix: list[list[bool]], width: int) -> tuple[int, int]:
    """Draw ``matrix`` right-aligned below the header; (left x, bottom y) of its box."""
    modules = len(matrix) + 2 * _QR_QUIET
    scale = max(1, _QR_BOX // modules)
    side = modules * scale
    left = width - 4 - side
    draw.rectangle((left, _QR_TOP, left + side - 1, _QR_TOP + side - 1), fill=_QR_LIGHT)
    origin_x, origin_y = left + _QR_QUIET * scale, _QR_TOP + _QR_QUIET * scale
    for row, line in enumerate(matrix):
        for column, dark in enumerate(line):
            if dark:
                x, y = origin_x + column * scale, origin_y + row * scale
                draw.rectangle((x, y, x + scale - 1, y + scale - 1), fill=_QR_DARK)
    return left, _QR_TOP + side

def _fit(draw: ImageDraw.ImageDraw, text: str, size: int, width: int):
    """(font, text): the largest font up to ``size`` that fits ``width``.

    Text that does not fit even the smallest font is cut with an ellipsis
    rather than drawn off the screen.
    """
    while size > _MIN_FONT:
        font = _font(size)
        if draw.textlength(text, font=font) <= width:
            return font, text
        size -= 1
    font = _font(_MIN_FONT)
    while len(text) > 1 and draw.textlength(text, font=font) > width:
        text = text[:-2] + "\u2026"
    return font, text

def to_panel(image: Image.Image, panel: tuple[int, int] = (240, 320)):
    """The ST7789's bytes for a landscape image: the same flip, rotation and RGB565
    packing ``rosy_lcd.LCD.img_show`` always did, as a (h, w, 2) uint8 array.

    rosy-face converts each GIF frame once with this and replays the bytes.
    """
    import numpy as np

    width, height = panel
    image = image.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.ROTATE_270)
    if image.size != (width, height):
        image = image.resize((width, height), Image.LANCZOS)
    rgb = np.asarray(image.convert("RGB"))
    pixel = np.empty((height, width, 2), dtype=np.uint8)
    pixel[..., 0] = (rgb[..., 0] & 0xF8) + (rgb[..., 1] >> 5)
    pixel[..., 1] = ((rgb[..., 1] << 3) & 0xE0) + (rgb[..., 2] >> 3)
    return pixel
