"""App import boundary (D-1036 addendum 3, 2026-11-19 app split).

An app's code imports only its own app and `core`; `core` imports no app. Apps come from
`tools/harness/platform_parts.yaml` `app:` (`affected_repo.app_of`); an imported module's owner is the
root whose `import_prefix` matches it longest. Files of app `repo` are not checked. `ALLOWED_EDGES` are
allowed directions. The pairs that already cross are frozen in `known_app_imports.txt`: a new pair fails
and a pair that no longer crosses must be deleted, so the list only shrinks.

shortcut: 정적 import만 본다. sys.path·importlib 경로 적재는 못 본다(omx는 test_omx_cell_boundary가
문자열로 보완). 경로 적재 우회가 늘면 문자열 검사로 확장한다.
"""

from __future__ import annotations

import ast
import functools
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "tools" / "harness"))
from _ast_imports import iter_import_nodes  # noqa: E402
from affected_repo import app_classifier  # noqa: E402

MANIFEST = yaml.safe_load((ROOT / "tools" / "harness" / "platform_parts.yaml").read_text(encoding="utf-8"))
KNOWN = Path(__file__).with_name("known_app_imports.txt")
# Consumer -> a library with no channel of its own (vision ships in the consumer's image), or the same
# image and owner (Fleet runs Account in process): release-split-1118 panel B, 2026-11-19.
ALLOWED_EDGES = {("pinky", "vision"), ("omx-cell", "vision"), ("learning", "vision"), ("site-fleet", "account")}
# par-C-decision §4 (2026-11-19, release-split): learning 9 move with the learning repo, situation 2 go to
# structured_output next, omx-cell 2 wait for a core client. Files calling Ollama's HTTP API directly besides rosy.decision.structured_output.
OLLAMA_BASELINE = 14
PREFIXES = [(prefix, root["app"]) for root in MANIFEST["roots"] for prefix in root.get("import_prefix") or []]
_PREFIXES_BY_TOP: dict[str, list[tuple[int, int, str, str]]] = {}
for _idx, (_prefix, _app) in enumerate(PREFIXES):
    _PREFIXES_BY_TOP.setdefault(_prefix.split(".", 1)[0], []).append((len(_prefix), -_idx, _prefix, _app))
for _bucket in _PREFIXES_BY_TOP.values():
    _bucket.sort(key=lambda item: (item[0], item[1]), reverse=True)
_CLASSIFY = app_classifier(MANIFEST)
HEADER = """# App import boundary allowlist (test_app_imports.py, D-1036 addendum 3, 2026-11-19).
# <path> -> <owner_app>: a file that imports another app's module. Only removals; a new pair fails.
# Rule: an app imports only itself and core; core imports no app. Regenerate (shrink only):
#   python test/architecture/test_app_imports.py --write
"""


def owner(name: str) -> str | None:
    for _, _, prefix, app in _PREFIXES_BY_TOP.get(name.split(".", 1)[0], ()):
        if name == prefix or name.startswith(prefix + "."):
            return app
    return None


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8",
                         check=True).stdout
    return [line for line in out.splitlines() if line]


def _imports(tree: ast.AST) -> set[str]:
    names = set()
    for node in iter_import_nodes(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif node.level == 0 and node.module:
            names.add(node.module)
    return names


@functools.cache
def scan() -> tuple[set[str], list[str]]:
    """(`path -> owner_app` pairs that cross an app boundary, files that did not parse)."""
    found, broken = set(), []
    for path in _git("ls-files", "--cached", "*.py"):
        app = _CLASSIFY(path)
        if app == "repo" or not (ROOT / path).is_file():
            continue
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
            tree = ast.parse(text, filename=path)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            broken.append(path)
            continue
        if "import" not in text:
            continue
        for name in _imports(tree):
            other = owner(name)
            if other not in (None, app, "core") and (app, other) not in ALLOWED_EDGES:
                found.add(f"{path} -> {other}")
    return found, broken


def known() -> set[str]:
    return {line.strip() for line in KNOWN.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")}


def test_every_app_file_parses():
    assert scan()[1] == []


def test_no_new_cross_app_imports():
    new = sorted(scan()[0] - known())
    assert not new, "자기 앱이나 core 계약을 거쳐라, D-1036 addendum 3:\n" + "\n".join(new)


def test_known_list_has_no_stale_lines():
    stale = sorted(known() - scan()[0])
    assert not stale, "더는 넘지 않는 쌍이다. known_app_imports.txt에서 지워라(--write):\n" + "\n".join(stale)


def test_owner_resolution():
    assert owner("fleet.server.x") == "site-fleet"
    assert owner("core_common.protocol") == "core"
    assert owner("control.control.actuation") == "pinky"
    assert owner("rosy.notifications.channels") == "site-fleet"
    assert owner("json") is None
    assert {app for edge in ALLOWED_EDGES for app in edge} <= set(MANIFEST["apps"])


def _is_test(path: str) -> bool:
    return path.startswith("test/") or "/test/" in path or path.rsplit("/", 1)[-1].startswith("test_")


def test_ollama_http_callers_do_not_grow():
    hits = _git("grep", "--cached", "-l", "-E", "/api/(chat|generate)", "--", "*.py")
    callers = [path for path in hits if not path.startswith("docs/") and not _is_test(path)
               and path != "operations/decision/src/rosy/decision/structured_output.py"]
    assert len(callers) <= OLLAMA_BASELINE, (
        "rosy.decision.structured_output(site-fleet)이나 앱의 기존 클라이언트를 써라, think:false 규칙:\n"
        + "\n".join(callers))


if __name__ == "__main__" and "--write" in sys.argv:
    pairs = sorted(scan()[0])
    KNOWN.write_text(HEADER + "".join(f"{pair}\n" for pair in pairs), encoding="utf-8", newline="\n")
    print(f"{len(pairs)} pairs written to {KNOWN.name}")
