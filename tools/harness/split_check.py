"""D-766 3: is a Python split a pure move? ``AST identical, only imports/paths changed`` or what differs.

Usage: python tools/harness/split_check.py BASE HEAD

Takes every file that changed between BASE and HEAD. Any changed file that is not ``.py``
is listed and the result is not pure (a web or data change is reviewed as an ordinary change).
For the ``.py`` files it compares BASE with HEAD:

- **Definitions** (every top-level statement except imports, the module docstring, ``__all__``
  and string-constant assignments) by ``ast.dump`` without line numbers: the same multiset,
  and two statements that come from one BASE file keep their order in their HEAD file.
- **String constants** by name: the same value, unless both values look like paths
  (``a/b``, ``x.py``, ``pkg.module``). A new or removed non-path constant differs.
- **Imports** as bound name -> ``module:attr``. A HEAD binding is fine when BASE had it, or
  when its module is one of the changed files (the moved set) and it imports a definition
  BASE had in those files or the same attr BASE bound that name to. Dropped imports are not
  reported.

Exit 0 only when nothing differs. Standard library only.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import Counter, defaultdict

_PATHLIKE = re.compile(r"[/\\]|^[\w.-]+\.\w{1,5}$|^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")


def _git(*args: str) -> str | None:
    done = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    return done.stdout if done.returncode == 0 else None


def _targets(node) -> list:
    return node.targets if isinstance(node, ast.Assign) else [node.target]


def _string_const(node) -> str | None:
    """The name of a ``NAME = "text"`` assignment, else None."""
    if (isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str) and len(_targets(node)) == 1 and isinstance(_targets(node)[0], ast.Name)):
        return _targets(node)[0].id
    return None


def _name(node: ast.stmt) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return ", ".join(ast.unparse(t) for t in _targets(node))
    return f"<{type(node).__name__} at line {node.lineno}>"


def parse(source: str | None) -> tuple[list[tuple[str, str]], dict[str, str], dict[str, str]]:
    """(definitions as (dump, name) in order, string constants name -> value, imports name -> module:attr)."""
    defs, strings, imports = [], {}, {}
    for index, node in enumerate(ast.parse(source).body if source is not None else ()):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name.split(".")[0]] = f"{alias.name if alias.asname else alias.name.split('.')[0]}:"
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                imports[alias.asname or alias.name] = f"{module}:{alias.name}"
        elif index == 0 and isinstance(node, ast.Expr) and isinstance(getattr(node.value, "value", None), str):
            continue  # module docstring
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in _targets(node)):
            continue
        elif _string_const(node):
            strings[_string_const(node)] = node.value.value
        else:
            defs.append((ast.dump(node), _name(node)))
    return defs, strings, imports


def _in_moved(module: str, moved: set[str]) -> bool:
    module = module.lstrip(".")
    return any(module == dotted or dotted.endswith("." + module) for dotted in moved)


def compare(base: str, head: str) -> tuple[list[str], list[str], list[str]]:
    """(changed .py paths, changed other paths, what differs)."""
    changed = [p for p in (_git("diff", "-z", "--name-only", "--no-renames", base, head) or "").split("\0") if p]
    paths = [p for p in changed if p.endswith(".py")]
    others = [p for p in changed if not p.endswith(".py")]
    moved = {p[:-3].replace("/", ".").removesuffix(".__init__") for p in paths}
    before, after = {}, {}
    for path in paths:
        before[path] = parse(_git("show", f"{base}:{path}"))
        after[path] = parse(_git("show", f"{head}:{path}"))
    differ = set()
    base_defs = Counter(d for defs, _, _ in before.values() for d in defs)
    head_defs = Counter(d for defs, _, _ in after.values() for d in defs)
    differ |= {name for _, name in (base_defs - head_defs) + (head_defs - base_defs)}
    # Order: statements from one BASE file keep their relative order in their HEAD file.
    origin = defaultdict(list)
    for path, (defs, _, _) in before.items():
        for index, item in enumerate(defs):
            origin[item].append((path, index))
    for path, (defs, _, _) in after.items():
        last = {}
        for item in defs:
            if not origin[item]:
                continue
            source, index = origin[item].pop(0)
            if index < last.get(source, -1):
                differ.add(f"{item[1]} (order changed)")
            last[source] = max(index, last.get(source, -1))
    base_strings = {name: value for _, strings, _ in before.values() for name, value in strings.items()}
    head_strings = {name: value for _, strings, _ in after.values() for name, value in strings.items()}
    for name in set(base_strings) | set(head_strings):
        old, new = base_strings.get(name), head_strings.get(name)
        if old != new and not (old is not None and new is not None and _PATHLIKE.search(old) and _PATHLIKE.search(new)):
            differ.add(f"{name} = {old!r} -> {new!r}")
    base_imports = defaultdict(set)
    for _, _, imports in before.values():
        for name, target in imports.items():
            base_imports[name].add(target)
    defined = {part for defs, strings, _ in before.values() for _, names in defs for part in names.split(", ")}
    defined |= set(base_strings)
    for _, _, imports in after.values():
        for name, target in imports.items():
            module, _, attr = target.partition(":")
            if target in base_imports[name]:
                continue
            if _in_moved(module, moved) and (attr in defined or any(old.partition(":")[2] == attr
                                                                    for old in base_imports[name])):
                continue  # a moved definition, or the same symbol through its new module
            differ.add(f"import {name} -> {target}")
    return paths, others, sorted(differ)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    paths, others, differ = compare(*argv)
    if others:
        print(f"[split-check] not a pure Python move; non-.py files changed: {', '.join(others)}", file=sys.stderr)
    if differ:
        print(f"[split-check] {len(paths)} Python file(s): not a pure move; these differ: " + "; ".join(differ),
              file=sys.stderr)
    if others or differ:
        return 1
    print(f"[split-check] {len(paths)} Python file(s): AST identical, only imports/paths changed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
