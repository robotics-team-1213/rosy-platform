"""Static import extraction shared by the D-413 and D-427 boundary tests."""

import ast
import functools
from pathlib import Path

_BODY_STMTS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.With, ast.AsyncWith)
_BODY_ORELSE_STMTS = (ast.If, ast.For, ast.AsyncFor, ast.While)
_TRY_STMTS = (ast.Try, getattr(ast, "TryStar", ast.Try))
_MATCH_STMT = getattr(ast, "Match", ())


def _matches(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def iter_import_nodes(tree: ast.AST):
    """Yield ``ast.Import`` / ``ast.ImportFrom`` walking statement containers only."""
    stack = list(reversed(getattr(tree, "body", ())))
    while stack:
        node = stack.pop()
        kind = type(node)
        if kind is ast.Import or kind is ast.ImportFrom:
            yield node
        elif kind in _BODY_STMTS:
            stack.extend(reversed(node.body))
        elif kind in _BODY_ORELSE_STMTS:
            if node.orelse:
                stack.extend(reversed(node.orelse))
            stack.extend(reversed(node.body))
        elif kind in _TRY_STMTS:
            if node.finalbody:
                stack.extend(reversed(node.finalbody))
            if node.orelse:
                stack.extend(reversed(node.orelse))
            for handler in reversed(node.handlers):
                stack.extend(reversed(handler.body))
            stack.extend(reversed(node.body))
        elif _MATCH_STMT and kind is _MATCH_STMT:
            for case in reversed(node.cases):
                stack.extend(reversed(case.body))


@functools.lru_cache(maxsize=None)
def _cached_file_import_stmts(
    path_str: str, _mtime_ns: int, _size: int,
) -> tuple[tuple[int, str | None, tuple[str, ...]], ...]:
    text = Path(path_str).read_text(encoding="utf-8-sig")
    if "import" not in text:
        return ()
    tree = ast.parse(text, filename=path_str)
    return tuple(
        (0, None, tuple(alias.name for alias in node.names))
        if isinstance(node, ast.Import)
        else (node.level, node.module, tuple(alias.name for alias in node.names))
        for node in iter_import_nodes(tree)
    )


def file_import_stmts(path: Path) -> tuple[tuple[int, str | None, tuple[str, ...]], ...]:
    """Parsed ``(level, module, names)`` tuples for ``path`` with zero AST retention."""
    st = path.stat()
    return _cached_file_import_stmts(str(path), st.st_mtime_ns, st.st_size)


def resolve_import_stmts(stmts, package_name: str) -> list[str]:
    imported: list[str] = []
    package_parts = package_name.split(".") if package_name else []
    for level, module, names in stmts:
        if level == 0 and module is None:
            imported.extend(names)
            continue
        if level:
            ascend = level - 1
            base = package_parts[:max(0, len(package_parts) - ascend)]
            prefix = ".".join(base)
        else:
            prefix = ""
        if module:
            imported.append(".".join(part for part in (prefix, module) if part))
            for name in names:
                if name != "*":
                    imported.append(".".join(part for part in (prefix, module, name) if part))
        elif level:
            for name in names:
                if name != "*":
                    imported.append(".".join(part for part in (prefix, name) if part))
    return imported


def _imports(source: str, package_name: str) -> list[str]:
    if "import" not in source:
        ast.parse(source)
        return []
    tree = ast.parse(source)
    stmts = [
        (0, None, tuple(alias.name for alias in node.names))
        if isinstance(node, ast.Import)
        else (node.level, node.module, tuple(alias.name for alias in node.names))
        for node in iter_import_nodes(tree)
    ]
    return resolve_import_stmts(stmts, package_name)
