"""emotion.info_screen — PWR-003 정보 카드 렌더러.

ROS 무의존. display/info JSON 페이로드 → PIL 이미지 한 장.
LCD는 이 이미지를 회전/리사이즈해 출력하므로 여기서는 GIF 프레임과 같은
가로 방향(기본 320x240)으로 그린다.

``render_boot``는 부팅 카드다(D-190). CORE 밖의 ``rosy-boot-display``가
``/run/rosy-boot`` 상태로 그린다. 같은 팔레트(D-82)를 쓴다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from . import wifi_qr


@dataclass(frozen=True)
class DisplayProfile:
    """D-394: 한 장치의 화면이 무엇인지. 카드 모델(페이로드)은 장치를 모른다.

    재사용 단위는 페이로드 계약이고, 이 프로파일은 그리는 쪽이 알아야 할 전부다:
    크기와, 움직임을 그려도 되는가. 전자잉크(``animation=False``)는 부분 갱신이
    느려 숨쉬지 않는다 — 렌더러는 프레임을 무시하고 고정 프레임을 그린다. 색은
    모듈의 토큰 사본(D-82/D-194)이 유일한 출처다: 장치마다 팔레트를 새로 정의하지
    않는다.
    """

    name: str
    size: tuple[int, int]
    animation: bool = True


#: Pinky Pro의 ST7789 — 320x240 가로, 숨쉬는 카드를 그릴 수 있다.
PINKY_ST7789 = DisplayProfile("pinky-st7789", (320, 240))
DEFAULT_PROFILE = PINKY_ST7789
DEFAULT_SIZE = DEFAULT_PROFILE.size
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

# concept 16 L1 / D-82 / D-194 — 색은 토큰과 같은 값이다. 이 모듈은 파일을
# 읽지 않고 튜플만 가진다. 숫자가 토큰과 어긋나면
# web_common/test/test_shared_controls.py 가 실패한다.
#
# 이전 값은 적록 색약 시야에서 _WARN 대 _CRIT 대비가 1.26:1이었다 — 얼굴은
# 1.5m 밖에서 0.5초에 읽히는 화면인데 주의와 위험이 구분되지 않았다.
#
# 정상에는 색이 없다: 배터리가 넉넉할 때는 잉크로 쓴다. 초록을 쓰면 화면
# 대부분이 색을 갖게 되고 임계 경보가 눈에 띌 대비 예산이 남지 않는다.
_BG = (16, 18, 20)          # --ground   #101214
_FG = (238, 238, 239)       # --ink        #eeeeef
_MUTED = (148, 153, 160)    # --ink-quiet  #9499a0
_NOMINAL = _FG              # --nominal  정상은 잉크다
_WARN = (254, 180, 50)      # --status-warn #feb432
_CRIT = (196, 9, 33)        # --status-crit #c40921

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


def battery_color(percent: float) -> tuple[int, int, int]:
    if percent >= 60.0:
        return _NOMINAL
    if percent >= 30.0:
        return _WARN
    return _CRIT


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


def _draw_alarm(draw: ImageDraw.ImageDraw, xy, text: str, font) -> None:
    """경보 문장은 채움이다(D-202 의 얼굴 번역).

    얼굴은 1.5m 밖에서 0.5초에 읽히는 화면이다. crit 글자는 어두운 바탕 위에서
    2.2:1 로 읽히지 않는다 — 위험을 알리는 문장이 제일 읽기 어려운 문장이 되는
    것은 계기의 역할과 반대다. 위험 채움 위에 종이 잉크로 얹는다(웹 표면의
    ui-tag[status=crit]·E-Stop 와 같은 얼굴).
    """
    x, y = xy
    left, _top, right, bottom = draw.textbbox((x, y), text, font=font)
    pad = 4
    draw.rounded_rectangle(
        # 하단 여백은 2px 로 짧게 — 칩이 다음 줄의 영역(y=100 경계 같은)을
        # 침범하면 '그 아래는 위험색이 아니다' 계약이 부러진다.
        (left - pad, y - pad, right + pad, bottom + 2), radius=4, fill=_CRIT
    )
    draw.text((x, y), text, font=font, fill=_FG)


def _draw_caution(draw: ImageDraw.ImageDraw, xy, text: str, font) -> None:
    """주의 문장도 채움이다 — 도움 요청은 OK 와 같은 무게로 읽히지 않는다.

    warn 채움 위에 ground 잉크(#feb432 대비 10:1 이상)로 얹는다. crit 칩과
    형태는 같고 색만 다른 어휘다.
    """
    x, y = xy
    left, _top, right, bottom = draw.textbbox((x, y), text, font=font)
    pad = 4
    draw.rounded_rectangle(
        (left - pad, y - pad, right + pad, bottom + 2), radius=4, fill=_WARN
    )
    draw.text((x, y), text, font=font, fill=_BG)


def render(payload: dict, size: tuple[int, int] = DEFAULT_SIZE) -> Image.Image:
    """웨이크 정보 카드. 값이 없으면 '--'로 두고 화면은 반드시 그린다."""
    width, height = size
    image = Image.new("RGB", size, _BG)
    draw = ImageDraw.Draw(image)

    raw_percent = battery_measurement(payload.get("battery_percent"), percent=True)
    voltage = battery_measurement(payload.get("battery_voltage"))
    has_percent = raw_percent is not None
    # 결측은 0%가 아니다 — 결측을 crit 색 경보로 그리면 없는 위험을 만든다
    # (Law 0). 전압의 '--' 폴백과 같은 규약을 쓴다.
    percent = raw_percent if has_percent else 0.0
    color = battery_color(percent) if has_percent else _MUTED

    robot_id = str(payload.get("robot_id") or "rosy")
    robot_font, robot_id = _fit(draw, robot_id, 18, width - 32)
    draw.text((16, 10), robot_id, font=robot_font, fill=_MUTED)

    if payload.get("estop"):
        # A stopped robot must be recognized before its charge level. Keep
        # the measured battery on a separate line above the existing gauge.
        _draw_alarm(draw, (16, 34), "E-STOP", _font(36))
        battery_text = f"BATTERY {percent:.0f}%" if has_percent else "BATTERY --"
        if has_percent and color == _CRIT:
            _draw_alarm(draw, (16, 80), battery_text, _font(18))
        else:
            draw.text((16, 80), battery_text, font=_font(18), fill=color)
        voltage_y = 95
    else:
        if has_percent:
            if color == _CRIT:
                _draw_alarm(draw, (16, 36), f"{percent:.0f}%", _font(56))
            else:
                draw.text((16, 36), f"{percent:.0f}%", font=_font(56), fill=color)
        else:
            draw.text((16, 36), "--", font=_font(56), fill=_MUTED)
        voltage_y = 60
    draw.text((width - 16, voltage_y), "--" if voltage is None else f"{float(voltage):.2f} V",
              font=_font(20), fill=_MUTED, anchor="rs")

    # 배터리 게이지
    bar_x, bar_y, bar_w, bar_h = 16, 104, width - 32, 18
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                           radius=6, outline=_MUTED, width=2)
    filled = int(bar_w * max(0.0, min(100.0, percent)) / 100.0)
    if filled > 4:
        draw.rounded_rectangle((bar_x, bar_y, bar_x + filled, bar_y + bar_h),
                               radius=6, fill=color)

    rows = [
        ("MODE", str(payload.get("mode") or "--")),
        ("NAV", str(payload.get("navigation") or "--")),
        ("HEALTH", str(payload.get("health") or "--")),
    ]
    if payload.get("estop"):
        rows[2] = ("HEALTH", "E-STOP")
    elif payload.get("hitl_requested"):
        rows[2] = ("HEALTH", "ASSIST REQ")
    # D-321 addendum: a calibration lease replaces the mode value. The LCD font is
    # ASCII-only (D-221), so the machine word stands in for "보정 중".
    if payload.get("activity") == "CALIBRATING":
        rows[0] = ("MODE", "CALIBRATING")

    for index, (label, value) in enumerate(rows):
        y = 142 + index * 24
        draw.text((16, y), label, font=_font(14), fill=_MUTED)
        if value == "E-STOP":
            _draw_alarm(draw, (92, y), value, _font(16))
        elif value in ("ASSIST REQ", "CALIBRATING"):
            _draw_caution(draw, (92, y), value, _font(16))
        else:
            value_font, value = _fit(draw, value, 16, width - 108)
            draw.text((92, y), value, font=value_font, fill=_FG)

    address = str(payload.get("address") or "")
    if address:
        address_font, address = _fit(draw, address, 14, width - 32)
        draw.text((width // 2, height - 14), address,
                  font=address_font, fill=_MUTED, anchor="ms")

    return image


# --- D-394: drive card -----------------------------------------------------
#
# 주행 카드는 운용 중에 20 s 마다 얼굴 위로 잠깐 지나간다(CORE의 drive_due).
# 웨이크 카드가 "로봇 전체 진단"이라면 주행 카드는 "지금 이 동작"이다:
# 큰 모드 단어 하나, 속도 한 줄, 배터리 한 줄. 읽는 사람은 1 m 밖에서
# 로봇을 따라가는 중이다 — 세 글자 이상 읽게 하면 이미 지나갔다.


def render_drive(payload: dict, size: tuple[int, int] = DEFAULT_SIZE) -> Image.Image:
    """주행 카드: 모드(큰 글자) · 속도 · 내비게이션 · 배터리. 값이 없으면 '--'."""
    width, height = size
    image = Image.new("RGB", size, _BG)
    draw = ImageDraw.Draw(image)

    robot_id = str(payload.get("robot_id") or "rosy")
    robot_font, robot_id = _fit(draw, robot_id, 18, width - 32)
    draw.text((16, 10), robot_id, font=robot_font, fill=_MUTED)

    mode = str(payload.get("mode") or "--")
    if payload.get("estop"):
        _draw_alarm(draw, (16, 40), "E-STOP", _font(52))
    else:
        mode_font, mode = _fit(draw, mode, 52, width - 32)
        draw.text((16, 40), mode, font=mode_font, fill=_CRIT if mode == "EMERGENCY" else _FG)

    speed = payload.get("speed")
    speed_text = f"{float(speed):.2f} m/s" if isinstance(speed, (int, float)) else "-- m/s"
    draw.text((16, 108), "SPEED", font=_font(14), fill=_MUTED)
    draw.text((92, 104), speed_text, font=_font(20), fill=_FG)
    draw.text((16, 136), "NAV", font=_font(14), fill=_MUTED)
    nav_font, nav = _fit(draw, str(payload.get("navigation") or "--"), 16, width - 108)
    draw.text((92, 136), nav, font=nav_font, fill=_FG)

    # 배터리: 웨이크 카드와 같은 게이지 규약 — 결측은 경보가 아니라 침묵이다.
    raw_percent = battery_measurement(payload.get("battery_percent"), percent=True)
    percent = raw_percent if raw_percent is not None else 0.0
    color = battery_color(percent) if raw_percent is not None else _MUTED
    bar_x, bar_y, bar_w, bar_h = 16, height - 44, width - 32, 18
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                           radius=6, outline=_MUTED, width=2)
    filled = int(bar_w * max(0.0, min(100.0, percent)) / 100.0)
    if filled > 4:
        draw.rounded_rectangle((bar_x, bar_y, bar_x + filled, bar_y + bar_h),
                               radius=6, fill=color)
    if raw_percent is not None:
        draw.text((width - 16, bar_y - 24), f"{percent:.0f}%", font=_font(16),
                  fill=color, anchor="rs")

    return image


def render_card(payload: dict, size: tuple[int, int] = DEFAULT_SIZE,
                profile: DisplayProfile = DEFAULT_PROFILE) -> Image.Image:
    """D-394: display/info 의 단일 입구 — kind 가 카드를 고른다.

    CORE 는 ``kind`` 필드로 카드를 구분한다(없으면 웨이크 카드, 호환).
    다른 장치의 렌더러도 이 디스패치와 같은 계약을 따른다.
    """
    if payload.get("kind") == "drive":
        return render_drive(payload, profile.size)
    return render(payload, profile.size)


# --- D-190: boot card -----------------------------------------------------
#
# rosy-boot-display.service draws this outside CORE (D-161) from the boot
# indicator's files, so it also shows BOOTING, PROVISIONED and FAILED, when
# CORE does not exist. Normal has no colour (D-82): only FAILED is red.

_STAGE_TITLES = {
    "BOOTING": "BOOTING",
    "PROVISIONED": "PROVISIONED",
    "CORE_READY": "READY",
    "FAILED": "FAILED",
}
_MIN_FONT = 11

# (slot, y, font size) in draw order; the slot names are what boot_lines returns.
_BOOT_LAYOUT = {
    "name": (8, 18),
    "release": (12, 13),
    "stage": (32, 34),
    "failed_unit": (74, 18),
    "detail": (76, 13),
    "address": (100, 20),
    "battery": (130, 20),
    # D-260 4: the robot state line and the most urgent todo (the todo slot
    # gives way to the AP rows, which a person needs first to reach the robot).
    "robot_state": (154, 16),
    "todo": (176, 15),
    "ap_ssid": (176, 16),
    "ap_login": (196, 20),
    "login": (218, 18),
}
#: While the AP is open the card also draws its Wi-Fi join QR (wifi_qr), right-aligned
#: between the header and the AP rows: black on white with a 2-module quiet zone, at
#: the largest whole pixels per module that fit _QR_BOX (a version-4 code: 4 px, 148 px,
#: about 22 mm on the 2.4-inch panel). Rows beside it keep to the left column.
_QR_BOX = 148
_QR_QUIET = 2
_QR_TOP = 28
_QR_GAP = 6
_QR_DARK = (0, 0, 0)          # token-exempt: QR modules need full black/white contrast
_QR_LIGHT = (255, 255, 255)   # token-exempt: QR quiet zone
#: D-260: the state line's colour; failed is the alarm fill, like FAILED above.
_STATE_COLOURS = {"failed": _CRIT, "caution": _WARN, "booting": _MUTED}


def boot_lines(payload: dict) -> list[tuple[str, str, tuple[int, int, int]]]:
    """(slot, text, colour) rows of the boot card; pure, for tests and render_boot.

    Keys: ``device_name``, ``release_id``, ``stage`` (``FAILED:<unit>`` label),
    ``failed_unit``, ``detail``, ``ipv4`` (list), ``api_port``,
    ``battery_percent``, ``battery_voltage``, ``network`` (``mode``/``ssid``/
    ``address``), ``ap_login`` (the AP key line, AP mode only) and, at
    CORE_READY only, ``login_code``/``login_role`` (D-193's one-time dashboard
    code) or ``login_burned``. Missing values never stop the card.
    """
    stage = str(payload.get("stage") or "BOOTING")
    kind = stage.split(":", 1)[0]
    failed = kind == "FAILED"
    stage_color = _CRIT if failed else (_MUTED if kind == "BOOTING" else _FG)
    lines = [
        ("name", str(payload.get("device_name") or "rosy (unprovisioned)"), _MUTED),
        ("release", str(payload.get("release_id") or "release ?"), _MUTED),
        ("stage", _STAGE_TITLES.get(kind, kind), stage_color),
    ]
    unit = payload.get("failed_unit")
    if failed and not unit and ":" in stage:
        unit = stage.split(":", 1)[1]
    if failed and unit:
        lines.append(("failed_unit", str(unit).rsplit(".service", 1)[0], _CRIT))
    elif payload.get("detail"):
        lines.append(("detail", str(payload["detail"]), _MUTED))

    network = payload.get("network") or {}
    ap_mode = network.get("mode") == "ap"
    port = payload.get("api_port") or 8080
    addresses = [str(address) for address in payload.get("ipv4") or []]
    if ap_mode and network.get("address"):
        addresses = [str(network["address"])]
    if addresses:
        lines.append(("address", f"{addresses[0]}:{port}", _FG))
    else:
        lines.append(("address", "no IP address", _MUTED))

    percent = battery_measurement(payload.get("battery_percent"), percent=True)
    voltage = battery_measurement(payload.get("battery_voltage"))
    if percent is None or voltage is None:
        lines.append(("battery", "battery --", _MUTED))
    else:
        lines.append(("battery", f"{percent:.0f}%  {voltage:.2f} V",
                      battery_color(percent)))

    # D-260 4: ``state_line`` / ``todo`` come from core_common.robot_state (LCD
    # form, ASCII: the DejaVu card font has no Hangul). Absent on an old release.
    if payload.get("state_line"):
        lines.append(("robot_state", str(payload["state_line"]),
                      _STATE_COLOURS.get(str(payload.get("robot_state")), _FG)))
    if payload.get("todo") and not ap_mode:
        lines.append(("todo", f"> {payload['todo']}", _FG))

    if ap_mode:
        lines.append(("ap_ssid", f"Wi-Fi {network.get('ssid') or '?'}", _FG))
        login = payload.get("ap_login")
        if login:
            lines.append(("ap_login", f"PW {login}", _FG))
        else:
            lines.append(("ap_login", "PW: see the operator AP store", _MUTED))

    if kind == "CORE_READY":
        if payload.get("login_code"):
            lines.append(("login", f"Login {payload['login_code']} {payload.get('login_role') or ''}".rstrip(),
                          _FG))
        elif payload.get("login_burned"):
            lines.append(("login", "Login code burned", _CRIT))
    return lines


def ap_qr(payload: dict) -> list[list[bool]] | None:
    """The AP's Wi-Fi join matrix, only while the AP is open and its SSID and key are known.

    None otherwise, and for a payload too long for the encoder (the text rows
    still show it). Holds the key: drawn, never logged.
    """
    network = payload.get("network") or {}
    login, ssid = payload.get("ap_login"), network.get("ssid")
    if network.get("mode") != "ap" or not login or not ssid:
        return None
    try:
        return wifi_qr.encode(wifi_qr.wifi_payload(str(ssid), str(login)))
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


def _dim(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """D-385: 무대 제목의 어두운 국면 — 같은 색, 45 % 밝기. 숨쉼의 한 단계다."""
    return tuple(int(component * 0.45) for component in color)


def render_boot(payload: dict, size: tuple[int, int] = DEFAULT_SIZE,
                frame: int = 0, profile: DisplayProfile = DEFAULT_PROFILE) -> Image.Image:
    """Boot card: name, release, stage (failed unit), address, battery, AP (and its QR).

    D-385: while the stage is still waiting (BOOTING·PROVISIONED) the stage title
    breathes — two brightness steps at the caller's frame rate (0.5 Hz on the
    device). Finished states (CORE_READY·FAILED·SETUP) hold still: an arrived
    robot does not fidget. D-394: a profile without animation (e-ink) ignores
    the frame entirely.
    """
    width, _height = size
    image = Image.new("RGB", size, _BG)
    draw = ImageDraw.Draw(image)
    # D-396: Rosy 정체성 마크 — 장치 이름 옆 작은 로즈색 점. "The rose colour
    # is for the ROSY name only"(D-82). 부팅 카드 어디를 보고 있는지 한눈에.
    _rose = (227, 27, 93, 255)  # --rose #e31b5d
    draw.ellipse((4, 12, 12, 20), fill=_rose[:3])
    matrix = ap_qr(payload)
    qr_left, qr_bottom = _draw_qr(draw, matrix, width) if matrix else (width, 0)
    lines = boot_lines(payload)
    kind = str(payload.get("stage") or "BOOTING").split(":", 1)[0]
    if profile.animation and frame % 2 == 1 and kind in ("BOOTING", "PROVISIONED"):
        lines = [(slot, text, _dim(color) if slot == "stage" else color)
                 for slot, text, color in lines]
    for slot, text, color in lines:
        y, font_size = _BOOT_LAYOUT[slot]
        if slot == "release":
            font, text = _fit(draw, text, font_size, width // 2 - 16)
            draw.text((width - 12, y), text, font=font, fill=color, anchor="ra")
            continue
        limit = width // 2 if slot == "name" else width - 32
        if slot != "name" and y < qr_bottom:
            limit = min(limit, qr_left - _QR_GAP - 16)
        font, text = _fit(draw, text, font_size, limit)
        if color == _CRIT:
            # D-202 — 부팅 카드의 위험 문장(FAILED·실패 유닛·코드 소각)도 채움.
            _draw_alarm(draw, (16, y), text, font)
        else:
            draw.text((16, y), text, font=font, fill=color)
    return image
