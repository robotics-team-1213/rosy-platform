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

import token_themes

TOKENS = (Path(__file__).parents[3] / "shared") / "web" / "tokens.css"
WEB_COMPONENTS = TOKENS.parent / "components.css"
DASHBOARD = (TOKENS.parents[2] / "middleware" / "ui") / "robot"

# 신호 색은 현대 다크 UI 액센트 대역에 있어야 한다. 대역은 취향이 아니라
# 실측이다 — Radix 9, Tailwind 500, Linear, Vercel의 액센트가 모두
# OKLCH L 0.54-0.82 / C 0.133-0.219 안에 있다.
MIN_SIGNAL_CHROMA = 0.133

SIGNAL = ("status-warn", "status-crit", "series-primary", "series-secondary", "series-goal")
BRAND = ("brand-rose", "brand-rose-wash")
STATUS = ("status-warn", "status-crit")
SERIES = ("series-primary", "series-secondary", "series-goal")
RASTER = ("raster-unknown", "raster-free", "raster-uncertain", "raster-occupied")
READS_AS_TEXT = ("ink", "ink-quiet", "status-warn", "series-primary", "series-goal", "brand-rose")


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


def _srgb_hex(lightness: float, a: float, b: float) -> str:
    """OKLab → #rrggbb (sRGB 밖은 자른다)."""
    l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return "#%02x%02x%02x" % (
        _encode(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
        _encode(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
        _encode(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s),
    )


def mix_oklab(first: str, share: float, second: str) -> str:
    """`color-mix(in oklab, first share, second)` — 두 불투명 색의 직선 보간."""
    l1, c1, h1 = oklch(first)
    l2, c2, h2 = oklch(second)
    t = share / 100.0
    a = c1 * math.cos(math.radians(h1)) * t + c2 * math.cos(math.radians(h2)) * (1 - t)
    b = c1 * math.sin(math.radians(h1)) * t + c2 * math.sin(math.radians(h2)) * (1 - t)
    return _srgb_hex(l1 * t + l2 * (1 - t), a, b)


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

TEXT = token_themes.read(TOKENS)
THEMES = sorted(token_themes.palettes(TEXT))
DARK = "dark"

# 밝기 대역은 바탕의 극성(어두운 바탕 / 밝은 바탕)에 따라 다르다. 테마 이름이 아니라
# 극성으로 고르므로 새 테마는 시험을 고치지 않고 블록 하나로 들어온다(D-359 §2.3).
#   brand     장미색 이름이 자기 바탕 위에서 읽히는 밝기(대비 4.5:1은 따로 본다).
#   wash      현재 위치 표식의 옅은 바탕 — 바탕 가까이에 머문다.
BANDS = {
    "dark": {"brand": (0.74, 0.84), "wash": (0.18, 0.28)},
    "light": {"brand": (0.45, 0.60), "wash": (0.88, 0.97)},
}


def resolve(theme: str) -> dict[str, str]:
    found = dict(token_themes.palettes(TEXT)[theme])
    # D-359 파생 층: 두 팔레트 색을 섞은 불투명 파생(세척·바탕 단계)도 그 테마의
    # 값으로 풀어 같은 게이트가 본다. `transparent`와 섞은 알파 파생은 색이 팔레트 그대로다.
    for name, first, share, second in re.findall(
        r"--([a-z0-9-]+):\s*color-mix\(in oklab,\s*var\(--([a-z0-9-]+)\)\s*([\d.]+)%,"
        r"\s*var\(--([a-z0-9-]+)\)\s*\)\s*;",
        token_themes.derived_body(TEXT),
    ):
        found[name] = mix_oklab(found[first], float(share), found[second])
    return found


def polarity(palette: dict[str, str]) -> str:
    """바탕이 잉크보다 어두우면 dark, 밝으면 light."""
    return "dark" if oklch(palette["ground"])[0] < oklch(palette["ink"])[0] else "light"


@pytest.fixture(scope="module", params=THEMES)
def palette(request) -> dict[str, str]:
    found = resolve(request.param)
    assert found, f"tokens.css {request.param} 블록에서 hex 토큰을 읽지 못했다"
    return found


def test_both_themes_are_declared():
    assert {"dark", "light"} <= set(THEMES), f"테마 블록: {THEMES}"


def test_every_theme_defines_the_same_palette_keys():
    """D-359 §2 — 테마는 값만 바꾼다. 한 테마에만 있는 키는 다른 테마에서 조용히
    어두운 값(`:root`)으로 떨어진다."""
    sets = {theme: set(values) for theme, values in token_themes.palettes(TEXT).items()}
    reference = sets[DARK]
    drift = {
        theme: {"missing": sorted(reference - keys), "extra": sorted(keys - reference)}
        for theme, keys in sets.items()
        if keys != reference
    }
    assert not drift, f"팔레트 키 집합이 테마마다 다르다: {drift}"


def test_every_theme_block_sets_its_own_colour_scheme():
    schemes = token_themes.colour_schemes(TEXT)
    for theme in THEMES:
        assert schemes.get(theme) == [theme], f"{theme} 블록의 color-scheme: {schemes.get(theme)}"


def test_the_dark_palette_is_also_the_root_default():
    """`data-theme`이 없는 페이지(고정 표면·구 페이지)도 어두운 팔레트를 받는다."""
    selectors = [sel for sel, _ in token_themes.blocks(TEXT) if '[data-theme="dark"]' in sel]
    assert selectors == [':root, [data-theme="dark"]'], selectors


def test_the_derived_block_has_no_raw_colour():
    """D-359 §1.2 — 원시 색은 팔레트 블록에만. 파생에 hex가 들어오면 테마가 바꾸지 못한다."""
    found = token_themes.RAW_COLOUR.findall(token_themes.derived_body(TEXT))
    assert not found, f"파생 블록에 원시 색: {found}"


def test_every_named_token_exists(palette):
    expected = {"ground", "ink", "ink-quiet", "ink-on-crit", *SIGNAL, *BRAND, *RASTER}
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
    danger, ink, ground = palette["status-crit"], palette["ink-on-crit"], palette["ground"]
    assert contrast(ink, danger) >= 4.5, f"잉크가 위험 면 위에서 {contrast(ink, danger):.2f}:1"
    assert contrast(danger, ground) >= 3.0, f"위험 면이 바탕 위에서 {contrast(danger, ground):.2f}:1"


def test_same_form_series_separate_for_deuteranopes(palette):
    """지도의 계열은 형태로 먼저 갈린다 — 색은 두 번째 단서다.

    실선(`series-primary`)과 파선(`series-secondary`)은 같은 형태 계열이므로 색으로도
    갈려야 한다. 목표(`series-goal`)는 채운 사각형이라 형태가 이미 다르고,
    sRGB 색역에서 차가운 색 셋을 밝기로 모두 떼어놓을 수 없다 — 그 쌍은
    형태에 맡긴다는 것이 이 시험이 기록하는 결정이다.
    """
    simulated = contrast(deuteranope(palette["series-primary"]), deuteranope(palette["series-secondary"]))
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


def test_rosy_brand_uses_a_readable_magenta_rose_distinct_from_critical(palette):
    """ROSY identity is a brand role, separate from status and data-series meaning."""
    lightness, chroma, hue = oklch(palette["brand-rose"])
    low, high = BANDS[polarity(palette)]["brand"]
    assert low <= lightness <= high, f"brand rose 밝기 {lightness:.3f} ({polarity(palette)} 대역 {low}-{high})"
    assert 0.133 <= chroma <= 0.20, f"brand rose 채도 {chroma:.3f}"
    assert 320 <= hue <= 340, f"brand rose 색상 {hue:.1f} — rose-magenta 대역 밖"
    assert contrast(palette["brand-rose"], palette["ground"]) >= 4.5
    simulated = contrast(
        deuteranope(palette["brand-rose"]),
        deuteranope(palette["status-crit"]),
    )
    assert simulated >= 1.8, f"브랜드와 위험 색약 대비 {simulated:.2f}:1"
    assert "brand-rose" not in STATUS and "brand-rose" not in SERIES


def test_rosy_brand_wash_is_a_subtle_tinted_surface(palette):
    lightness, chroma, hue = oklch(palette["brand-rose-wash"])
    rose_hue = oklch(palette["brand-rose"])[2]
    hue_delta = abs(hue - rose_hue)
    hue_delta = min(hue_delta, 360 - hue_delta)
    low, high = BANDS[polarity(palette)]["wash"]
    assert low <= lightness <= high, f"brand wash 밝기 {lightness:.3f} ({polarity(palette)} 대역 {low}-{high})"
    assert 0.015 <= chroma <= 0.05, f"brand wash 채도 {chroma:.3f}"
    assert hue_delta <= 12, f"brand wash 색상 방향이 rose와 {hue_delta:.1f}° 다름"


def test_rosy_brand_tokens_are_used_by_wordmark_and_surface_navigation():
    components = WEB_COMPONENTS.read_text(encoding="utf-8")
    legacy_shell = (DASHBOARD / "styles.css").read_text(encoding="utf-8")
    role_shell = (DASHBOARD / "shell" / "shell.css").read_text(encoding="utf-8")
    assert "ui-brand b" in components and "color: var(--brand-rose)" in components
    assert ".brand b" in legacy_shell and "color: var(--brand-rose)" in legacy_shell
    active = role_shell.split('.surface-switch a[aria-current="page"]', 1)[1].split("}", 1)[0]
    assert "color: var(--brand-rose)" in active
    assert "background: var(--brand-rose-wash)" in active


def test_browser_theme_colour_matches_the_neutral_page_ground():
    """정적 theme-color는 기본(어둡게) 바탕이다. 밝게는 theme.js가 바꾼다."""
    palette = resolve(DARK)
    for name in ("surface.html", "index.html"):
        source = (DASHBOARD / name).read_text(encoding="utf-8")
        match = re.search(r'<meta\s+name="theme-color"\s+content="(#[0-9a-fA-F]{6})"', source)
        assert match, f"{name}: theme-color meta 없음"
        assert match.group(1).lower() == palette["ground"].lower(), (
            f"{name}: 브라우저 색 {match.group(1)} != ground {palette['ground']}"
        )


def test_raster_ramp_is_achromatic_and_monotonic(palette):
    """지형은 계열이 아니라 바탕이다. 밝기만으로 단조여야 오버레이가 어디에나 얹힌다.

    D-359: 단조의 방향은 '어두운 것에서 밝은 것으로'가 아니라 **바탕에서 잉크
    쪽으로**다 — 미지는 바탕에 녹고 점유는 잉크처럼 선다. 어두운 바탕에서는
    밝기 오름차순(예전 판정과 같다), 밝은 바탕에서는 내림차순이 된다.
    """
    for name in RASTER:
        chroma = oklch(palette[name])[1]
        assert chroma <= 0.02, f"{name} 채도 {chroma:.3f} — 래스터는 무채색이어야 한다"

    ground = oklch(palette["ground"])[0]
    toward_ink = 1 if polarity(palette) == "dark" else -1
    distance = [toward_ink * (oklch(palette[name])[0] - ground) for name in RASTER]
    assert distance == sorted(distance), (
        "래스터 램프가 바탕에서 잉크 쪽으로 단조가 아니다: "
        + " ".join(f"{n}={v:+.2f}" for n, v in zip(RASTER, distance))
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
    for name in ("ground", "ground-soft", "ground-card", "ink", "ink-quiet"):
        chroma = oklch(palette[name])[1]
        assert chroma <= 0.02, f"{name} 채도 {chroma:.3f} — 바탕 계열은 중립이어야 한다"


def test_duplicate_palettes_are_gone(palette):
    """선언된 팔레트 밖에서 섞여 들어온 둘째·셋째 벌이 없어야 한다.

    이전 styles.css에는 `--signal-*` 한 벌 외에 Tailwind 계열
    (#fbbf24 #f87171 #6ee7b7 #94a3b8)과 세 번째 앰버가 함께 있었다.
    """
    # D-359: 같은 값의 별칭(`-2`, `--status-ok`)은 지웠다. 되살아나면 두 벌이다.
    aliases = {"status-crit-2", "status-warn-2", "status-ok"} & palette.keys()
    assert not aliases, f"같은 색의 둘째 이름: {sorted(aliases)}"

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


def test_robot_identity_is_a_lightness_ladder(palette):
    """D-82 로봇 사다리 — 한 색상, 밝기 내림차순, 바탕 위 3:1, 이웃 색약 1.5:1.

    Fleet `test_console_palette.py`가 같은 성질을 소비자 쪽에서 본다. 원본의 주인인
    여기서는 테마마다 돈다(D-359 §3.2).
    """
    robots = ("robot-1", "robot-2", "robot-3")
    hues = [oklch(palette[name])[2] for name in robots]
    assert max(hues) - min(hues) <= 5, f"로봇 사다리가 한 색상이 아니다: {[round(h) for h in hues]}"
    for hue in hues:
        assert 150 <= hue <= 330, f"로봇 색상 {hue:.0f} — 차가운 띠여야 한다"
    lightness = [oklch(palette[name])[0] for name in robots]
    assert lightness == sorted(lightness, reverse=True), f"밝기 사다리가 단조가 아니다: {lightness}"
    for name in robots:
        assert contrast(palette[name], palette["ground"]) >= 3.0, f"{name} 바탕 대비"
    for a, b in zip(robots, robots[1:]):
        ratio = contrast(deuteranope(palette[a]), deuteranope(palette[b]))
        assert ratio >= 1.5, f"{a} 대 {b} 색약 대비 {ratio:.2f}:1"


def test_the_primary_command_is_an_ink_fill(palette):
    """주 명령은 테마와 무관하게 ink 채움이고 그 위 글자는 바탕이다(D-359 §2.2)."""
    derived = token_themes.derived_body(TEXT)
    assert re.search(r"--button-primary-bg:\s*var\(--ink\);", derived)
    assert re.search(r"--button-primary-ink:\s*var\(--surface-canvas\);", derived)
    assert re.search(r"--surface-canvas:\s*var\(--ground\);", derived)
    assert contrast(palette["ground"], palette["ink"]) >= 7.0


#: 위험 채움 위 글자에 허용되는 토큰. `--ink`는 밝게에서 짙은 글자라 짙은 적색 위에서 사라진다.
ON_DANGER_INK = ("--ink-on-crit", "--text-on-danger", "--flag-danger-ink", "--button-irreversible-ink")
_DANGER_FILL = re.compile(r"background(?:-color)?:\s*var\(--(?:status-crit|flag-danger-bg|button-irreversible-bg)\)")
_TEXT_COLOUR = re.compile(r"(?<![-\w])color:\s*var\((--[a-z0-9-]+)\)")


def test_text_on_a_danger_fill_uses_the_on_crit_ink():
    """D-359 — 어둡게에서는 `--ink`와 `--ink-on-crit`가 같은 값이라 틀린 참조가 숨는다.

    위험 채움 규칙이 글자색을 정하면 그 값은 위험 위 잉크여야 한다. 모든 테마에서
    `test_danger_works_as_a_fill`이 그 쌍의 대비를 지킨다.
    """
    import surface_registry as registry

    sheets = {TOKENS.parent / "components.css"}
    for row in registry.load():
        if row.get("medium") == "web":
            target = registry.REPO / row["path"]
            sheets |= set(target.rglob("*.css")) if target.is_dir() else set()
    offenders = []
    for sheet in sorted(sheets):
        text = re.sub(r"/\*.*?\*/", "", sheet.read_text(encoding="utf-8"), flags=re.S)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            danger = _DANGER_FILL.search(body) or 'kind="irreversible"] small' in selector
            colour = _TEXT_COLOUR.search(body)
            if danger and colour and colour.group(1) not in ON_DANGER_INK:
                offenders.append(f"{sheet.name}: {selector.strip()} color {colour.group(1)}")
    assert not offenders, offenders
