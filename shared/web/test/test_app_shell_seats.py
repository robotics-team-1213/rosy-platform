"""D-741 — 공용 셸 자리: 토큰, 공용 시트, 등록."""
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
TOKENS = (WEB / "tokens.css").read_text(encoding="utf-8")
BASE_SCALE = {f"--space-{i}" for i in range(1, 7)}


def _decl(name: str) -> str | None:
    found = re.search(rf"^\s*{re.escape(name)}\s*:\s*([^;]+);", TOKENS, re.MULTILINE)
    return found.group(1).strip() if found else None


def test_seat_dimensions_are_tokens():
    assert _decl("--appbar-height") == "64px"
    assert _decl("--rail-track") == "72px"
    assert _decl("--subnav-track") == "232px"
    assert _decl("--context-track") == "360px"
    assert _decl("--pathbar-height") == "56px"


def test_seat_spacing_roles_reference_the_base_scale():
    for role in ("--inset-rail", "--gap-rail", "--inset-subnav", "--inset-pathbar",
                 "--gap-pathbar", "--inset-pane", "--gap-pane"):
        value = _decl(role)
        assert value, f"{role} 토큰이 없다"
        refs = set(re.findall(r"var\((--[a-z0-9-]+)", value))
        assert refs and refs <= BASE_SCALE, f"{role}은 기본 간격 척도만 참조해야 한다: {value}"


def test_control_line_and_chrome_surface_are_roles():
    assert _decl("--line-40") == "color-mix(in oklab, var(--ink) 40%, transparent)"
    assert _decl("--control-line") == "var(--line-40)"
    assert _decl("--surface-chrome") == "var(--ground-raise)"
    assert _decl("--border-default") == "var(--line-14)", "면을 가르는 선은 그대로 둔다"
