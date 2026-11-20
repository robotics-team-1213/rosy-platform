"""Dynamic cross-app coupling ratchet: path loads (a) and script launches (b) the static import scan cannot see.

The import ratchet reads `import` statements. An app can also reach into another app's folder by
`sys.path` edits, `importlib`, `runpy` (type a) or by running its `.py`/`.sh` with `subprocess` (type b).
This test finds those statements, names the owning app of each path string with
`tools/harness/affected_repo.app_of` and `platform_parts.yaml`, and freezes today's set in
`known_app_dynamic_refs.txt` (one `<file> -> <app> (<a|b>)` row each). A new row fails; a row
that no longer occurs fails too, so the list only shrinks. core, tooling and repo are not product apps
and are not counted. Types c (file reads), s (shell/yml lines) and d (CI strings) are out of scope.
Read-only: nothing here edits a file.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "harness"))
from affected_repo import app_of  # noqa: E402

KNOWN = Path(__file__).with_name("known_app_dynamic_refs.txt")
PARTS = ROOT / "tools" / "harness" / "platform_parts.yaml"
PRODUCT_APPS = {"site-fleet", "omx-cell", "pinky", "account", "vision", "learning"}
LOAD_WORDS = ("sys.path", "addsitedir", "import_module", "spec_from_file_location", "run_path")
RUN_WORDS = ("subprocess", "Popen", "os.system", "check_call", "check_output")
SCRIPT = re.compile(r"\.(py|sh)\b")
ROW = re.compile(r"^(?P<file>\S+) -> (?P<app>[\w-]+) \((?P<kind>[ab])\)$")


def _entries(parts: dict) -> list[tuple[list[str], str]]:
    """Folder paths of two or more parts that name an app, deepest first (a wildcard key is not a folder)."""
    paths = [root["path"] for root in parts["roots"]] + [k for k in parts["app_subtrees"] if "*" not in k]
    # test/, docs and .github are shared hubs, not an app's folder to load code from.
    paths = [p for p in paths if len(p.split("/")) >= 2 and not p.startswith(("test/", "docs", ".github"))]
    return sorted(((p.split("/"), p) for p in paths), key=lambda e: -len(e[0]))


def _targets(tokens: list[str], entries, parts: dict) -> dict[str, str]:
    """app -> folder for every folder that `tokens` spells out in a row; only the deepest folder at a
    start position counts, so learning/envs/isaac/assets is omx-cell and not also learning."""
    found: dict[str, str] = {}
    for start in range(len(tokens)):
        for comps, path in entries:
            if tokens[start:start + len(comps)] == comps:
                found.setdefault(app_of(path + "/x.py", parts), path)
                break
    return found


def _tokens(node: ast.AST) -> list[str]:
    out: list[str] = []
    strings = [n for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for n in sorted(strings, key=lambda n: (n.lineno, n.col_offset)):  # source order: ROOT / "a" / "b" nests right-first
        out += [t for t in re.split(r"[/\\]+", n.value) if t]
    return out


def dynamic_refs(source: str, parts: dict, entries=None) -> set[tuple[str, str]]:
    """(target app, kind) pairs of the path-loading (a) and script-running (b) statements in `source`."""
    entries = entries or _entries(parts)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names: dict[str, dict[str, str]] = {}  # NAME = ROOT / "a" / "b": the folders a name stands for
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            found = _targets(_tokens(node.value), entries, parts)
            for ref in (n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)):
                for app, path in names.get(ref, {}).items():
                    found.setdefault(app, path)
            if found:
                names.setdefault(node.targets[0].id, {}).update(found)
    refs: set[tuple[str, str]] = set()
    compound = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If, ast.For, ast.While, ast.With,
                ast.Try, ast.Import, ast.ImportFrom, ast.Assign)
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt) or isinstance(node, compound):
            continue
        segment = ast.get_source_segment(source, node) or ""
        kind = "a" if any(w in segment for w in LOAD_WORDS) else "b" if any(w in segment for w in RUN_WORDS) else ""
        if not kind:
            continue
        tokens = _tokens(node)
        if kind == "b" and not any(SCRIPT.search(t) for t in tokens):
            continue  # a command line without a .py/.sh is a tool call (git, docker), not another app's script
        found = _targets(tokens, entries, parts)
        for ref in (n.id for n in ast.walk(node) if isinstance(n, ast.Name)):
            for app, path in names.get(ref, {}).items():
                found.setdefault(app, path)
        refs |= {(app, kind) for app in found}
    return refs


def current_rows() -> set[str]:
    parts = yaml.safe_load(PARTS.read_text(encoding="utf-8"))
    entries = _entries(parts)
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", check=True).stdout.splitlines()
    rows = set()
    for rel in files:
        source_app = app_of(rel, parts)
        path = ROOT / rel
        if source_app not in PRODUCT_APPS or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not any(w in text for w in LOAD_WORDS + RUN_WORDS):
            continue
        for app, kind in dynamic_refs(text, parts, entries):
            if app in PRODUCT_APPS and app != source_app:
                rows.add(f"{rel} -> {app} ({kind})")
    return rows


def known_rows() -> list[str]:
    return [line.strip() for line in KNOWN.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def test_known_rows_are_well_formed_and_sorted():
    rows = known_rows()
    assert all(ROW.match(row) for row in rows), [row for row in rows if not ROW.match(row)]
    assert rows == sorted(set(rows)), "known_app_dynamic_refs.txt rows must be unique and sorted"


def test_dynamic_cross_app_refs_equal_known_list():
    now, known = current_rows(), set(known_rows())
    new = sorted(now - known)
    stale = sorted(known - now)
    assert not new, (
        f"{len(new)} new dynamic cross-app reference(s) (sys.path/importlib/runpy load or subprocess of another "
        "app's script). Go through a contract or a CLI instead; the list is not for new rows:\n  " + "\n  ".join(new))
    assert not stale, ("rows no longer found: delete them from known_app_dynamic_refs.txt (the list only shrinks):\n  "
                       + "\n  ".join(stale))


def test_scanner_reads_each_pattern():
    parts = yaml.safe_load(PARTS.read_text(encoding="utf-8"))
    run = lambda src: dynamic_refs(src, parts)  # noqa: E731
    assert run('import sys\nsys.path.insert(0, str(ROOT / "deploy" / "robot" / "omx"))') == {("omx-cell", "a")}
    assert run('import sys\nP = ROOT / "deploy/robot/omx"\nsys.path.append(str(P))') == {("omx-cell", "a")}
    assert run('import subprocess\nsubprocess.run(["python", ROOT / "deploy/robot/omx/x.py"])') == {("omx-cell", "b")}
    assert run('import subprocess\nsubprocess.run(["git", "ls-tree", "deploy/robot/omx"])') == set()
    assert run('import sys\nsys.path.insert(0, "learning/envs/isaac/assets")') == {("omx-cell", "a")}
