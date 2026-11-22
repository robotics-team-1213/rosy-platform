"""D-940: identical top-level definitions across parts must be registered.

Tracked product files in two different parts that define the same top-level
function or class with an identical body (AST dump, line numbers excluded,
at least ``MIN_DUMP`` characters) form one group per definition; every group
must appear in ``known_duplicates.txt`` with a reason, and a row whose group
has since disappeared fails too (P5 set equality). Run
``python test/architecture/test_duplicate_definitions.py`` to print the
current groups when building or pruning the registry.

Honest holes, not oversight:
- One-line helpers (``_sha``, ``wrap``, ``_iso`` ...) stay under the size
  floor on purpose: D-841 keeps trivial stdlib one-liners in their owners
  instead of a global utils package. Substantial forks are what this gate
  catches at birth.
- A fork that already differs by one token never registers, so forked mirrors
  (site_users-style deploy mirrors) keep their own equality or contract tests
  (D-841 decision 8, e.g. test_peer_proof_ownership.py). Inside a registered
  group a one-sided edit turns the row stale, so structural drift is caught;
  only synchronized edits to every copy stay silent.
- Same-name definitions with different bodies (vocabulary collisions such as
  the wrap conventions) are out of scope; the folder vocabulary table owns
  those names.
- Only top-level defs are compared; methods and nested functions are not.
- Files under a ``test/`` directory are skipped: package-local test mirrors
  are legitimate and the audit's ament boilerplate is same-part anyway.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
KNOWN = Path(__file__).resolve().parent / "known_duplicates.txt"

#: Parts whose files are scanned. ``test`` and ``docs`` mirror names by design;
#: ``profiles`` carries no Python.
PARTS = {"middleware", "operations", "learning", "contracts", "integrations",
         "shared_web", "deploy", "tools"}

#: AST dumps shorter than this are one-liners the repo deliberately leaves
#: with their owners (D-841 alternatives: no global utils package).
MIN_DUMP = 160


def _roots():
    manifest = yaml.safe_load(
        (ROOT / "tools" / "harness" / "platform_parts.yaml").read_text(encoding="utf-8"))
    out = []
    for entry in manifest["roots"]:
        if entry["part"] in PARTS:
            out.append((tuple(entry["path"].split("/")), entry["part"]))
    return sorted(out, key=lambda item: len(item[0]))


def _part_of(rel: str, roots) -> str | None:
    parts = tuple(rel.split("/"))
    best = None
    for prefix, part in roots:
        size = len(prefix)
        if len(parts) > size and tuple(parts[:size]) == prefix:
            best = part  # roots are sorted by depth, the deepest match wins
    return best


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return sorted(line for line in out.splitlines() if line)


_TOP_DEF_RE = re.compile(r"^(?:async[ \t]+)?(?:def|class)[ \t]+([^\W\d]\w*)\b", re.M)
_TOP_DEF_FALLBACK = re.compile(
    r"(?:^(?:async\b[^\n]*|def|class)\b[^\n]*\\$|^(?:async[ \t]+)?(?:def|class)[ \t]+\w*[^\x00-\x7f]|;[ \t]*(?:async[ \t]+)?(?:def|class)\b|\x0c)",
    re.M,
)


def _definitions(text: str) -> list[tuple[str, str]]:
    tree = ast.parse(text)
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # ast.dump without include_attributes carries no line numbers,
            # so a pure move or reindent keeps the same key.
            dump = ast.dump(node)
            if len(dump) >= MIN_DUMP:
                out.append((node.name, dump))
    return out


def _part_lookup(roots):
    by_top: dict[str, list[tuple[int, tuple[str, ...], str]]] = {}
    for prefix, part in roots:
        by_top.setdefault(prefix[0], []).append((len(prefix), prefix, part))
    for bucket in by_top.values():
        bucket.sort(key=lambda item: item[0], reverse=True)

    def part_of(rel: str) -> str | None:
        parts = tuple(rel.split("/"))
        for size, prefix, part in by_top.get(parts[0], ()):
            if len(parts) > size and parts[:size] == prefix:
                return part
        return None

    return part_of


def scan(root: Path = ROOT) -> dict[tuple[str, str], tuple[str, ...]]:
    """Current identical cross-part definition groups: (name, n) -> paths.

    The second tuple field is the AST dump length bucketed to its length so a
    pure reformat of one copy (same statements, new dump) surfaces as a new
    group instead of silently vanishing.
    """
    part_of = _part_lookup(_roots())
    name_parts: dict[str, set[str]] = {}
    candidates: list[tuple[str, str, list[str]]] = []
    parsed_fallback: list[tuple[str, str, ast.Module]] = []
    for rel in _tracked_files():
        if "/test/" in f"/{rel}":
            continue
        part = part_of(rel)
        if part is None:
            continue
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        if _TOP_DEF_FALLBACK.search(text):
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name_parts.setdefault(node.name, set()).add(part)
            parsed_fallback.append((rel, part, tree))
            continue
        found_names = _TOP_DEF_RE.findall(text)
        if not found_names:
            continue
        for def_name in found_names:
            name_parts.setdefault(def_name, set()).add(part)
        candidates.append((rel, part, found_names))

    dup_names = {def_name for def_name, parts in name_parts.items() if len(parts) >= 2}
    buckets: dict[tuple, list[tuple[str, str, ast.AST]]] = {}
    bucket_parts: dict[tuple, set[str]] = {}

    def _collect(rel: str, part: str, tree: ast.Module) -> None:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in dup_names:
                sig = (type(node), node.name, len(node.decorator_list), tuple(type(s) for s in node.body))
                buckets.setdefault(sig, []).append((rel, part, node))
                bucket_parts.setdefault(sig, set()).add(part)

    for rel, part, tree in parsed_fallback:
        _collect(rel, part, tree)
    for rel, part, found_names in candidates:
        if not any(def_name in dup_names for def_name in found_names):
            continue
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        _collect(rel, part, tree)

    owners: dict[tuple[str, str], set[str]] = {}  # (name, dump) -> parts
    where: dict[tuple[str, str, str], set[str]] = {}  # (name, dump, part) -> paths
    for sig, entries in buckets.items():
        if len(bucket_parts[sig]) < 2:
            continue
        for rel, part, node in entries:
            dump = ast.dump(node)
            if len(dump) < MIN_DUMP:
                continue
            owners.setdefault((node.name, dump), set()).add(part)
            where.setdefault((node.name, dump, part), set()).add(rel)

    groups = {}
    for (name, dump), parts in owners.items():
        if len(parts) < 2:
            continue
        paths = tuple(sorted(
            rel for part in parts for rel in where[(name, dump, part)]))
        groups[(name, str(len(dump)))] = paths
    return groups


def _by_name(groups: dict[tuple[str, str], tuple[str, ...]]) -> dict[str, set[tuple[str, ...]]]:
    result: dict[str, set[tuple[str, ...]]] = {}
    for (name, _n), paths in groups.items():
        result.setdefault(name, set()).add(paths)
    return result


def _known_groups() -> dict[str, set[tuple[str, ...]]]:
    result: dict[str, set[tuple[str, ...]]] = {}
    for line in KNOWN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        head, _sep, _reason = line.partition("  ")
        fields = head.strip().split("|")
        if len(fields) != 2:
            raise AssertionError(
                f"known_duplicates.txt: expected '<path> <path>|name  reason' "
                f"(space-separated paths: a '+' joins them into one token the "
                f"secret scan reports): {line!r}")
        group = tuple(sorted(p for p in fields[0].split() if p))
        if len(group) < 2:
            raise AssertionError(f"known_duplicates.txt: group needs 2+ paths: {line!r}")
        result.setdefault(fields[1].strip(), set()).add(group)
    return result


def test_identical_definitions_are_registered():
    known = _known_groups()
    found = _by_name(scan())

    missing = []
    for name, groups in found.items():
        for paths in groups - known.get(name, set()):
            missing.append(f"{'+'.join(paths)}|{name}")
    stale = []
    for name, groups in known.items():
        for paths in groups - found.get(name, set()):
            stale.append(f"{'+'.join(paths)}|{name}")
    assert not missing, (
        "identical definition in two parts without a known_duplicates.txt row "
        "(add '<path> <path>|name  <갈래 ①-④>  <reason>' and, for an intentional "
        "duplicate, its guard test):\n" + "\n".join(sorted(missing))
    )
    assert not stale, (
        "known_duplicates.txt row whose group no longer exists — a one-sided "
        "edit of a registered copy shows up here first (delete or re-register "
        "the row in the change that touched the copy):\n"
        + "\n".join(sorted(stale))
    )


if __name__ == "__main__":
    for (name, _n), paths in sorted(scan().items()):
        print(f"{' '.join(paths)}|{name}  <갈래> <reason>")
    sys.exit(0)
