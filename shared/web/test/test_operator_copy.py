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

Two shapes carry no Hangul in the literal itself and are judged apart:

- a literal that is exactly a bare enum (`"OFFLINE"`) flowing to a text sink
  (`.textContent =`, `.innerText =`, `tag(`, `setText(`, `setStatus(`, `el(`,
  `setChip(`, `pill(`, `setAttribute("reason"|"aria-label"|...)`), outside a
  comparison (`=== "IDLE"`), an index (`[...]`) or a method-call argument;
- a template hole that interpolates a raw mode/state variable
  (`${requestedMode}`, `${state.mode || "OFF"}`) into Korean text. The fix is
  `enumLabel(MODE_LABEL, value)` or a local label map.
"""

from __future__ import annotations

from html.parser import HTMLParser
import os
from pathlib import Path
import re

import pytest

REPO = Path(__file__).resolve().parents[3]  # repository root (D-427: keys are repo-relative)


def _rel(path: Path) -> str:
    """Path relative to src/; Rosy Games left src/ for operations/ (D-427 wave 3b)."""
    return Path(os.path.relpath(path, REPO)).as_posix()


SURFACES = (
    ("middleware/ui/robot", "*.js"),
    ("middleware/ui/robot/panels", "**/*.js"),
    ("middleware/ui/robot", "index.html"),
    ("middleware/ui/robot", "surface.html"),
    ("operations/fleet/fleet/server/web", "*.js"),
    ("operations/fleet/fleet/server/web", "*.html"),
    ("operations/apps/games/games/web", "*.js"),
    ("operations/apps/games/games/web", "*.html"),
)

HANGUL = re.compile(r"[가-힣]")
RETIRED_TERMS = re.compile(r"(?i:profile|capability|line-follow)|Navigation|hardware 모드|프로필")
ENUM_WORDS = (r"IDLE|MANUAL|NAVIGATION|DOCKING|EMERGENCY|RUNNING|HOLDING|"
              r"UNDOCKED|UNDOCKING|DOCKED|CHARGING|DOCK_FAILED|WAITING|STALE|OFFLINE|"
              # Lane-follow modes and D-20 formation shapes (2026-10-10 console walkthrough).
              r"CAMERA_LINE|IR_LINE|LINE_FOLLOW|TRACKING|COLUMN|GRID|CIRCLE|TRAIL")
BARE_ENUMS = re.compile(r"(?<![A-Za-z0-9_])(" + ENUM_WORDS + r")(?![A-Za-z0-9_])")
ENUM_ONLY = re.compile(ENUM_WORDS)  # used with fullmatch

#: (path relative to src/, substring of the offending literal) -> reason.
#: Every entry must still match something, so a fixed string cannot leave a
#: stale exemption behind.
ALLOWLIST: dict[tuple[str, str], str] = {}

OPERATOR_ATTRIBUTES = {"aria-label", "placeholder", "reason", "alt"}


def _js_literals(text: str, holes: list[tuple[int, str, str]] | None = None) -> list[tuple[int, str]]:
    """Static text of every string/template literal, comments and regexes skipped.

    `holes`, when given, receives (line, raw hole expression, template text) for
    every `${...}` hole of a top-level template.
    """
    found: list[tuple[int, str]] = []
    i, n = 0, len(text)
    prev = ""  # last significant character, to tell a regex from a division

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    def read_template(start: int) -> int:
        """`start` is just after the backtick. Returns the index after the closing one."""
        j, parts, begin, raw_holes = start, [], start, []
        while j < n:
            ch = text[j]
            if ch == "\\":
                parts.append(text[begin:j + 2]); j += 2; begin = j; continue
            if ch == "`":
                parts.append(text[begin:j])
                found.append((line_of(start), "".join(parts)))
                if holes is not None:
                    holes.extend((line, expr, "".join(parts)) for line, expr in raw_holes)
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
                raw_holes.append((line_of(expr_start), text[expr_start:k - 1]))
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
        files.update(path for path in (REPO / folder).glob(pattern) if path.is_file())
    return sorted(files)


def problems(allowlist=None) -> list[tuple[str, int, str, str]]:
    allowlist = ALLOWLIST if allowlist is None else allowlist
    out = []
    for path in surface_files():
        rel = _rel(path)
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


#: A hole that is only a mode/state value (optionally with a `||`/`??` literal default).
RAW_ENUM_HOLE = re.compile(
    r"\s*(?:[A-Za-z_$][\w$]*\??\.)*[A-Za-z_$]*(?i:mode|state)\s*"
    r"(?:(?:\|\||\?\?)\s*([\"'])[^\"']*\1\s*)?")
TEXT_SINK = re.compile(
    r"\.(?:textContent|innerText)\s*=(?!=)"
    r"|(?<![\w$.])(?:tag|setText|setStatus|setChip|pill|el)\s*\("
    r"|\.setAttribute\s*\(\s*([\"'])(?:reason|aria-label|placeholder|alt)\1\s*,")
CONTINUES = ("?", ":", "+", "||", "&&", "??", ".")


def _mask_code(text: str) -> str:
    """Same length as `text`; string/template bodies, regexes and comments become spaces."""
    out, i, n, prev = list(text), 0, len(text), ""

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        ch = text[i]
        if text.startswith("//", i):
            end = text.find("\n", i); end = n if end < 0 else end
            blank(i, end); i = end; continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2); end = n if end < 0 else end + 2
            blank(i, end); i = end; continue
        if ch in "\"'`":
            k, depth = i + 1, 0
            while k < n:
                c = text[k]
                if c == "\\":
                    k += 2; continue
                if ch == "`" and text.startswith("${", k):
                    depth += 1; k += 2; continue
                if ch == "`" and depth and c == "}":
                    depth -= 1
                elif c == ch and not depth:
                    break
                k += 1
            blank(i + 1, k); i = k + 1; prev = "a"; continue
        if ch == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^"):
            k, in_class = i + 1, False
            while k < n and text[k] != "\n":
                c = text[k]
                if c == "\\":
                    k += 2; continue
                if c == "[": in_class = True
                elif c == "]": in_class = False
                elif c == "/" and not in_class: break
                k += 1
            blank(i + 1, k); i = k + 1; prev = "a"; continue
        if not ch.isspace():
            prev = ch
        i += 1
    return "".join(out)


def _sink_end(masked: str, start: int, is_call: bool) -> int:
    """End of the expression a text sink receives (on masked code, so strings cannot confuse it)."""
    depth, k, n = 0, start, len(masked)
    while k < n:
        c = masked[k]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return k
            depth -= 1
        elif depth == 0 and not is_call and c == ";":
            return k
        elif depth == 0 and not is_call and c == "\n":
            if not masked[k:].lstrip().startswith(CONTINUES) and \
                    not masked[:k].rstrip().endswith(CONTINUES + ("=", "(")):
                return k
        k += 1
    return n


def enum_text_problems(text: str) -> list[tuple[int, str, str]]:
    """Bare-enum literals flowing to a text sink, and raw mode/state holes in Korean templates."""
    out = []
    masked = _mask_code(text)
    for sink in TEXT_SINK.finditer(text):
        if masked[sink.start()] != text[sink.start()]:
            continue  # the sink's own text sits in a comment or a string
        is_call = sink.group(0).rstrip().endswith(("(", ","))
        end = _sink_end(masked, sink.end(), is_call)
        for lit in re.finditer(r"([\"'`])([A-Z_]+)\1", text[sink.end():end]):
            pos = sink.end() + lit.start()
            if masked[pos] != lit.group(1) or not ENUM_ONLY.fullmatch(lit.group(2)):
                continue  # inside a longer string, or not an enum
            before = masked[:pos].rstrip()
            after = masked[pos + len(lit.group(0)):].lstrip()
            if before.endswith(("===", "!==", "==", "!=", "case", "[")) \
                    or after.startswith(("===", "!==", "==", "!=", "]")) \
                    or re.search(r"\.[\w$]+\s*\($", before):
                continue  # a protocol key: compared, indexed or passed to a method
            out.append((text.count("\n", 0, pos) + 1, lit.group(0), "bare enum to text"))
    holes: list[tuple[int, str, str]] = []
    _js_literals(text, holes)
    for line, expr, template in holes:
        if HANGUL.search(template) and RAW_ENUM_HOLE.fullmatch(expr):
            out.append((line, "${" + expr + "}", "raw enum hole in Korean text"))
    return out


def test_the_lint_catches_bare_enums_flowing_to_text():
    """Mutation proof for the Hangul-free shapes (P1-1 review: OFFLINE on the Fleet roster)."""
    caught = (
        'node.textContent = "OFFLINE";',
        'const t = tag(online ? label : "OFFLINE", "crit");',
        'setText("mode", ok ? "IDLE" : "MANUAL");',
        'button.setAttribute("reason", "STALE");',
        'const t = tag(\n  a ? "상태 확인 불가" : b ? x\n    : "OFFLINE",\n  "crit");',
        'node.textContent = a\n  ? "대기"\n  : "OFFLINE";',
        'setStatus(out, `${requestedMode} 모드로 바꿉니다.`);',
        'const m = `차선 추종 ${current.mode || "OFF"}`;',
        'const m = `상태 ${state} · 도크`;',
        'log(`${id} 명령 하달 (${body.mode})`);',
    )
    for source in caught:
        assert enum_text_problems(source), source
    clean = (
        'node.textContent = mode === "IDLE" ? "대기" : "수동";',
        'node.textContent = LABEL["IDLE"];',
        'node.textContent = set.has("IDLE") ? "대기" : "";',
        'node.title = "OFFLINE";',
        'node.textContent = label;\nconst body = { mode: "IDLE" };',
        '// node.textContent = "OFFLINE";',
        'node.textContent = "OFFLINE 상태";',
        'setText("mode", `${enumLabel(MODE_LABEL, requestedMode)} 모드`);',
        'const url = `/api/${mode}`;',
        'const t = `Vision 응답 ${status}`;',
        'const t = `${stateUnavailable ? "확인 불가" : "정상"}`;',
    )
    for source in clean:
        assert enum_text_problems(source) == [], source


@pytest.mark.parametrize(("rel", "fixed", "regressed"), [
    ("operations/fleet/fleet/server/web/roster.js", '!robot.online ? "오프라인"', '!robot.online ? "OFFLINE"'),
    ("middleware/ui/robot/app.js", "`${enumLabel(MODE_LABEL, requestedMode)} 모드로", "`${requestedMode} 모드로"),
    ("middleware/ui/robot/settings.js", "상태 ${enumLabel(DOCK_STATE_LABEL, state)}", "상태 ${state}"),
    ("middleware/ui/robot/panels/console/line-follow.js",
     '`차선 추종 ${enumLabel(LINE_MODE_LABEL, current.mode || "OFF")}`', '`차선 추종 ${current.mode || "OFF"}`'),
    ("operations/fleet/fleet/server/web/signals.js",
     "${signalIntentLabel(row.intent?.mode)}", '${row.intent?.mode || "없음"}'),
])
def test_reverting_an_enum_text_fix_fails_the_lint(rel, fixed, regressed):
    """Mutation proof on the real files: undo one P1-1/P2-2 fix and the lint sees it."""
    source = (REPO / rel).read_text(encoding="utf-8-sig")
    assert fixed in source
    assert _enum_text_unallowed(rel, source) == []
    assert _enum_text_unallowed(rel, source.replace(fixed, regressed, 1)) != []


#: (path relative to src/, exact flagged hole or literal) -> reason. Stale entries fail.
ENUM_TEXT_ALLOWLIST: dict[tuple[str, str], str] = {
    ("middleware/ui/robot/panels/console/teleop.js", "${readErrors.state}"):
        "an error message keyed by the state endpoint, not a state value",
    ("middleware/ui/robot/panels/host/operations.js", '${data.runtime_mode || "실행 모드 미확인"}'):
        "runtime mode names core/motor/hardware are the CONCEPTS.md glossary preset names",
    ("middleware/ui/robot/panels/host/system.js", '${data.runtime_mode || "확인 불가"}'):
        "runtime mode names core/motor/hardware are the CONCEPTS.md glossary preset names",
    ("middleware/ui/robot/panels/host/operations.js", '${data.state || "상태 미확인"}'):
        "Host Agent release state is shown as received; no sanctioned Korean map exists yet",
}


def _enum_text_unallowed(rel: str, source: str) -> list[tuple[int, str, str]]:
    return [row for row in enum_text_problems(source) if (rel, row[1]) not in ENUM_TEXT_ALLOWLIST]


def test_no_bare_enum_reaches_operator_text():
    found = [(_rel(path), line, literal, why)
             for path in surface_files() if path.suffix == ".js"
             for line, literal, why in _enum_text_unallowed(
                 _rel(path), path.read_text(encoding="utf-8-sig"))]
    assert found == [], "\n".join(f"{rel}:{line}: {why}: {literal}" for rel, line, literal, why in found)


def test_every_enum_text_allowlist_entry_still_matches():
    for (rel, flagged), reason in ENUM_TEXT_ALLOWLIST.items():
        assert reason.strip(), (rel, flagged)
        rows = enum_text_problems((REPO / rel).read_text(encoding="utf-8-sig"))
        assert any(row[1] == flagged for row in rows), (rel, flagged)


def test_the_lint_sees_every_surface():
    rels = {_rel(path) for path in surface_files()}
    for expected in ("middleware/ui/robot/panels/console/mode.js", "middleware/ui/robot/app.js",
                     "operations/fleet/fleet/server/web/roster.js", "operations/fleet/fleet/server/web/index.html",
                     "operations/apps/games/games/web/board.js", "operations/apps/games/games/web/index.html"):
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
    for clean in ("내비게이션 지원", "실행 모드", "도킹 기능", "대형이 멈췄을 때만", "OFF 추종", "CPU 부하"):
        assert not (RETIRED_TERMS.search(clean) or BARE_ENUMS.search(clean)), clean


@pytest.mark.parametrize(("rel", "fixed", "regressed"), [
    ("middleware/ui/robot/panels/console/mode.js", '"내비게이션 기능을 쓸 수 있습니다."', '"Navigation 기능을 사용할 수 있습니다."'),
    ("middleware/ui/robot/panels/console/map.js", "승인된 하드웨어 실행 모드에서만", "승인된 hardware 모드에서만"),
    ("middleware/ui/robot/panels/setup/localization.js", '"내비게이션 기능 없음"', '"Navigation capability 미제공"'),
    ("middleware/ui/robot/panels/host/system.js", "`내비게이션 ${navigation", "`Navigation ${navigation"),
    ("operations/fleet/fleet/server/web/formation.js", "대형 재개는 대형이 멈췄을 때만", "대형 재개는 HOLDING일 때만"),
])
def test_reverting_a_fixed_string_fails_the_lint(rel, fixed, regressed):
    """Mutation proof on the real files: undo one US-009 fix and the lint sees it."""
    source = (REPO / rel).read_text(encoding="utf-8-sig")
    assert fixed in source
    assert list(_judge(_js_literals(source))) == []
    assert list(_judge(_js_literals(source.replace(fixed, regressed, 1)))) != []


def test_every_allowlist_entry_still_matches():
    rels = {_rel(path): path for path in surface_files()}
    for (rel, needle), reason in ALLOWLIST.items():
        assert reason.strip(), (rel, needle)
        assert rel in rels, rel
        assert any(needle in literal for _, literal in _copy(rels[rel])), (rel, needle)


def test_operator_copy_uses_the_sanctioned_korean_terms():
    found = problems()
    assert found == [], "\n".join(f"{rel}:{line}: {why}: {literal[:120]}" for rel, line, literal, why in found)
