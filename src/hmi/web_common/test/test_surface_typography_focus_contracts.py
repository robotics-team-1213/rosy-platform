"""D-300 contracts for recurring typography and focus rules on product surfaces."""

import re
from pathlib import Path

import surface_registry as registry

ROOT = Path(__file__).resolve().parents[4]

# 표면 목록은 src/hmi/web_common/surfaces.yaml 한 곳에서만 읽는다 (D-329 Decision 1).


def surface_styles():
    return [
        style
        for surface in registry.for_contract(ROOT, "typography_focus")
        for style in ((surface,) if surface.is_file() else surface.rglob("*.css"))
    ]


def test_surface_repeated_weights_leading_and_tracking_use_shared_tokens():
    raw_numeric_weight = re.compile(r"\bfont-weight\s*:\s*(?:400|500|600|650|700)\b")
    raw_weighted_font = re.compile(r"\bfont\s*:\s*(?:400|500|600|650|700)\s+")
    raw_shared_leading = re.compile(
        r"(?:line-height\s*:|font\s*:[^;{}]+/)\s*(?:1\.5|1\.4|1\.3|1\.25|1\.2|1(?:\.0)?)(?=\s|;|$)"
    )
    surface_leading = re.compile(r"(?:line-height\s*:|font\s*:[^;{}]+/)\s*(1\.\d+)(?=\s|;|$)")
    raw_shared_tracking = re.compile(r"letter-spacing\s*:\s*(?:0\.04|0\.06|0\.12)em\b")
    malformed_token_value = re.compile(r"(?:normal|var\(--leading-flat\))\.\d")
    violations = []
    surface_exceptions = set()

    for path in surface_styles():
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
        for pattern in (
            raw_numeric_weight,
            raw_weighted_font,
            raw_shared_leading,
            raw_shared_tracking,
            malformed_token_value,
        ):
            violations.extend(f"{path.relative_to(ROOT)}: {match.group(0)}" for match in pattern.finditer(css))
        surface_exceptions.update(match.group(1) for match in surface_leading.finditer(css))

    assert not violations, "반복 타이포그래피 규칙은 D-300 토큰을 사용해야 합니다:\n" + "\n".join(violations)
    assert surface_exceptions <= {"1.15", "1.35", "1.45", "1.55", "1.6", "1.7"}, (
        "예외로 허용한 고유 읽기 줄 간격만 표면 CSS에 남길 수 있습니다: "
        + str(sorted(surface_exceptions))
    )


def test_standard_keyboard_focus_rings_use_shared_dimensions():
    focus_rule = re.compile(r"([^{}]*:focus-visible[^{}]*)\{([^{}]*)\}", re.DOTALL)
    violations = []
    for path in surface_styles():
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
        for selector, declarations in focus_rule.findall(css):
            if "canvas" in selector:
                continue  # D-300 keeps a larger, viewport-specific map focus gap.
            if "outline:" not in declarations:
                continue
            if "var(--focus-ring-width)" not in declarations:
                violations.append(f"{path.relative_to(ROOT)} {selector.strip()}: focus width")
            if "var(--focus-ring-offset-outer)" not in declarations and "var(--focus-ring-offset)" not in declarations:
                violations.append(f"{path.relative_to(ROOT)} {selector.strip()}: focus offset")

    assert not violations, "표준 키보드 포커스 링은 공유 치수를 사용해야 합니다:\n" + "\n".join(violations)


def test_letter_spacing_is_a_token_or_zero():
    """D-359 §5.5 — 자간은 --track-label/--track-wide/--track-state 또는 0만 쓴다."""
    spacing = re.compile(r"letter-spacing\s*:\s*([^;}]+)")
    allowed = re.compile(r"\s*(?:0|var\(--track-(?:label|wide|state)\))\s*(?:!important)?\s*")
    violations = []
    for path in surface_styles():
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
        violations.extend(
            f"{path.relative_to(ROOT)}: letter-spacing: {value.strip()}"
            for value in spacing.findall(css) if not allowed.fullmatch(value)
        )
    assert not violations, "자간은 토큰 또는 0이어야 합니다:\n" + "\n".join(violations)


def test_dimming_uses_the_disabled_token_not_an_opacity_literal():
    """D-359 §5.5 — 흐림은 --disabled-opacity 또는 --ink-quiet 색이다. 임의 불투명도를 쓰지 않는다."""
    literal = re.compile(r"(?<![-\w])opacity\s*:(?!\s*var\()\s*([^;}]+)")
    violations = []
    for path in surface_styles():
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
        violations.extend(
            f"{path.relative_to(ROOT)}: opacity: {value.strip()}"
            for value in literal.findall(css) if value.strip() not in {"0", "1"}
        )
    assert not violations, "임의 불투명도:\n" + "\n".join(violations)


def test_skip_link_focus_border_uses_the_shared_focus_width_token():
    css = (ROOT / "src/hmi/web_common/components.css").read_text(encoding="utf-8")
    block = re.search(r"\.skip-link\s*\{([^{}]*)\}", css, re.DOTALL)
    assert block, "skip-link style should exist"
    assert "border: var(--focus-ring-width) solid var(--focus-ring)" in block.group(1), (
        "keyboard skip-link border should use shared focus tokens"
    )
