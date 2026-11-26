"""One definition per shared need (2026-11-18 S3): .sr-only lives in components.css, and a token nobody reads is deleted."""

from pathlib import Path
import re

WEB = Path(__file__).resolve().parents[1]
REPO = WEB.parents[1]
# untracked trees a test PC may hold (11-18 review F4: the ratchets below need the same file set everywhere)
SKIP = {".git", "node_modules", ".worktrees", "vendor", "docs", "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache",
        ".tox", "site-packages", "build", "dist"}


def _sources(suffixes):
    for path in REPO.rglob("*"):
        if path.suffix in suffixes and path.is_file() and not SKIP & set(path.relative_to(REPO).parts):
            yield path


def test_sr_only_is_defined_once_in_components_css():
    pattern = re.compile(r"\.sr-only\b[^{}]*\{[^}]*(?:clip|1px)")
    stray = [p.relative_to(REPO).as_posix() for p in _sources({".css"}) if p.name != "components.css" and pattern.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert not stray, f".sr-only is redefined in {stray}; use the shared class"


# Density tokens whose first readers (map and control stylesheets) arrive in later UI slices. Only shrinks: an entry that is
# read by then fails the test until it is removed here.
PENDING_TOKENS = set()


def test_every_token_in_tokens_css_is_read_somewhere():
    tokens = set(re.findall(r"^\s*(--[a-z0-9-]+):", (WEB / "tokens.css").read_text(encoding="utf-8"), re.M))
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in _sources({".css", ".js", ".html", ".mjs", ".py", ".kt", ".gradle", ".xml", ".yaml"}) if p.name != "tokens.css" and p != Path(__file__))
    unused = sorted(t for t in tokens if t not in text and not re.search(rf"var\({re.escape(t)}\b", (WEB / "tokens.css").read_text(encoding="utf-8")))
    assert unused == sorted(PENDING_TOKENS), f"tokens nobody reads: {unused}; delete them, or lower PENDING_TOKENS when the first reader lands"


# 11-18 UI 패널 게이트 ②: 소비자 0인 이름 래칫. 정의 파일 밖(시험·middleware 포함 저장소 전체, md 제외)에 이름이
# 한 번도 안 나오면 소비자 0이다. 수가 늘면 실패, 줄면 상한을 같은 변경에서 내린다(test_size_limits 방식).
# 한계: 음성 단언 시험(count == 0)도 소비자로 센다. 템플릿 조립 '접두-${'는 그 접두로 시작하는 클래스를 쓴 것으로 본다.
PRODUCT_ROOTS = (REPO / "applications" / "fleet" / "web", WEB)
CONSUMERS = {".js", ".mjs", ".html", ".inc", ".py", ".ts"}
#: 시험만 쓰는 export 중 시험 이음매(지우면 시험이 제품을 못 건드림). 이유 필수, 늘리지 않는다.
TEST_SEAMS: dict[str, str] = {}
UNUSED_CEILING = {"exports": 0, "test_only_exports": 3, "css_classes": 1, "html_ids": 0}
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_HYPHEN_WORD = re.compile(r"[A-Za-z_][\w-]*")
_EXPORT = re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z_$][\w$]*)", re.M)
_EXPORT_LIST = re.compile(r"^export\s*\{([^}]*)\}", re.M)
_CACHE = {}


def _rel(path):
    return path.relative_to(REPO).as_posix()


def _consumer_texts():
    if "texts" not in _CACHE:
        _CACHE["texts"] = {p: p.read_text(encoding="utf-8", errors="ignore") for p in _sources(CONSUMERS)}
    return _CACHE["texts"]


def _product(suffix):
    for root in PRODUCT_ROOTS:
        for path in root.rglob(f"*{suffix}"):
            if path.is_file() and not ({"test", "vendor", "node_modules"} & set(path.relative_to(REPO).parts)):
                yield path


def _exports(text):
    names = _EXPORT.findall(text)
    for body in _EXPORT_LIST.findall(text):
        names += [part.split(" as ")[-1].strip() for part in body.split(",") if part.strip()]
    return names


def unused_names():
    """{kind: [where name]} for exports, test-only exports, CSS classes and HTML ids nobody else names."""
    texts = _consumer_texts()
    tokens = {p: set(_IDENT.findall(t)) for p, t in texts.items()}
    found = {"exports": [], "test_only_exports": [], "css_classes": [], "html_ids": []}
    for path in _product(".js"):
        own = texts.get(path) or path.read_text(encoding="utf-8", errors="ignore")
        for name in _exports(own):
            users = [q for q, words in tokens.items() if q != path and name in words]
            if not users:
                found["exports"].append(f"{_rel(path)} {name}")
            elif name not in TEST_SEAMS and all("test" in q.relative_to(REPO).parts for q in users) \
                    and len(re.findall(rf"(?<![\w$]){re.escape(name)}(?![\w$])", own)) <= 1:
                found["test_only_exports"].append(f"{_rel(path)} {name}")
    words = set()
    for text in texts.values():
        words.update(_HYPHEN_WORD.findall(text))
    prefixes = {m for text in texts.values() for m in re.findall(r"([A-Za-z][\w-]*-)\$\{", text)}
    for path in _product(".css"):
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8", errors="ignore"), flags=re.S)
        css = re.sub(r"\"[^\"]*\"|'[^']*'", '""', css)
        classes = {c for prelude in re.findall(r"([^{};]+)\{", css) if not prelude.strip().startswith("@")
                   for c in re.findall(r"\.(-?[A-Za-z_][\w-]*)", prelude)}
        found["css_classes"] += [f"{_rel(path)} .{c}" for c in sorted(classes)
                                 if c not in words and not any(c.startswith(x) for x in prefixes)]
    css_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in _sources({".css"}))
    for path in [*_product(".html"), *_product(".inc")]:
        html = texts.get(path, "")
        # role-lock-note IDs are read dynamically via element.id by authorization.js for aria-describedby.
        dynamic_role_lock_ids = {
            m.group(1)
            for tag in re.findall(r"<[^>]+>", html)
            if "role-lock-note" in tag and (m := re.search(r'\bid="([A-Za-z][\w-]*)"', tag))
        }
        for name in sorted(set(re.findall(r"\bid=\"([A-Za-z][\w-]*)\"", html))):
            if name in dynamic_role_lock_ids or any(name.startswith(x) for x in prefixes):
                continue
            here = len(re.findall(rf"(?<![\w-]){re.escape(name)}(?![\w-])", html))
            elsewhere = f"#{name}" in css_text or any(q != path and name in t for q, t in texts.items())
            if here <= 1 and not elsewhere:
                found["html_ids"].append(f"{_rel(path)} #{name}")
    return found


def test_names_nobody_uses_only_go_down():
    found = unused_names()
    for kind, ceiling in UNUSED_CEILING.items():
        count = len(found[kind])
        assert count <= ceiling, f"{kind}: {count} > {ceiling}; delete or use them: {found[kind][:20]}"
        assert count == ceiling, f"{kind} fell to {count}; lower UNUSED_CEILING[{kind!r}] to {count} in the same change"


# 정본 밖 재정의·본문 복제·직접 쓰기 래칫 (구 patterns.yaml helpers/direct/duplicate_bodies 통합)
HELPERS = (
    {"name": "node", "module": "shared/web/control-dom.js", "aliases": ["nodeWithText"], "ceiling": 1},
    {"name": "setOff", "module": "shared/web/cause-line.js", "aliases": ["setOffBy", "guard", "gate", "blockWith", "setReason"], "ceiling": 0},
    {"name": "iconSvg", "module": "shared/web/ui.js", "aliases": ["iconNode"], "ceiling": 0},
    # 2026-11-26 패널 C-1: 3×3 투영 사본 4벌(#893 Calibration 포함)을 하나로. Calibration 화면도 본다(HELPER_ROOTS).
    {"name": "invert3", "module": "shared/web/plane-math.js", "aliases": ["invert3x3", "applyH", "applyHomography"], "ceiling": 0},
    # 2026-11-26: World 2D 지도 규칙 사본(#922 map-rules.js)과 Fleet 사본을 /common/map-rules.js 하나로. World 화면도 본다.
    {"name": "scaleBar", "module": "shared/web/map-rules.js", "aliases": ["viewTurnOf", "placeText", "stamp", "mapEvidence"], "ceiling": 0,
     "roots": ["applications/world/web"]},
)
#: 도우미 재정의는 /common 을 읽는 다른 화면에서도 찾는다. 이름·중복 래칫의 범위(PRODUCT_ROOTS)는 그대로 둔다.
HELPER_ROOTS = (*PRODUCT_ROOTS, REPO / "applications" / "calibration" / "web")
DIRECT = (
    {"what": "reason 속성 직접 쓰기", "pattern": r"""(?:set|remove)Attribute\(\s*["']reason["']""", "owners": ["shared/web/ui.js", "shared/web/cause-line.js"], "ceiling": 4},
    {"what": "운영자 역할 직접 비교", "pattern": r"""role\s*[!=]==?\s*["']operator["']""", "owners": ["applications/fleet/web/shared/authorization.js"], "ceiling": 0},
    {"what": "권한 문구 직접 쓰기", "pattern": "운영자 권한이 필요합니다", "owners": ["applications/fleet/web/shared/authorization.js"], "ceiling": 0},
    {"what": "'초 전' 손 포맷", "pattern": "초 전", "owners": ["shared/web/core_ui_logic.js", "shared/web/component-gallery.js"], "ceiling": 0},
)
DUPLICATE_BODIES_CEILING = 0
_JS_NOISE = re.compile(r"""//[^\n]*|/\*.*?\*/|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`""", re.S)
_JS_STRINGS_KEPT = re.compile(r"""("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`)|//[^\n]*|/\*.*?\*/""", re.S)
_FUNCTION_HEAD = re.compile(r"\bfunction\s+[\w$]+\s*\([^)]*\)\s*\{|\b(?:const|let)\s+[\w$]+\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{")


def js_code(text):
    """Source with comments dropped and string literals emptied: what is left can really execute."""
    return _JS_NOISE.sub(lambda match: '""' if match.group(0)[0] in "\"'`" else "", text)


def js_without_comments(text):
    """Source with comments dropped; strings stay."""
    return _JS_STRINGS_KEPT.sub(lambda match: match.group(1) or "", text)


def product_scripts(roots=PRODUCT_ROOTS):
    for root in roots:
        for path in sorted(root.rglob("*.js")):
            if not ({"test", "vendor", "node_modules"} & set(path.relative_to(REPO).parts)):
                yield path.relative_to(REPO).as_posix(), path.read_text(encoding="utf-8", errors="ignore")


def helper_redefinitions(scripts, row):
    """Places outside the helper's own module that define its name or an alias with function/const/let."""
    names = "|".join(re.escape(n) for n in [row["name"], *row.get("aliases", [])])
    pattern = re.compile(rf"(?:\bfunction\s+(?:{names})\s*\(|\b(?:const|let|var)\s+(?:{names})\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[\w$]+\s*=>))")
    return [f"{rel}:{js_code(text)[:m.start()].count(chr(10)) + 1}" for rel, text in scripts if rel != row["module"]
            for m in pattern.finditer(js_code(text))]


def direct_uses(scripts, row):
    """Lines outside the owners that write the pattern directly (comments ignored, strings kept)."""
    pattern = re.compile(row["pattern"])
    return [f"{rel}:{n}" for rel, text in scripts if rel not in row["owners"]
            for n, line in enumerate(js_without_comments(text).splitlines(), 1) if pattern.search(line)]


def duplicate_bodies(scripts, minimum=35):
    """Groups of function bodies (strings emptied, whitespace dropped) that appear in two or more files."""
    seen = {}
    for rel, text in scripts:
        code = js_code(text)
        for head in _FUNCTION_HEAD.finditer(code):
            depth, start = 0, head.end() - 1
            for end in range(start, len(code)):
                depth += {"{": 1, "}": -1}.get(code[end], 0)
                if depth == 0:
                    break
            body = re.sub(r"\s+", "", code[start:end + 1])
            if len(body) >= minimum:
                seen.setdefault(body, set()).add(rel)
    return sorted(sorted(files) for files in seen.values() if len(files) > 1)


def _ratchet(label, found, ceiling):
    assert len(found) <= ceiling, f"{label}: {len(found)} > ceiling {ceiling}; use the shared one instead: {found[:15]}"
    assert len(found) == ceiling, f"{label} fell to {len(found)}; lower its ceiling in test_shared_dedupe.py to {len(found)}"


def test_helpers_are_defined_once_and_direct_writes_only_go_down():
    scripts = list(product_scripts())
    helper_scripts = list(product_scripts(HELPER_ROOTS))
    for row in HELPERS:
        assert (REPO / row["module"]).is_file() and re.search(rf"\b{re.escape(row['name'])}\b", (REPO / row["module"]).read_text(encoding="utf-8")), row
        seen = list(product_scripts((*HELPER_ROOTS, *(REPO / r for r in row["roots"])))) if "roots" in row else helper_scripts
        _ratchet(f"redefined {row['name']}", helper_redefinitions(seen, row), row["ceiling"])
    for row in DIRECT:
        assert row["owners"] and all((REPO / owner).is_file() for owner in row["owners"]), row
        _ratchet(f"direct {row['what']}", direct_uses(scripts, row), row["ceiling"])
    _ratchet("duplicate function bodies", duplicate_bodies(scripts), DUPLICATE_BODIES_CEILING)


def test_the_helper_gate_sees_copies_and_ignores_comments():
    row = {"name": "setOff", "module": "shared/web/cause-line.js", "aliases": ["guard"]}
    copy = ("a.js", "// function guard(x) {}\nfunction guard(control, reason) { control.disabled = Boolean(reason); }\nconst guard = 1;\nconst guard = (c) => c;")
    assert helper_redefinitions([copy], row) == ["a.js:2", "a.js:4"]
    direct = {"pattern": r"role\s*[!=]==?\s*[\"']operator", "owners": ["auth.js"]}
    assert direct_uses([("b.js", 'if (role === "operator") go();\n// role === "operator"'), ("auth.js", 'role === "operator"')], direct) == ["b.js:1"]
    body = "function a(n) { const el = document.createElement(n); el.hidden = true; return el; }"
    assert duplicate_bodies([("x.js", body), ("y.js", body.replace("a(", "b("))]) == [["x.js", "y.js"]]
