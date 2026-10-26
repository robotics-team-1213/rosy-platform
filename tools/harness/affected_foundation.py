"""Rule 4 (design 0.7): a ``contracts/foundation`` change that only adds code narrows, proven by AST.

A new ``core_common`` module, or statements appended at the end of ``protocol/schemas.py``, cannot
change what existing importers see when the added top level only defines new names: no existing
statement changes, no name is bound twice, no ``__all__`` edit, no stdlib or builtin name is shadowed,
no call runs at import beyond the declarative ones listed, and imports stay inside what the package
already imports. Then the foundation suite, the test files importing the module, the tests reading the
API reference and the protocol version alignment test run instead of FULL. Anything else returns why.
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import PurePosixPath

import affected_tests as at  # attributes read at call time, so the cyclic import is safe

CORE_COMMON = "contracts/foundation/core_common"
SCHEMAS = f"{CORE_COMMON}/protocol/schemas.py"
API_REFERENCE = "docs/reference/ROSY API & Protocol Reference.md"
VERSION_ALIGNMENT = "middleware/core/gateway/test/test_protocol_version_alignment.py"
#: Calls a class or module body may make at import: declarations (pydantic, dataclasses, typing).
ALLOWED_CALLS = frozenset({
    "Field", "ConfigDict", "field_validator", "model_validator", "model_serializer", "AfterValidator",
    "BeforeValidator", "dataclass", "field", "frozenset", "tuple", "re.compile", "TypeVar", "NewType",
    "property", "staticmethod", "classmethod", "enum.auto", "auto", "timedelta"})
STATEMENTS = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.ClassDef, ast.FunctionDef,
              ast.AsyncFunctionDef)
# Private C modules (_datetime) are left out: `import datetime as _datetime` is the usual alias, not a shadow.
SHADOWED = frozenset(dir(builtins)) | {name for name in sys.stdlib_module_names if not name.startswith("_")}


def readers(repo: at.Repo, path: str, base: str | None) -> tuple[dict[str, str] | None, str]:
    """The tests for an additions-only `path` (``base``: its text at the merge base, None if new), or
    (None, why FULL); (None, "") when the rule does not apply to `path`."""
    p = PurePosixPath(path)
    if not at._under(path, CORE_COMMON) or p.suffix != ".py" or not repo.exists(path):
        return None, ""
    if base is not None and p.name == "__init__.py":
        return None, "an existing __init__.py changed"
    if base is not None and path != SCHEMAS:
        return None, ""
    if base is None and p.stem in sys.stdlib_module_names:
        return None, f"new module {p.name} shadows the stdlib module"
    why = _additions_problem(repo, path, base or "", repo.text(path))
    if why:
        return None, why
    found = {f"{CORE_COMMON.rpartition('/')[0]}/test": f"module core_common ({path})",
             VERSION_ALIGNMENT: "protocol version alignment (rule 4 always)"}
    found.update({t: f"reads the API reference (rule 4 always, {path})" for t in repo.referencing_tests(API_REFERENCE)})
    for test in [*repo.referencing_tests(path), *(s for s in at.affected_narrow.module_importers(repo, path)
                                                  if at.TEST_FILE.search(s))]:
        found.setdefault(test, f"imports or names {path}")
    return {t: why for t, why in found.items() if repo.exists(t)}, ""


def _additions_problem(repo: at.Repo, path: str, base: str, head: str) -> str:
    try:
        old, new = ast.parse(base).body, ast.parse(head).body
    except SyntaxError as exc:
        return f"does not parse: {exc.msg}"
    if [ast.dump(s) for s in new[:len(old)]] != [ast.dump(s) for s in old]:
        return "an existing statement changed (only additions at the end narrow)"
    bound, imported = _bound(old), _package_imports(repo, path)
    for stmt in new[len(old):]:
        line = f"line {stmt.lineno}"
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            continue  # a docstring
        if not isinstance(stmt, STATEMENTS):
            return f"{line}: top-level {type(stmt).__name__} statement"
        names = _bound([stmt])
        if "__all__" in names:
            return f"{line}: __all__ changes"
        if names & bound:
            return f"{line}: redefines existing name(s) {', '.join(sorted(names & bound))}"
        if any(not isinstance(t, ast.Name) for t in _writes(stmt)):  # `X.a = 1`, `X[k] = v`, also in class bodies
            return f"{line}: assigns into an existing object"
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in stmt.names] if isinstance(stmt, ast.Import) else [stmt.module or ""]
            if isinstance(stmt, ast.ImportFrom) and any(a.name == "*" for a in stmt.names):
                return f"{line}: star import"
            outside = [m for m in modules if not (getattr(stmt, "level", 0) or m.split(".")[0] in imported
                                                  or m.split(".")[0] in sys.stdlib_module_names)]
            if outside:
                return f"{line}: imports {', '.join(outside)}, which core_common does not import yet"
            # `import json` and `from datetime import datetime` bind the stdlib's own object, no shadow
            stdlib = isinstance(stmt, ast.ImportFrom) and not stmt.level and modules[0].split(".")[0] in sys.stdlib_module_names
            shadow = set() if stdlib else {a.asname for a in stmt.names if a.asname in SHADOWED} if isinstance(
                stmt, ast.Import) else names & SHADOWED
        else:
            shadow = names & SHADOWED
        if shadow:
            return f"{line}: shadows the stdlib or builtin name(s) {', '.join(sorted(shadow))}"
        call = next((c for c in _calls(stmt) if c not in ALLOWED_CALLS), None)
        if call:
            return f"{line}: top-level call {call}() runs at import"
        bound |= names
    return ""


def _targets(stmt: ast.stmt) -> list[ast.expr]:
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
    return [e for t in targets for e in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t])]


def _writes(node: ast.AST):
    """Assignment targets evaluated at import (function bodies excluded), tuples unpacked."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        yield from _targets(node)
    elif isinstance(node, (ast.AugAssign, ast.Delete)):
        yield from (node.targets if isinstance(node, ast.Delete) else [node.target])
    for child in ast.iter_child_nodes(node):
        yield from _writes(child)


def _bound(stmts: list[ast.stmt]) -> set[str]:
    """Top-level names the statements bind (imports, assignments, classes and functions)."""
    names: set[str] = set()
    for stmt in stmts:
        if isinstance(stmt, ast.Import):
            names |= {a.asname or a.name.split(".")[0] for a in stmt.names}
        elif isinstance(stmt, ast.ImportFrom):
            names |= {a.asname or a.name for a in stmt.names}
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            names |= {t.id for t in _targets(stmt) if isinstance(t, ast.Name)}
        elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
        elif isinstance(stmt, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(stmt.name)
    return names


def _calls(node: ast.AST):
    """Calls evaluated at import: everything but function bodies (decorators and defaults included)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = node.args
        for sub in [*getattr(node, "decorator_list", []), *args.defaults, *(d for d in args.kw_defaults if d)]:
            yield from _calls(sub)
        return
    if isinstance(node, ast.Call):
        yield ast.unparse(node.func)
    for child in ast.iter_child_nodes(node):
        yield from _calls(child)


def _package_imports(repo: at.Repo, path: str) -> set[str]:
    """Top-level modules core_common already imports (its dependencies), not counting `path`."""
    return {name.split(".")[0] for src in repo.tracked if src != path and src.endswith(".py")
            and at._under(src, CORE_COMMON) for name in repo.imports(src)}
