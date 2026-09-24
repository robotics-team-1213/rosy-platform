"""PWR-003 정보 카드 렌더러 단위 테스트 — ROS/LCD 없이 순수 PIL."""

import pytest

from PIL import ImageChops
from pathlib import Path

from emotion.info_screen import DEFAULT_SIZE, _CRIT, battery_color, render

ROOT = Path(__file__).resolve().parents[1]


def test_package_declares_emotion_servers():
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert "emotion_server=emotion.emotion_server:main" in setup
    package = (ROOT / "package.xml").read_text(encoding="utf-8")
    assert "<name>emotion</name>" in package


class TestBatteryColor:
    @pytest.mark.parametrize("percent,expected", [
        (100.0, (238, 238, 239)),
        (60.0, (238, 238, 239)),
        (59.9, (254, 180, 50)),
        (30.0, (254, 180, 50)),
        (29.9, (196, 9, 33)),
        (0.0, (196, 9, 33)),
    ])
    def test_thresholds(self, percent, expected):
        assert battery_color(percent) == expected


class TestRender:
    def _payload(self, **overrides):
        payload = {
            "robot_id": "rosy_01",
            "battery_percent": 73.4,
            "battery_voltage": 12.1,
            "mode": "IDLE",
            "navigation": "IDLE",
            "health": "OK",
            "estop": False,
            "address": "http://192.168.0.7:8080",
        }
        payload.update(overrides)
        return payload

    def test_default_size_and_mode(self):
        image = render(self._payload())
        assert image.size == DEFAULT_SIZE
        assert image.mode == "RGB"

    def test_custom_size(self):
        image = render(self._payload(), size=(480, 320))
        assert image.size == (480, 320)

    def test_empty_payload_still_renders(self):
        # 스냅샷이 아직 안 찼거나 필드가 비어도 화면은 반드시 나와야 한다.
        image = render({})
        assert image.size == DEFAULT_SIZE

    def test_missing_voltage_is_tolerated(self):
        assert render(self._payload(battery_voltage=None)).size == DEFAULT_SIZE

    def test_missing_battery_percent_is_not_a_critical_alarm(self):
        # 결측 배터리가 0% 위경보(crit 색)로 보이면 없는 위험을 만든다(Law 0,
        # D-153 회차3 F-04). 전압 '--' 폴백과 같은 규약이어야 한다.
        image = render(self._payload(battery_percent=None))
        assert image.size == DEFAULT_SIZE
        colors = {
            image.getpixel((x, y))
            for y in range(image.height)
            for x in range(0, image.width, 2)
        }
        assert _CRIT not in colors
        assert battery_color(0.0) == _CRIT  # 실측 0%는 여전히 위험색이다

    @pytest.mark.parametrize("percent", [-20.0, 0.0, 100.0, 150.0])
    def test_gauge_clamps_out_of_range_percent(self, percent):
        assert render(self._payload(battery_percent=percent)).size == DEFAULT_SIZE

    def test_gauge_is_painted_in_the_battery_color(self):
        # 게이지 채움 영역(좌상단 안쪽)이 실제로 잔량 색으로 칠해져야 한다.
        for percent in (5.0, 45.0, 90.0):
            image = render(self._payload(battery_percent=percent))
            assert image.getpixel((22, 113)) == battery_color(percent)

    def test_estop_payload_renders(self):
        assert render(self._payload(estop=True)).size == DEFAULT_SIZE

    def test_hitl_request_changes_the_health_row_but_never_overrides_estop(self):
        normal = render(self._payload())
        hitl = render(self._payload(hitl_requested=True))
        estop = render(self._payload(estop=True))
        estop_and_hitl = render(self._payload(estop=True, hitl_requested=True))

        assert ImageChops.difference(normal, hitl).getbbox() is not None
        assert ImageChops.difference(estop, estop_and_hitl).getbbox() is None
