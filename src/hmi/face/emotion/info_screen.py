"""emotion.info_screen — PWR-003 정보 카드 렌더러.

ROS 무의존. display/info JSON 페이로드 → PIL 이미지 한 장.
LCD는 이 이미지를 회전/리사이즈해 출력하므로 여기서는 GIF 프레임과 같은
가로 방향(기본 320x240)으로 그린다.

``render_boot``는 부팅 카드다(D-190). CORE 밖의 ``rosy-boot-display``가
``/run/rosy-boot`` 상태로 그린다. 같은 팔레트(D-82)를 쓴다.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

DEFAULT_SIZE = (320, 240)

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
_FG = (238, 238, 239)       # --paper    #eeeeef
_MUTED = (148, 153, 160)    # --muted    #9499a0
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


def render(payload: dict, size: tuple[int, int] = DEFAULT_SIZE) -> Image.Image:
    """웨이크 정보 카드. 값이 없으면 '--'로 두고 화면은 반드시 그린다."""
    width, height = size
    image = Image.new("RGB", size, _BG)
    draw = ImageDraw.Draw(image)

    raw_percent = payload.get("battery_percent")
    voltage = payload.get("battery_voltage")
    has_percent = raw_percent is not None
    # 결측은 0%가 아니다 — 결측을 crit 색 경보로 그리면 없는 위험을 만든다
    # (Law 0). 전압의 '--' 폴백과 같은 규약을 쓴다.
    percent = float(raw_percent) if has_percent else 0.0
    color = battery_color(percent) if has_percent else _MUTED

    draw.text((16, 10), str(payload.get("robot_id") or "rosy"),
              font=_font(18), fill=_MUTED)

    if has_percent:
        if color == _CRIT:
            _draw_alarm(draw, (16, 36), f"{percent:.0f}%", _font(56))
        else:
            draw.text((16, 36), f"{percent:.0f}%", font=_font(56), fill=color)
    else:
        draw.text((16, 36), "--", font=_font(56), fill=_MUTED)
    draw.text((width - 16, 60), "--" if voltage is None else f"{float(voltage):.2f} V",
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

    for index, (label, value) in enumerate(rows):
        y = 142 + index * 24
        draw.text((16, y), label, font=_font(14), fill=_MUTED)
        if value == "E-STOP":
            _draw_alarm(draw, (92, y), value, _font(16))
        else:
            draw.text((92, y), value, font=_font(16), fill=_FG)

    address = str(payload.get("address") or "")
    if address:
        draw.text((width // 2, height - 14), address,
                  font=_font(14), fill=_MUTED, anchor="ms")

    return image


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

    percent = payload.get("battery_percent")
    voltage = payload.get("battery_voltage")
    if percent is None or voltage is None:
        lines.append(("battery", "battery --", _MUTED))
    else:
        lines.append(("battery", f"{float(percent):.0f}%  {float(voltage):.2f} V",
                      battery_color(float(percent))))

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


def render_boot(payload: dict, size: tuple[int, int] = DEFAULT_SIZE) -> Image.Image:
    """Boot card: name, release, stage (failed unit), address, battery, AP."""
    width, _height = size
    image = Image.new("RGB", size, _BG)
    draw = ImageDraw.Draw(image)
    for slot, text, color in boot_lines(payload):
        y, font_size = _BOOT_LAYOUT[slot]
        if slot == "release":
            font, text = _fit(draw, text, font_size, width // 2 - 16)
            draw.text((width - 12, y), text, font=font, fill=color, anchor="ra")
            continue
        limit = width // 2 if slot == "name" else width - 32
        font, text = _fit(draw, text, font_size, limit)
        if color == _CRIT:
            # D-202 — 부팅 카드의 위험 문장(FAILED·실패 유닛·코드 소각)도 채움.
            _draw_alarm(draw, (16, y), text, font)
        else:
            draw.text((16, y), text, font=font, fill=color)
    return image
