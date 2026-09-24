"""emotion.info_screen — PWR-003 정보 카드 렌더러.

ROS 무의존. display/info JSON 페이로드 → PIL 이미지 한 장.
LCD는 이 이미지를 회전/리사이즈해 출력하므로 여기서는 GIF 프레임과 같은
가로 방향(기본 320x240)으로 그린다.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

DEFAULT_SIZE = (320, 240)

# concept 16 L1 / D-82 / D-187 — 색은 토큰과 같은 값이다. 이 모듈은 파일을
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
        fill = _CRIT if value == "E-STOP" else _FG
        draw.text((92, y), value, font=_font(16), fill=fill)

    address = str(payload.get("address") or "")
    if address:
        draw.text((width // 2, height - 14), address,
                  font=_font(14), fill=_MUTED, anchor="ms")

    return image
