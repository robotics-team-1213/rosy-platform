"""D-359 US-009 — operator copy lint (PRODUCT.md "운용자 어휘는 한국어 평문", CONCEPTS.md).

Every Korean UI string on the robot dashboard, the Fleet console and the games
board speaks the sanctioned Korean terms. A literal that carries Hangul is
operator copy, so it must not carry:

- implementation vocabulary the glossary retires for operators: `profile`,
  `capability`, `hardware 모드`, `Navigation`, `프로필` (CONCEPTS: Runtime mode
  → 실행 모드, Capability → 기능);
- a bare protocol enum (`IDLE`, `MANUAL`, `RUNNING`, ...). Enums stay in `title`
  and in data attributes, never in the words an operator reads.

Only the static text of a literal is judged: `${expr}` holes are replaced, and
their own literals are judged separately, so `mode === "IDLE"` inside a hole is
a protocol key, not copy. Comments are skipped. HTML text and the operator-read
attributes (`aria-label`, `placeholder`, `reason`, `alt`) are judged; `title`
is the sanctioned home of enums and is not.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re

import pytest

SRC = Path(__file__).resolve().parents[3]

SURFACES = (
    ("hmi/dashboard", "*.js"),
    ("hmi/dashboard/panels", "**/*.js"),
    ("hmi/dashboard", "index.html"),
    ("hmi/dashboard", "surface.html"),
    ("site/fleet/fleet/server/web", "*.js"),
    ("site/fleet/fleet/server/web", "*.html"),
    ("site/games/games/web", "*.js"),
    ("site/games/games/web", "*.html"),
)

HANGUL = re.compile(r"[가-힣]")
RETIRED_TERMS = re.compile(r"(?i:profile|capability)|Navigation|hardware 모드|프로필")
BARE_ENUMS = re.compile(
    r"(?<![A-Za-z0-9_])(IDLE|MANUAL|NAVIGATION|DOCKING|EMERGENCY|RUNNING|HOLDING|"
    r"UNDOCKED|UNDOCKING|DOCKED|CHARGING|DOCK_FAILED|WAITING|STALE|OFFLINE)(?![A-Za-z0-9_])")

#: (path relative to src/, substring of the offending literal) -> reason.
#: Every entry must still match something, so a fixed string cannot leave a
#: stale exemption behind.
ALLOWLIST: dict[tuple[str, str], str] = {}

OPERATOR_ATTRIBUTES = {"aria-label", "placeholder", "reason", "alt"}


def _js_literals(text: str) -> list[tuple[int, str]]:
    """Static text of every string/template literal, comments and regexes skipped."""
    found: list[tuple[int, str]] = []
    i, n = 0, len(text)
    prev = ""  # last significant character, to tell a regex from a division

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    def read_template(start: int) -> int:
        """`start` is just after the backtick. Returns the index after the closing one."""
        j, parts, begin = start, [], start
        while j < n:
            ch = text[j]
            if ch == "\\":
                parts.append(text[begin:j + 2]); j += 2; begin = j; continue
            if ch == "`":
                parts.append(text[begin:j])
                found.append((line_of(start), "".join(parts)))
                return j + 1
            if ch == "$" and j + 1 < n and text[j + 1] == "{":
                parts.append(text[begin:j])
                hole = len(parts); parts.append("${}")
                depth, k = 1, j + 2
                expr_start = k
                while k < n and depth:
                    c = text[k]
                    if c in "\"'`":
                        k = skip_string(k)
                        continue
                    if c == "{": depth += 1
                    elif c == "}": depth -= 1
                    k += 1
                inner = _js_literals(text[expr_start:k - 1])
                found.extend((line_of(expr_start) + line - 1, lit) for line, lit in inner)
                # `Navigation ${ok ? "사용 가능" : "미제공"}` renders as Korean copy even
                # though its static text is Latin: Korean hole text joins the template.
                spoken = [lit for _, lit in inner if HANGUL.search(lit)]
                if spoken:
                    parts[hole] = "${" + " | ".join(spoken) + "}"
                j = k; begin = j; continue
            j += 1
        return n

    def skip_string(j: int) -> int:
        quote = text[j]
        if quote == "`":
            # nested template inside a hole: judged by the recursive call
            depth_mark = len(found)
            end = read_template(j + 1)
            del found[depth_mark:]
            return end
        k = j + 1
        while k < n and text[k] != quote:
            k += 2 if text[k] == "\\" else 1
        return k + 1

    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1; continue
        if text.startswith("//", i):
            i = text.find("\n", i); i = n if i < 0 else i; continue
        if text.startswith("/*", i):
            i = text.find("*/", i + 2); i = n if i < 0 else i + 2; continue
        if ch in "\"'":
            end = skip_string(i)
            found.append((line_of(i), text[i + 1:end - 1]))
            i = end; prev = "a"; continue
        if ch == "`":
            i = read_template(i + 1); prev = "a"; continue
        if ch == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^" or text[max(0, i - 7):i].rstrip().endswith("return")):
            k, in_class = i + 1, False
            while k < n and text[k] != "\n":
                c = text[k]
                if c == "\\": k += 2; continue
                if c == "[": in_class = True
                elif c == "]": in_class = False
                elif c == "/" and not in_class: break
                k += 1
            i = k + 1; prev = "a"; continue
        prev = ch
        i += 1
    return found


class _HtmlCopy(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[int, str]] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for name, value in attrs:
            if name in OPERATOR_ATTRIBUTES and value:
                self.found.append((self.getpos()[0], value))

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.found.append((self.getpos()[0], data.strip()))


def _copy(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".html":
        parser = _HtmlCopy()
        parser.feed(text)
        return parser.found
    return _js_literals(text)


def surface_files() -> list[Path]:
    files: set[Path] = set()
    for folder, pattern in SURFACES:
        files.update(path for path in (SRC / folder).glob(pattern) if path.is_file())
    return sorted(files)


def problems(allowlist=None) -> list[tuple[str, int, str, str]]:
    allowlist = ALLOWLIST if allowlist is None else allowlist
    out = []
    for path in surface_files():
        rel = path.relative_to(SRC).as_posix()
        for line, literal, why in _judge(_copy(path)):
            if any(key[0] == rel and key[1] in literal for key in allowlist):
                continue
            out.append((rel, line, literal, why))
    return out


def _judge(literals):
    for line, literal in literals:
        if not HANGUL.search(literal):
            continue
        why = []
        if RETIRED_TERMS.search(literal):
            why.append("retired term " + RETIRED_TERMS.search(literal).group(0))
        if BARE_ENUMS.search(literal):
            why.append("bare enum " + BARE_ENUMS.search(literal).group(0))
        if why:
            yield line, literal, "; ".join(why)


def test_the_lint_sees_every_surface():
    rels = {path.relative_to(SRC).as_posix() for path in surface_files()}
    for expected in ("hmi/dashboard/panels/console/mode.js", "hmi/dashboard/app.js",
                     "site/fleet/fleet/server/web/roster.js", "site/fleet/fleet/server/web/index.html",
                     "site/games/games/web/board.js", "site/games/games/web/index.html"):
        assert expected in rels


def test_the_lint_reads_literals_the_way_a_browser_would():
    source = (
        '// "Navigation 주석" is a comment\n'
        'const a = "Navigation을 쓸 수 없습니다";\n'
        'const b = `현재 모드: ${mode === "IDLE" ? "대기" : "수동"}`;\n'
        'const c = `${x}/2 프로필` ; const r = /["\']/g;\n'
        "const d = 'IDLE 모드';\n"
    )
    literals = [literal for _, literal in _js_literals(source)]
    assert "Navigation을 쓸 수 없습니다" in literals
    assert "현재 모드: ${대기 | 수동}" in literals and "IDLE" in literals
    assert "${}/2 프로필" in literals
    assert "IDLE 모드" in literals
    spoken = [literal for _, literal in _js_literals('const e = `Navigation ${ok ? "사용 가능" : "미제공"}`;')]
    assert "Navigation ${사용 가능 | 미제공}" in spoken
    assert not any("주석" in literal for literal in literals)


def test_the_lint_catches_what_it_is_meant_to_catch():
    """Mutation proof: each banned shape, planted in an otherwise clean literal, is caught."""
    for planted in ("이 profile에서", "도킹 capability", "승인된 hardware 모드", "Navigation 지원",
                    "로봇 프로필", "현재 모드: IDLE", "RUNNING일 때만", "HOLDING일 때만",
                    "상태 UNDOCKED", "WAITING", "STALE 수신"):
        literal = planted if HANGUL.search(planted) else f"{planted} 수신"
        assert RETIRED_TERMS.search(literal) or BARE_ENUMS.search(literal), planted
    for clean in ("내비게이션 지원", "실행 모드", "도킹 기능", "대형 유지 중일 때만", "OFF 추종", "CPU 부하"):
        assert not (RETIRED_TERMS.search(clean) or BARE_ENUMS.search(clean)), clean


@pytest.mark.parametrize(("rel", "fixed", "regressed"), [
    ("hmi/dashboard/panels/console/mode.js", '"내비게이션 기능을 쓸 수 있습니다."', '"Navigation 기능을 사용할 수 있습니다."'),
    ("hmi/dashboard/panels/console/map.js", "승인된 하드웨어 실행 모드에서만", "승인된 hardware 모드에서만"),
    ("hmi/dashboard/panels/setup/localization.js", '"내비게이션 기능 없음"', '"Navigation capability 미제공"'),
    ("hmi/dashboard/panels/host/system.js", "`내비게이션 ${navigation", "`Navigation ${navigation"),
    ("site/fleet/fleet/server/web/formation.js", '"대형 유지 중일 때만"', '"HOLDING일 때만"'),
])
def test_reverting_a_fixed_string_fails_the_lint(rel, fixed, regressed):
    """Mutation proof on the real files: undo one US-009 fix and the lint sees it."""
    source = (SRC / rel).read_text(encoding="utf-8-sig")
    assert fixed in source
    assert list(_judge(_js_literals(source))) == []
    assert list(_judge(_js_literals(source.replace(fixed, regressed, 1)))) != []


def test_every_allowlist_entry_still_matches():
    rels = {path.relative_to(SRC).as_posix(): path for path in surface_files()}
    for (rel, needle), reason in ALLOWLIST.items():
        assert reason.strip(), (rel, needle)
        assert rel in rels, rel
        assert any(needle in literal for _, literal in _copy(rels[rel])), (rel, needle)


def test_operator_copy_uses_the_sanctioned_korean_terms():
    found = problems()
    assert found == [], "\n".join(f"{rel}:{line}: {why}: {literal[:120]}" for rel, line, literal, why in found)
