"""D-298 contracts for recurring typography and focus rules on product surfaces."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SURFACES = (
    ROOT / "src/hmi/dashboard",
    ROOT / "src/site/fleet/fleet/server/web",
    ROOT / "src/site/games/games/web",
)


def surface_styles():
    return [path for surface in SURFACES for path in surface.rglob("*.css")]


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

    assert not violations, "반복 타이포그래피 규칙은 D-298 토큰을 사용해야 합니다:\n" + "\n".join(violations)
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
                continue  # D-298 keeps a larger, viewport-specific map focus gap.
            if "outline:" not in declarations:
                continue
            if "var(--focus-ring-width)" not in declarations:
                violations.append(f"{path.relative_to(ROOT)} {selector.strip()}: focus width")
            if "var(--focus-ring-offset-outer)" not in declarations and "var(--focus-ring-offset)" not in declarations:
                violations.append(f"{path.relative_to(ROOT)} {selector.strip()}: focus offset")

    assert not violations, "표준 키보드 포커스 링은 공유 치수를 사용해야 합니다:\n" + "\n".join(violations)
