"""D-741 10 — 조작(단추·입력)의 경계는 두 테마의 다섯 바탕 위에서 3:1을 넘는다.

`--control-line`은 잉크에 알파만 준 파생 토큰이다
(`color-mix(in oklab, var(--ink) N%, transparent)`). 파생 층은 테마마다 따로 정할 수
없으므로(D-359 §1) N 하나가 두 테마를 다 넘어야 한다. 색 공간과 대비 계산은
`test_palette_gates.py`의 것을 그대로 쓴다.

변이 증명: tokens.css의 `--line-50`을 `--line-40`·40%로 되돌리면 밝게 테마 다섯 건이 빨갛다.
"""

import re
from pathlib import Path

import pytest

import token_themes
from test_palette_gates import THEMES, contrast, resolve

WEB = Path(__file__).resolve().parents[1]
DERIVED = token_themes.derived_body(token_themes.read())
SURFACES = ("ground", "ground-deep", "ground-raise", "ground-soft", "ground-card")
MIN_CONTROL_CONTRAST = 3.0  # WCAG 2.2 SC 1.4.11 비텍스트 대비


def _decl(name: str) -> str:
    found = re.search(rf"^\s*{re.escape(name)}\s*:\s*([^;]+);", DERIVED, re.MULTILINE)
    assert found, f"{name} 토큰이 없다"
    return found.group(1).strip()


def control_line_share() -> float:
    alias = re.fullmatch(r"var\((--line-\d+)\)", _decl("--control-line"))
    assert alias, "--control-line은 --line-N 파생 하나를 가리킨다"
    mix = re.fullmatch(r"color-mix\(in oklab, var\(--ink\) ([\d.]+)%, transparent\)", _decl(alias.group(1)))
    assert mix, f"{alias.group(1)}은 잉크 알파 파생이다"
    assert alias.group(1) == f"--line-{mix.group(1)}", "이름의 숫자가 값의 백분율이다"
    return float(mix.group(1))


def over(ink: str, share: float, face: str) -> str:
    """알파 share%의 잉크를 불투명한 면 위에 얹은 색(sRGB source-over). 브라우저가 테두리를 칠하는 방식이다."""
    def channels(colour: str) -> list[int]:
        return [int(colour[i:i + 2], 16) for i in (1, 3, 5)]

    t = share / 100.0
    return "#%02x%02x%02x" % tuple(round(i * t + f * (1 - t)) for i, f in zip(channels(ink), channels(face)))


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("surface", SURFACES)
def test_control_line_reaches_three_to_one(theme, surface):
    palette = resolve(theme)
    ratio = contrast(over(palette["ink"], control_line_share(), palette[surface]), palette[surface])
    assert ratio >= MIN_CONTROL_CONTRAST, f"{theme}/{surface}: {ratio:.2f}:1"


def test_the_gate_is_not_vacuous():
    """잉크 40%는 밝게 테마에서 모자란다. 계산이 늘 통과하는 식이 아님을 고정한다."""
    light = resolve("light")
    assert contrast(over(light["ink"], 40, light["ground"]), light["ground"]) < MIN_CONTROL_CONTRAST


COMPONENTS = (WEB / "components.css").read_text(encoding="utf-8")


def test_controls_take_the_control_line_and_dividers_keep_theirs():
    assert _decl("--field-line") == "var(--control-line)"
    for selector in ("ui-button", 'ui-button[kind="quiet"],\na.docs-link', ".ui-disclosure-row"):
        block = COMPONENTS.split(f"\n{selector} {{", 1)[1].split("}", 1)[0]
        assert "border: 1px solid var(--control-line);" in block, selector
    assert _decl("--surface-line") == "var(--border-default)"
    assert _decl("--border-default") == "var(--line-14)"
