"""concept 16 §6 / D-82 — 팔레트 값이 지켜야 할 수치 게이트.

`test_ui_token_contracts.py`가 "원시 색이 토큰 파일 밖에 있으면 실패"를 지킨다면,
이 파일은 그 토큰 **값 자체**를 지킨다. 철학이 취향이면 리뷰에서 다시 다투고,
수치면 시험이 지킨다.

왜 필요한가: 이전 팔레트는 `정상 #c4db76`과 `주의 #f2c46d`가 HSL로 3pt 차이라
괜찮아 보였지만 지각 밝기 차는 0.009였다. 적록 색약 시야에서 `위험`과 `주의`의
대비가 1.07:1이 되어, 로봇 콘솔에서 주의와 위험이 구분되지 않았다.

표준 라이브러리만 쓴다. CI 의존 목록에 numpy가 없다(D-73: 이 모듈이 소유한
파일만 단언한다).
"""

from itertools import combinations
from pathlib import Path
import math
import re

import pytest

TOKENS = Path(__file__).parent.parent.parent / "web_common" / "tokens.css"

# 신호 색은 현대 다크 UI 액센트 대역에 있어야 한다. 대역은 취향이 아니라
# 실측이다 — Radix 9, Tailwind 500, Linear, Vercel의 액센트가 모두
# OKLCH L 0.54-0.82 / C 0.133-0.219 안에 있다.
MIN_SIGNAL_CHROMA = 0.133

SIGNAL = ("status-warn", "status-crit", "series-primary", "route-dim", "series-goal")
STATUS = ("status-warn", "status-crit")
SERIES = ("series-primary", "route-dim", "series-goal")
RASTER = ("raster-unknown", "raster-free", "raster-uncertain", "raster-occupied")
READS_AS_TEXT = ("paper", "muted", "status-warn", "series-primary", "series-goal")


# ---- 색 공간 -------------------------------------------------------------

def _linear(channel: int) -> float:
    v = channel / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _encode(value: float) -> int:
    value = max(0.0, min(1.0, value))
    srgb = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return max(0, min(255, round(srgb * 255)))


def linear_rgb(hex_colour: str) -> tuple[float, float, float]:
    raw = hex_colour.lstrip("#")
    return tuple(_linear(int(raw[i:i + 2], 16)) for i in (0, 2, 4))


def oklch(hex_colour: str) -> tuple[float, float, float]:
    """(L, C, H) — L은 지각 밝기다. HSL의 lightness와 다르다."""
    r, g, b = linear_rgb(hex_colour)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    lightness = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return lightness, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def relative_luminance(hex_colour: str) -> float:
    r, g, b = linear_rgb(hex_colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    ya, yb = relative_luminance(a), relative_luminance(b)
    return (max(ya, yb) + 0.05) / (min(ya, yb) + 0.05)


def deuteranope(hex_colour: str) -> str:
    """적록 색약(2형) 근사. 색상은 무너지고 밝기는 남는다."""
    r, g, b = linear_rgb(hex_colour)
    return "#%02x%02x%02x" % (
        _encode(0.625 * r + 0.375 * g),
        _encode(0.700 * r + 0.300 * g),
        _encode(0.300 * g + 0.700 * b),
    )


# ---- 토큰 읽기 -----------------------------------------------------------

@pytest.fixture(scope="module")
def palette() -> dict[str, str]:
    text = TOKENS.read_text(encoding="utf-8")
    found = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", text))
    assert found, "tokens.css에서 hex 토큰을 읽지 못했다"
    return found


def test_every_named_token_exists(palette):
    expected = {"ground", "paper", *SIGNAL, *RASTER}
    missing = expected - palette.keys()
    assert not missing, f"tokens.css에 없는 토큰: {sorted(missing)}"


def test_signal_colours_carry_enough_chroma(palette):
    """채도가 낮으면 탁해 보이고, 현대 다크 UI 대역에서 벗어난다."""
    weak = {
        name: round(oklch(palette[name])[1], 3)
        for name in SIGNAL
        if oklch(palette[name])[1] < MIN_SIGNAL_CHROMA
    }
    assert not weak, f"채도가 모자란 신호 색 (기준 {MIN_SIGNAL_CHROMA}): {weak}"


def test_caution_and_danger_never_collapse(palette):
    """이 팔레트가 존재하는 이유다.

    이전 팔레트는 색약 시야에서 위험과 주의의 대비가 1.07:1이었다. 색상
    차이는 색약·글레어·흑백에서 사라지므로, 두 경보는 **지각 밝기**로도
    떨어져 있어야 한다.
    """
    caution, danger = palette["status-warn"], palette["status-crit"]

    delta_l = abs(oklch(caution)[0] - oklch(danger)[0])
    assert delta_l >= 0.15, f"주의·위험 지각 밝기 차 {delta_l:.3f} (기준 0.15)"

    simulated = contrast(deuteranope(caution), deuteranope(danger))
    assert simulated >= 2.0, f"색약 대비 {simulated:.2f}:1 (기준 2.0, 이전 팔레트 1.07)"


def test_danger_works_as_a_fill(palette):
    """위험은 글자가 아니라 채움이다(concept 16 Law 3: 종류가 다르다).

    그래서 위험 토큰에 요구되는 것은 '바탕 위에서 읽히는 글자색'이 아니라
    '잉크를 얹을 수 있는 면'이다.
    """
    danger, ink, ground = palette["status-crit"], palette["paper"], palette["ground"]
    assert contrast(ink, danger) >= 4.5, f"잉크가 위험 면 위에서 {contrast(ink, danger):.2f}:1"
    assert contrast(danger, ground) >= 3.0, f"위험 면이 바탕 위에서 {contrast(danger, ground):.2f}:1"


def test_same_form_series_separate_for_deuteranopes(palette):
    """지도의 계열은 형태로 먼저 갈린다 — 색은 두 번째 단서다.

    실선(`series-primary`)과 파선(`route-dim`)은 같은 형태 계열이므로 색으로도
    갈려야 한다. 목표(`series-goal`)는 채운 사각형이라 형태가 이미 다르고,
    sRGB 색역에서 차가운 색 셋을 밝기로 모두 떼어놓을 수 없다 — 그 쌍은
    형태에 맡긴다는 것이 이 시험이 기록하는 결정이다.
    """
    simulated = contrast(deuteranope(palette["series-primary"]), deuteranope(palette["route-dim"]))
    assert simulated >= 1.5, f"실선 대 파선 색약 대비 {simulated:.2f}:1 (기준 1.5)"


def test_status_is_warm_and_series_is_cool(palette):
    """색상 온도가 의미를 나른다.

    화면에 따뜻한 것이 보이면 언제나 무언가 잘못된 것이다. 계열 색이 따뜻한
    띠에 들어오면 그 규칙이 무너진다.
    """
    for name in STATUS:
        hue = oklch(palette[name])[2]
        assert hue <= 90 or hue >= 350, f"{name} 색상 {hue:.0f} — status는 따뜻한 띠여야 한다"

    for name in SERIES:
        hue = oklch(palette[name])[2]
        assert 150 <= hue <= 330, f"{name} 색상 {hue:.0f} — series는 차가운 띠여야 한다"


def test_raster_ramp_is_achromatic_and_monotonic(palette):
    """지형은 계열이 아니라 바탕이다. 밝기만으로 단조 증가해야 오버레이가
    어디에나 얹힌다."""
    for name in RASTER:
        chroma = oklch(palette[name])[1]
        assert chroma <= 0.02, f"{name} 채도 {chroma:.3f} — 래스터는 무채색이어야 한다"

    lightness = [oklch(palette[name])[0] for name in RASTER]
    assert lightness == sorted(lightness), (
        "래스터 램프가 단조가 아니다: "
        + " ".join(f"{n}={v:.2f}" for n, v in zip(RASTER, lightness))
    )


def test_text_tokens_meet_wcag_on_the_ground(palette):
    ground = palette["ground"]
    failures = {
        name: round(contrast(palette[name], ground), 2)
        for name in READS_AS_TEXT
        if contrast(palette[name], ground) < 4.5
    }
    assert not failures, f"바탕 위 대비가 4.5:1 미만: {failures}"


def test_the_ground_ramp_stays_neutral(palette):
    """초록 기운이 있는 바탕은 따뜻한 벽과 목표 색의 지각 색상을 밀어낸다."""
    for name in ("ground", "ground-soft", "ground-card", "paper", "muted"):
        chroma = oklch(palette[name])[1]
        assert chroma <= 0.02, f"{name} 채도 {chroma:.3f} — 바탕 계열은 중립이어야 한다"


def test_duplicate_palettes_are_gone(palette):
    """선언된 팔레트 밖에서 섞여 들어온 둘째·셋째 벌이 없어야 한다.

    이전 styles.css에는 `--signal-*` 한 벌 외에 Tailwind 계열
    (#fbbf24 #f87171 #6ee7b7 #94a3b8)과 세 번째 앰버가 함께 있었다.
    """
    assert palette["status-crit-2"] == palette["status-crit"], "위험 색이 두 벌이다"
    assert palette["status-warn-2"] == palette["status-warn"], "주의 색이 두 벌이다"

    warm_hues = sorted(
        oklch(value)[2]
        for name, value in palette.items()
        if name.startswith("status-") and "-a" not in name and oklch(value)[2] <= 90
    )
    # 같은 계열의 변형(면용 짙은 빨강 등)은 한 색으로 센다. 15도 안이면 한 계열이다.
    families: list[float] = []
    for hue in warm_hues:
        if not families or hue - families[-1] > 15:
            families.append(hue)
    assert len(families) <= 2, (
        f"따뜻한 경보 색상 계열이 둘을 넘는다: {[round(h) for h in families]} "
        f"(전체 {[round(h) for h in warm_hues]})"
    )
