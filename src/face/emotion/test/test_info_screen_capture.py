"""D-153 G2 — 로봇 얼굴 웨이크 카드 캡처를 저장소에서 재현한다 (옵트인).

ROSY_FACE_CAPTURE_DIR 가 가리키는 폴더에 카드 4종을 PNG으로 쓴다. LCD 실물
사진(BENCH)을 대체하지 않는다 — render() PIL의 LOCAL 렌더 경로 증거다.
실행: PYTHONPATH=src/apps/emotion ROSY_FACE_CAPTURE_DIR=<폴더> python -m pytest
src/apps/emotion/test/test_info_screen_capture.py -q
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ROSY_FACE_CAPTURE_DIR"),
    reason="set ROSY_FACE_CAPTURE_DIR to write the D-153 face captures",
)

from PIL import Image  # noqa: E402

from emotion.info_screen import render  # noqa: E402

_BASE = {
    "robot_id": "rosy_01",
    "battery_percent": 73.4,
    "battery_voltage": 12.1,
    "mode": "IDLE",
    "navigation": "IDLE",
    "health": "OK",
    "estop": False,
    "address": "http://192.168.0.7:8080",
}

_CARDS = {
    "robot-face_info-card_320x240_fresh-nominal-local.png": dict(_BASE),
    "robot-face_info-card_320x240_fresh-battery-crit-local.png": dict(
        _BASE,
        battery_percent=15.0,
        battery_voltage=10.9,
        mode="NAVIGATION",
        navigation="NAVIGATING",
    ),
    "robot-face_info-card_320x240_fresh-estop-local.png": dict(_BASE, estop=True),
    "robot-face_info-card_320x240_first-boot-empty-local.png": {},
}


def test_face_captures_write_all_four_cards():
    out = Path(os.environ["ROSY_FACE_CAPTURE_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    for name, payload in _CARDS.items():
        render(payload).save(out / name)
        written = Image.open(out / name)
        assert written.size == (320, 240)
        assert written.mode == "RGB"
        pixels = set(written.getdata())
        assert len(pixels) > 1, "검정/빈 카드가 아니어야 한다"
    empty = Image.open(out / "robot-face_info-card_320x240_first-boot-empty-local.png")
    # F-04 — 결측 배터리가 0% 위경보(crit 색)로 보이면 안 된다.
    assert (196, 9, 33) not in set(empty.getdata())
