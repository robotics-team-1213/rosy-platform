"""PWR-003 정보 카드 렌더러 단위 테스트 — ROS/LCD 없이 순수 PIL."""

import pytest

from PIL import ImageChops
from pathlib import Path

from emotion.info_screen import (DEFAULT_SIZE, _BG, _CRIT, _FG, _WARN, battery_color,
                                 hold_duration, render, render_boot, render_card,
                                 render_drive)
from emotion.info_screen import DisplayProfile, PINKY_ST7789

ROOT = Path(__file__).resolve().parents[1]


def test_low_light_assist_is_white_with_visible_bulb_and_ascii_caption():
    from emotion.info_screen import render_light_assist
    image = render_light_assist()
    assert image.size == DEFAULT_SIZE
    counts = {color: count for count, color in image.getcolors(image.width * image.height)}
    assert counts[(255, 255, 255)] > image.width * image.height * 0.9
    assert image.getpixel((160, 66)) == _BG


@pytest.mark.parametrize("raw,expected", [
    (12.3, 12.3), ("3.5", 3.5), (None, 15.0), (0, 15.0),
    ("bad", 15.0), (True, 15.0), (-2, 15.0), (float("nan"), 15.0), (float("inf"), 15.0),
])
def test_info_hold_duration_always_expires(raw, expected):
    assert hold_duration(raw) == expected


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

    @pytest.mark.parametrize("percent", [float("nan"), float("inf"), -1, 101, "unknown", True])
    def test_invalid_percent_uses_missing_instead_of_a_false_alarm(self, percent):
        invalid = render(self._payload(battery_percent=percent))
        missing = render(self._payload(battery_percent=None))
        assert ImageChops.difference(invalid, missing).getbbox() is None
        assert _CRIT not in {color for _count, color in invalid.getcolors(maxcolors=1 << 16)}

    @pytest.mark.parametrize("voltage", [float("nan"), float("inf"), -1, "unknown", True])
    def test_invalid_voltage_uses_missing(self, voltage):
        invalid = render(self._payload(battery_voltage=voltage))
        missing = render(self._payload(battery_voltage=None))
        assert ImageChops.difference(invalid, missing).getbbox() is None

    def test_measured_low_and_normal_percent_keep_their_distinct_states(self):
        low = render(self._payload(battery_percent=12.0))
        normal = render(self._payload(battery_percent=73.4))
        assert _CRIT in {color for _count, color in low.getcolors(maxcolors=1 << 16)}
        assert _CRIT not in {color for _count, color in normal.getcolors(maxcolors=1 << 16)}
        assert ImageChops.difference(low, normal).getbbox() is not None

    @pytest.mark.parametrize("percent", [-20.0, 0.0, 100.0, 150.0])
    def test_renderer_handles_percent_bounds_and_invalid_values(self, percent):
        assert render(self._payload(battery_percent=percent)).size == DEFAULT_SIZE

    def test_gauge_is_painted_in_the_battery_color(self):
        # 게이지 채움 영역(좌상단 안쪽)이 실제로 잔량 색으로 칠해져야 한다.
        for percent in (5.0, 45.0, 90.0):
            image = render(self._payload(battery_percent=percent))
            assert image.getpixel((22, 113)) == battery_color(percent)

    def test_estop_payload_renders(self):
        assert render(self._payload(estop=True)).size == DEFAULT_SIZE

    def test_estop_owns_the_primary_glance_area_without_hiding_battery(self):
        stopped = render(self._payload(estop=True))
        upper_alarm = stopped.crop((12, 28, 220, 80))
        assert sum(count for count, color in upper_alarm.getcolors(maxcolors=1 << 16)
                   if color == _CRIT) > 2000
        assert _FG in {color for _count, color in upper_alarm.getcolors(maxcolors=1 << 16)}

        # Once the stop message takes the large type, the measured battery
        # still has a dedicated line above the unchanged gauge.
        lower_percent = render(self._payload(estop=True, battery_percent=37.0))
        battery_line = (12, 78, 130, 102)
        assert ImageChops.difference(stopped.crop(battery_line),
                                     lower_percent.crop(battery_line)).getbbox() is not None

    def test_estop_battery_line_distinguishes_measured_low_from_missing(self):
        measured_low = render(self._payload(estop=True, battery_percent=19.0))
        missing = render(self._payload(estop=True, battery_percent=None))
        measured_colors = {color for _count, color in measured_low.crop(
            (12, 76, 190, 103)).getcolors(maxcolors=1 << 16)}
        missing_colors = {color for _count, color in missing.crop(
            (12, 76, 190, 103)).getcolors(maxcolors=1 << 16)}
        assert _CRIT in measured_colors and _FG in measured_colors
        assert _CRIT not in missing_colors

    def test_row_labels_are_the_pinned_machine_acronyms(self):
        # D-221(F-07 처분) — 행 라벨은 기계 약어로 고정이다. 행인의 채널은
        # 글자가 아니라 형태·색·만료이고(§7.4), 라벨만 번역하면 값(enum)과
        # 어휘가 섞인다. 바꾸려면 D-221 amendment 다.
        source = (ROOT / "emotion" / "info_screen.py").read_text(encoding="utf-8")
        assert '("MODE", str(payload.get("mode")' in source
        assert '("NAV", str(payload.get("navigation")' in source
        assert '("HEALTH", str(payload.get("health")' in source

    def test_the_renderer_carries_no_font_dependency(self):
        # D-221 — 폰트 후보는 DejaVu 둘뿐. CJK 경로가 들어오는 것은 이미지에
        # 폰트를 싣는 ADR 와 같은 커밋에서만 일어날 수 있다.
        source = (ROOT / "emotion" / "info_screen.py").read_text(encoding="utf-8")
        assert source.count("_FONT_CANDIDATES") >= 1
        assert "noto" not in source.lower()
        assert "nanum" not in source.lower()
        assert "malgun" not in source.lower()

    def test_alarm_statements_are_paper_on_a_crit_fill(self):
        # D-202 의 얼굴 번역 — E-STOP 문장은 위험 채움 위 종이 잉크다. crit 글자
        # (어두운 바탕 위 2.2:1)는 경보가 제일 읽기 어려운 문장이 되게 한다.
        estop = render(self._payload(estop=True))
        box = estop.crop((88, 186, 320, 212))
        colors = {color for _count, color in box.getcolors(maxcolors=1 << 16)}
        assert _CRIT in colors and _FG in colors, sorted(colors)

    def test_critical_battery_number_is_paper_on_a_crit_fill(self):
        low = render(self._payload(battery_percent=12.0))
        box = low.crop((12, 32, 200, 100))
        colors = {color for _count, color in box.getcolors(maxcolors=1 << 16)}
        assert _CRIT in colors and _FG in colors, sorted(colors)

    def test_nominal_wake_card_spends_no_alarm_colour(self):
        # 정상(73.4%)의 웨이크 카드에는 따뜻한 색이 없다 — 색 예산은 경보가
        # 쓴다(D-82). 부팅 카드의 READY 게이트와 같은 규약.
        image = render(self._payload())
        colors = {color for _count, color in image.getcolors(maxcolors=1 << 16)}
        assert _CRIT not in colors and _WARN not in colors, sorted(colors)

    def test_calibration_marks_the_mode_row_as_a_caution_and_keeps_estop(self):
        # D-321 addendum: the robot face says CALIBRATING (ASCII font) on the MODE row.
        normal = render(self._payload())
        calibrating = render(self._payload(activity="CALIBRATING"))
        row = calibrating.crop((88, 138, 320, 164))
        colors = {color for _count, color in row.getcolors(maxcolors=1 << 16)}
        assert _WARN in colors, sorted(colors)
        assert ImageChops.difference(normal, calibrating).getbbox() is not None
        both = render(self._payload(activity="CALIBRATING", estop=True))
        health = both.crop((88, 186, 320, 212))
        assert _CRIT in {color for _count, color in health.getcolors(maxcolors=1 << 16)}

    def test_hitl_request_changes_the_health_row_but_never_overrides_estop(self):
        normal = render(self._payload())
        hitl = render(self._payload(hitl_requested=True))
        estop = render(self._payload(estop=True))
        estop_and_hitl = render(self._payload(estop=True, hitl_requested=True))

        assert ImageChops.difference(normal, hitl).getbbox() is not None
        assert ImageChops.difference(estop, estop_and_hitl).getbbox() is None

    @pytest.mark.parametrize("field,strip", [
        ("robot_id", (304, 8, 320, 34)),
        ("mode", (304, 140, 320, 165)),
        ("navigation", (304, 164, 320, 189)),
        ("health", (304, 188, 320, 213)),
        ("address", (304, 215, 320, 240)),
    ])
    def test_long_dynamic_text_preserves_right_margin(self, field, strip):
        image = render(self._payload(**{field: "LONG_VALUE_" * 20}))
        empty = render(self._payload(**{field: ""}))
        assert ImageChops.difference(image, empty).getbbox() is not None
        assert image.crop(strip).getcolors(maxcolors=1 << 16) == [
            ((strip[2] - strip[0]) * (strip[3] - strip[1]), _BG),
        ]


class TestBootCardBreathesWhileWaiting:
    """D-385: 기다리는 동안 무대 제목이 두 밝기로 숨쉬고, 끝난 상태는 고요하다."""

    def _card(self, stage, frame):
        return render_boot({"stage": stage, "device_name": "rosy"}, frame=frame)

    def test_the_waiting_title_alternates_two_brightness_steps(self):
        from PIL import ImageChops

        bright = self._card("BOOTING", frame=0)
        dark = self._card("BOOTING", frame=1)

        assert ImageChops.difference(bright, dark).getbbox() is not None

    def test_an_arrived_or_failed_card_holds_still(self):
        from PIL import ImageChops

        for stage in ("CORE_READY", "FAILED:rosy-core", "SETUP"):
            steady = ImageChops.difference(self._card(stage, frame=0), self._card(stage, frame=1))
            assert steady.getbbox() is None, stage


class TestDisplayProfile:
    """D-394: 프로파일은 그리는 쪽이 알아야 할 전부다 — 전자잉크는 숨쉬지 않는다."""

    def test_the_default_profile_is_pinky(self):
        assert PINKY_ST7789.size == (320, 240)
        assert PINKY_ST7789.animation is True

    def test_a_profile_without_animation_ignores_the_frame(self):
        from PIL import ImageChops

        e_ink = DisplayProfile("eink-sketch", (400, 300), animation=False)
        payload = {"stage": "BOOTING", "device_name": "rosy"}
        steady = ImageChops.difference(
            render_boot(payload, size=e_ink.size, frame=0, profile=e_ink),
            render_boot(payload, size=e_ink.size, frame=1, profile=e_ink))
        assert steady.getbbox() is None  # 같은 프레임 — 숨쉬지 않는다


class TestDriveCard:
    """D-394: 주행 카드 — 큰 모드 단어, 속도, 내비게이션, 배터리."""

    def _drive(self, **over):
        payload = {"kind": "drive", "robot_id": "rosy_01", "mode": "MANUAL",
                   "navigation": "NAVIGATING", "speed": 0.24,
                   "battery_percent": 87.7, "battery_voltage": 7.89,
                   "estop": False, "hold_s": 5.0}
        payload.update(over)
        return render_drive(payload), payload

    def test_mode_speed_and_battery_all_draw(self):
        image, _payload = self._drive()
        colours = image.getcolors(maxcolors=1 << 16)
        assert colours and any(count > 40 for count, colour in colours if colour != _BG)

    def test_a_different_mode_draws_differently(self):
        from PIL import ImageChops

        manual, _ = self._drive()
        navigation, _ = self._drive(mode="NAVIGATION")
        assert ImageChops.difference(manual, navigation).getbbox() is not None

    def test_a_missing_speed_is_a_quiet_placeholder_not_a_zero(self):
        from PIL import ImageChops

        with_speed, _ = self._drive()
        without, _ = self._drive(speed=None)
        assert ImageChops.difference(with_speed, without).getbbox() is not None

    def test_the_card_dispatch_picks_the_drive_kind(self):
        # kind 가 카드를 고른다 — 없으면 웨이크 카드(호환). 다른 장치의 렌더러도
        # 이 계약을 따른다. 픽셀로 비교한다: 크기만 같다고 닮은 게 아니다.
        from PIL import ImageChops

        payload = {"kind": "drive", "robot_id": "rosy_01", "mode": "MANUAL",
                   "navigation": "NAVIGATING", "speed": 0.24,
                   "battery_percent": 87.7, "estop": False}
        dispatched = render_card(payload)
        assert ImageChops.difference(dispatched, render_drive(payload)).getbbox() is None
        wake = render_card({"battery_percent": 87.7, "mode": "MANUAL"})  # kind 없음
        assert ImageChops.difference(dispatched, wake).getbbox() is not None


class TestBootCardRoseMark:
    """D-396: 부팅 카드의 Rosy 정체성 점 — 장치 이름 옆 로즈색 픽셀."""

    def _boot(self, **over):
        payload = {"stage": "BOOTING", "device_name": "rosy-pinky-8kcn",
                   "release_id": "2026.10.01-013"}
        payload.update(over)
        return render_boot(payload)

    def test_the_boot_card_has_a_rose_pixel(self):
        image = self._boot()
        rose = (246, 151, 231)  # --brand-rose #f697e7
        colours = {colour for _count, colour in image.getcolors(maxcolors=1 << 16)}
        assert rose in colours, f"로즈색 점이 없다: {sorted(c for c in colours if c != _BG)[:8]}"
