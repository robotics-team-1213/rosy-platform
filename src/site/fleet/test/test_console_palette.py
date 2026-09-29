"""concept 16 §6, §7.3 / D-72 L1 / D-82 / D-129 — 관제 표면 팔레트의 수치 게이트.

D-129 부터 L1 토큰은 트리 전체에서 하나다 — web_common의 tokens.css. 이
모듈은 그 단일 파일을 읽는다. D-73이 "표면 간 토큰 단언의 거처가 없다"고 한
자리가 이제 여기다: 그 파일이 공유 계약 자산이 된 이상(core_common 스키마
선례, D-18) fleet 시험이 그 값을 읽는 것은 경계 침범이 아니라 계약 소비다.

역할 분담(D-129·D-130): 값 게이트(아래 OKLCH·대비·사다리)는 단일 파일의 값을
먹는 이 계층이, fleet 시트의 문법(원시 색 없음, 정상 참조 없음)은 이 파일의
표면 게이트가 지킨다. 문법 분리 자체는 test_grammar_separation.py 가 잡는다.

이 시험이 존재하는 이유: Fleet은 D-82 이전 팔레트를 복사해 갔었다. 적록 색약
시야에서 주의 대 위험 대비가 1.07:1이었고, 계열 색 하나가 따뜻한 띠에 있었으며,
로봇 식별 4색 중 6쌍 가운데 4쌍이 색약에서 갈리지 않았다. 관제는 색 예산이
가장 빡빡한 표면이다 — 스무 대 중 한 대가 문제면 색이 있는 줄도 하나여야 한다.

표준 라이브러리만 쓴다.
"""

from pathlib import Path
import math
import re

import pytest

WEB = Path(__file__).resolve().parents[1] / "fleet" / "server" / "web"
#: D-129 — 단일 L1 파일. 사본은 없다.
CANON = Path(__file__).resolve().parents[3] / "hmi" / "web_common" / "tokens.css"

COLOR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d|hsla?\(\s*\d")
ROBOTS = ("robot-1", "robot-2", "robot-3")


def _linear(channel: int) -> float:
    v = channel / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _encode(value: float) -> int:
    value = max(0.0, min(1.0, value))
    srgb = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return max(0, min(255, round(srgb * 255)))


def _rgb(hex_colour: str):
    raw = hex_colour.lstrip("#")
    return tuple(_linear(int(raw[i:i + 2], 16)) for i in (0, 2, 4))


def oklch(hex_colour: str):
    r, g, b = _rgb(hex_colour)
    lc = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    mc = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    sc = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    lightness = 0.2104542553 * lc + 0.7936177850 * mc - 0.0040720468 * sc
    a = 1.9779984951 * lc - 2.4285922050 * mc + 0.4505937099 * sc
    bb = 0.0259040371 * lc + 0.7827717662 * mc - 0.8086757660 * sc
    return lightness, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def contrast(a: str, b: str) -> float:
    def lum(c):
        r, g, bl = _rgb(c)
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl
    ya, yb = lum(a), lum(b)
    return (max(ya, yb) + 0.05) / (min(ya, yb) + 0.05)


def deuteranope(hex_colour: str) -> str:
    r, g, b = _rgb(hex_colour)
    return "#%02x%02x%02x" % (
        _encode(0.625 * r + 0.375 * g),
        _encode(0.700 * r + 0.300 * g),
        _encode(0.300 * g + 0.700 * b),
    )


@pytest.fixture(scope="module")
def palette() -> dict[str, str]:
    found = dict(
        re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", CANON.read_text(encoding="utf-8"))
    )
    assert found, "단일 토큰 파일에서 hex 토큰을 읽지 못했다"
    return found


def surfaces() -> list[Path]:
    return [WEB / "styles.css", WEB / "console.js"]


@pytest.mark.parametrize("path", surfaces(), ids=lambda p: p.name)
def test_tokens_are_the_single_source_of_colour(path: Path):
    found = COLOR_LITERAL.findall(path.read_text(encoding="utf-8"))
    assert not found, f"{path.name}에 원시 색 {len(found)}개: {found[:5]}"


def test_caution_and_danger_never_collapse(palette):
    warn, crit = palette["status-warn"], palette["status-crit"]
    delta_l = abs(oklch(warn)[0] - oklch(crit)[0])
    assert delta_l >= 0.15, f"주의·위험 지각 밝기 차 {delta_l:.3f} (이전 사본 0.131)"

    simulated = contrast(deuteranope(warn), deuteranope(crit))
    assert simulated >= 2.0, f"색약 대비 {simulated:.2f}:1 (이전 사본 1.07)"


def test_status_is_warm_and_series_is_cool(palette):
    for name in ("status-warn", "status-crit"):
        hue = oklch(palette[name])[2]
        assert hue <= 90 or hue >= 350, f"{name} 색상 {hue:.0f} — status는 따뜻한 띠"
    for name in ("series-primary", "series-goal", *ROBOTS):
        hue = oklch(palette[name])[2]
        assert 150 <= hue <= 330, f"{name} 색상 {hue:.0f} — series는 차가운 띠"


def test_robot_identity_is_a_lightness_ladder(palette):
    """네 대를 네 색상으로 가르는 것은 sRGB에서 불가능하다.

    식별은 라벨(PINKY-01)이 나르고, 색은 같은 색상의 밝기 사다리다. 밝기
    차이는 색약·글레어·흑백에서도 남는다.
    """
    hues = [oklch(palette[name])[2] for name in ROBOTS]
    assert max(hues) - min(hues) <= 5, f"로봇 사다리가 한 색상이 아니다: {[round(h) for h in hues]}"

    lightness = [oklch(palette[name])[0] for name in ROBOTS]
    assert lightness == sorted(lightness, reverse=True), (
        f"밝기 사다리가 단조가 아니다: {[round(v, 2) for v in lightness]}"
    )

    ground = palette["ground"]
    for name in ROBOTS:
        ratio = contrast(palette[name], ground)
        assert ratio >= 3.0, f"{name}이 바탕 위에서 {ratio:.2f}:1 — 표식은 3:1이 필요하다"

    for a, b in zip(ROBOTS, ROBOTS[1:]):
        ratio = contrast(deuteranope(palette[a]), deuteranope(palette[b]))
        assert ratio >= 1.5, f"{a} 대 {b} 색약 대비 {ratio:.2f}:1"


def test_fleet_never_renders_the_nominal(palette):
    """concept 16 §7.3 — 정상은 화면에 없다. 초록이 아니라 없음이다.

    D-129 로 선언은 공유 파일에 옮겨 갔다(콘솔은 쓴다). 그래서 이 표면의
    금지는 선언 부재가 아니라 **참조 부재**다 — fleet 시트와 스크립트가
    정상 색 토큰을 읽는 순간 정상을 색으로 칠하는 것이다.
    """
    banned = ("--status-good", "--status-ok")
    for path in surfaces():
        body = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in body, f"{path.name}이 정상을 색으로 칠한다({token})"


def test_no_decoration_effects(palette):
    banned = ("linear-gradient", "radial-gradient", "drop-shadow(")
    for path in surfaces():
        body = path.read_text(encoding="utf-8")
        hits = [token for token in banned if token in body]
        assert not hits, f"{path.name}에 장식 효과: {hits}"


def test_text_meets_wcag_on_the_ground(palette):
    ground = palette["ground"]
    for name in ("paper", "muted", "status-warn", "series-primary", "series-goal"):
        ratio = contrast(palette[name], ground)
        assert ratio >= 4.5, f"{name} 대비 {ratio:.2f}:1"
    # 위험은 글자가 아니라 채움이다 — 잉크를 얹을 수 있으면 된다.
    assert contrast(palette["paper"], palette["status-crit"]) >= 4.5


def test_every_referenced_token_is_declared_in_the_single_file(palette):
    """토큰을 갈아끼울 때 관제 UI가 조용히 색을 잃지 않게 한다.

    `var(--x)`와 `css("--x")` 둘 다 본다 — 콘솔은 CSP 아래에서 캔버스 색을
    런타임에 읽으므로, 선언이 사라지면 지도가 검게 칠해진다. 선언의 출처는
    이제 단일 파일이다(D-129).
    """
    declared = set(
        re.findall(r"--([a-z0-9-]+)\s*:", CANON.read_text(encoding="utf-8"))
    )
    missing: dict[str, list[str]] = {}
    for path in surfaces():
        body = path.read_text(encoding="utf-8")
        used = set(re.findall(r"var\(\s*--([a-z0-9-]+)\s*\)", body))
        used |= set(re.findall(r'css\("--([a-z0-9-]+)"\)', body))
        gap = sorted(used - declared)
        if gap:
            missing[path.name] = gap
    assert not missing, f"단일 파일에 선언되지 않은 토큰 참조: {missing}"
