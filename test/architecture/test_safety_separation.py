"""D-430 safety as a separate concern: §1 tagging and §3 separation invariants.

Safety-tagged files are the Python files under a ``concern: safety`` root plus the
``safety_modules`` list in ``tools/harness/platform_parts.yaml``. Each test says
whether it is structural (static AST over tracked files) or behavioural.

KNOWN_SAFETY_VIOLATIONS is checked by set equality like ``KNOWN_VIOLATIONS`` in
``test_platform_parts.py``: a new edge fails, a listed edge that no longer occurs
fails, so the list only shrinks. The Fleet stop-path carve (D-430 Validation wave 0
item 2) removes the mixed-file entries.

Honest holes, not oversights:
- Only static ``import`` / ``from`` statements are seen, as in test_platform_parts.
- A module counts only when it lies under a root's ``import_prefix``; script
  folders without one are invisible to the import rules.
- Invariant 3a sees ``create_publisher`` topic literals, module constants named
  in that argument, and ``declare_parameter`` defaults. A topic built at run time
  or remapped in launch is review-only (D-430 §3 invariant 3).
"""

import ast
import functools
from pathlib import PurePosixPath

from test_platform_parts import ROOT, _is_test_file, _owner, _package_of, _tracked
from test_platform_parts import _manifest as _read_manifest

SAFETY = "safety"

#: One parse per session; the tests below only read it.
_manifest = functools.lru_cache(maxsize=1)(_read_manifest)


@functools.lru_cache(maxsize=1)
def _index() -> dict[str, str]:
    """Dotted module name -> tracked path, for production files under an import_prefix."""
    roots = _manifest()["roots"]
    modules: dict[str, str] = {}
    for path in _tracked():
        if not path.endswith(".py") or _is_test_file(path):
            continue
        root = _owner(path, roots)
        if root is None or not root.get("import_prefix"):
            continue
        package = _package_of(path, root)
        stem = PurePosixPath(path).stem
        module = package if stem == "__init__" else ".".join(p for p in (package, stem) if p)
        if any(module == prefix or module.startswith(prefix + ".") for prefix in root["import_prefix"]):
            modules[module] = path
    return modules


def _module_of(name: str) -> str | None:
    """Longest indexed module that ``name`` starts with."""
    index = _index()
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in index:
            return candidate
    return None


@functools.lru_cache(maxsize=None)
def _concern_of(path: str) -> str | None:
    manifest = _manifest()
    if path in manifest["safety_modules"]:
        return SAFETY
    root = _owner(path, manifest["roots"])
    return None if root is None else root["concern"]


@functools.lru_cache(maxsize=None)
def _tree(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))


def _find(node: ast.AST, name: str) -> ast.AST | None:
    """First definition or assignment of ``name`` under ``node``, nested ones included."""
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child.name == name:
            return child
        targets = (child.targets if isinstance(child, ast.Assign)
                   else [child.target] if isinstance(child, ast.AnnAssign) else [])
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return child
    return None


def _resolve_symbol(symbol: str) -> tuple[str | None, ast.AST | None]:
    """(defining path, node) of a dotted ``module.Symbol[.nested]`` anchor."""
    module = _module_of(symbol)
    if module is None or module == symbol:
        return None, None
    path = _index()[module]
    node: ast.AST | None = _tree(path)
    for name in symbol[len(module) + 1:].split("."):
        node = _find(node, name) if node is not None else None
    return path, node


@functools.lru_cache(maxsize=1)
def _safety_files() -> list[str]:
    return sorted(path for path in _tracked()
                  if path.endswith(".py") and not _is_test_file(path) and _concern_of(path) == SAFETY)


def test_safety_anchors_live_in_safety_tagged_files():
    """Structural. D-430 §1 drift guard: every symbol anchor (module-qualified, nested
    definitions included) and string anchor resolves inside a safety-tagged file, and
    every safety module and Python safety root holds at least one anchor."""
    manifest = _manifest()
    tracked = set(_tracked())
    problems = [f"safety_modules entry is not a tracked .py file: {path}"
                for path in manifest["safety_modules"] if path not in tracked or not path.endswith(".py")]
    anchored = set()
    for anchor in manifest["safety_anchors"]:
        if "string" in anchor:
            path, node = _resolve_symbol(anchor["in"])
            found = node is not None and any(
                isinstance(child, ast.Constant) and child.value == anchor["string"] for child in ast.walk(node))
            label = f"string {anchor['string']!r} in {anchor['in']}"
        else:
            path, node = _resolve_symbol(anchor["symbol"])
            found = node is not None
            label = anchor["symbol"]
        if not found:
            problems.append(f"anchor does not resolve: {label}")
        elif _concern_of(path) != SAFETY:
            problems.append(f"anchor {label} lives in {path}, which is not safety-tagged")
        else:
            anchored.add(path)
    problems += [f"safety module has no anchor: {path}"
                 for path in manifest["safety_modules"] if path not in anchored]
    for root in manifest["roots"]:
        if root["concern"] != SAFETY:
            continue
        files = [path for path in _safety_files() if _owner(path, manifest["roots"]) is root]
        if files and not anchored & set(files):
            problems.append(f"safety root has Python files but no anchor: {root['path']}")
    assert problems == [], problems
    assert len(anchored) >= len(manifest["safety_modules"]) + 1
