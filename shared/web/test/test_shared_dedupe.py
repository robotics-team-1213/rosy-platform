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
PENDING_TOKENS = {"--row-dense"}


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
UNUSED_CEILING = {"exports": 37, "test_only_exports": 5, "css_classes": 1, "html_ids": 9}
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
        for name in sorted(set(re.findall(r"\bid=\"([A-Za-z][\w-]*)\"", html))):
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
