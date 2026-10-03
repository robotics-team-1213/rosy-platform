#!/usr/bin/env python3
r"""D-427 step B bulk mover: move every pending root of one wave and rewrite its consumers.

Usage: ``python tools/harness/d427_move.py <wave> [--dry-run]``, ``--report`` (residue only).
Source of truth: ``tools/harness/platform_parts.yaml``; a root is pending when
``path != d427_target`` and it is not riding inside an already moved parent.

What one run does (docs/plans/2026-10-03-d427-source-migration.md, common procedure):

1. ``git mv`` each pending root of the wave, parents first. A nested root rides with
   its parent; a ``deferred`` root stays inside the parent (its ``path`` becomes the
   location under the parent target), any other nested root whose target is not that
   location is moved again afterwards.
2. Manifest: ``path`` and ``legacy`` per root, ``safety_modules`` paths, and
   ``colcon_roots`` (every top-level folder that holds a ``package.xml``, no nesting).
   Every ``pyproject.toml``-only folder under a colcon root gets ``COLCON_IGNORE``.
3. References to an old path, in the legacy-scan scope (``test/architecture/_legacy_paths``)
   plus the moved roots' own Markdown (never ``logs.md``/``progress.md``, history dirs or
   FROZEN_BYTES):
   in this order:
   (c) ``../`` strings, resolved from the old file folder (then its ancestors) against the
       pre-move tree, re-relativised from the new folder;
   (d) ``parents[N]`` / ``.parent`` chains of ``Path(__file__)`` in moved ``.py`` files
       whose old ancestor is above the moved root: the repo root, an ancestor the new
       location keeps, or ``(<repo root> / "src" / ...)`` for one it lost;
   (a) slash paths (also after ``/``, ``$VAR/``, ``/repo/`` and in backslash form); a path
       token starting with ``/opt/``, ``/usr/`` or ``/etc/`` is an install path and kept;
   (b) joined literal segments (``"middleware" / "core" / "gateway"``, ``os.path.join``,
       ``Path(a, b)``, PowerShell ``Join-Path``), keeping closing parentheses;
   (e) ``SRC / "site" / "fleet"`` where ``SRC`` denotes src/ (``--srcvars`` re-applies it).
   A rewritten ``.py`` that no longer compiles is left alone and reported.
4. Residue: the legacy scanner findings over the whole tree after the rewrite.

Package names, ROS names, topics and APIs never change (D-231).
"""

from __future__ import annotations

import argparse
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tools" / "harness" / "platform_parts.yaml"
MANIFEST_REL = "tools/harness/platform_parts.yaml"
sys.path.insert(0, str(ROOT / "test" / "architecture"))
from _legacy_paths import (  # noqa: E402
    _END, _RELATIVE, _SEPARATOR, _START, _TOKEN_BREAK, FROZEN_BYTES, HISTORY_DIRS,
    HISTORY_NAMES, INSTALL_PREFIXES, LegacyScan, in_scope, under,
)

#: Preferred order of top-level colcon roots.
ROOT_ORDER = ["src", "learning", "operations", "middleware", "contracts", "integrations", "shared"]
MAX_BYTES = 5_000_000


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def tracked() -> list[str]:
    return [p for p in git("ls-files", "-z").split("\0") if p]


def load_roots() -> list[dict]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["roots"]


def plan(wave: str, roots: list[dict]) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """``moves``: ordered ``git mv`` pairs. ``new_path``: old root path -> new root path."""
    pending = [r for r in roots if r.get("wave") == wave and r["path"] != r["d427_target"]
               and not r.get("legacy")]
    pending.sort(key=lambda r: len(PurePosixPath(r["path"]).parts))
    moves: list[tuple[str, str]] = []
    new_path: dict[str, str] = {}
    for root in pending:
        old = root["path"]
        riding = old
        for src, dst in sorted(moves, key=lambda m: -len(m[0])):
            if under(old, src):
                riding = dst + old[len(src):]
                break
        if riding == old and root.get("deferred"):
            raise SystemExit(f"{old}: deferred root without a moving parent")
        if root.get("deferred") or riding == root["d427_target"]:
            new_path[old] = riding
        else:
            moves.append((riding, root["d427_target"]))
            new_path[old] = root["d427_target"]
    return moves, new_path


def mapper(new_path: dict[str, str]):
    pairs = sorted(new_path.items(), key=lambda kv: -len(kv[0]))

    def mapf(path: str) -> str:
        for old, new in pairs:
            if under(path, old):
                return new + path[len(old):]
        return path
    return mapf


def _install_token(text: str, start: int) -> bool:
    while start > 0 and not _TOKEN_BREAK.match(text, start - 1):
        start -= 1
    return text.startswith(INSTALL_PREFIXES, start)


def slash_pattern(olds: list[str]) -> re.Pattern:
    alts = ["(?:/|\\\\+)".join(map(re.escape, old.split("/"))) for old in olds]
    return re.compile(f"{_START}(?:{'|'.join(alts)}){_END}")


def _copy_destination(text: str, at: int) -> bool:
    """Inside the last argument of a Dockerfile COPY/ADD line (a path in the image)."""
    start = text.rfind("\n", 0, at) + 1
    end = text.find("\n", at)
    line = text[start:end if end != -1 else len(text)]
    return bool(re.match(r"\s*(COPY|ADD)\s", line)) and at - start >= len(line.rstrip()) - len(line.split()[-1])


def rewrite_slash(text: str, pattern: re.Pattern, mapping: dict[str, str],
                  dockerfile: bool = False) -> tuple[str, int]:
    count = 0

    def repl(match: re.Match) -> str:
        nonlocal count
        raw = match.group(0)
        if _install_token(text, match.start()) or (dockerfile and _copy_destination(text, match.start())):
            return raw
        sep = re.search(r"\\+", raw)
        sep = sep.group(0) if sep else "/"
        old = re.sub(r"\\+", "/", raw)
        count += 1
        return sep.join(mapping[old].split("/"))
    return pattern.sub(repl, text), count


def _fit_seps(seps: list[str], need: int) -> list[str] | None:
    """``need`` separators from the matched ones, keeping every one that closes a
    parenthesis (``") / "``) so the expression stays balanced. None: cannot fit."""
    seps = list(seps)
    while len(seps) > need:
        plain = [i for i, sep in enumerate(seps) if ")" not in sep]
        if not plain:
            return None
        del seps[plain[-1]]
    while len(seps) < need:
        plain = next((sep for sep in seps if ")" not in sep), None)
        if plain is None:
            return None
        seps.insert(0, plain)
    return seps


def join_patterns(mapping: dict[str, str]):
    out = []
    for old in sorted(mapping, key=len, reverse=True):
        segs = old.split("/")
        if len(segs) < 2:
            continue
        body = f"({_SEPARATOR})".join(map(re.escape, segs))
        out.append((old, segs, re.compile(_START + body + _END)))
    return out


def rewrite_join(text: str, patterns, mapping: dict[str, str]) -> tuple[str, int]:
    count = 0
    for old, segs, pattern in patterns:
        if not all(seg in text for seg in segs):
            continue

        def repl(match: re.Match) -> str:
            nonlocal count
            raw = match.group(0)
            if "'" not in raw and '"' not in raw:
                return raw
            seps = list(match.groups())
            new = mapping[old].split("/")
            need = len(new) - 1
            new_seps = _fit_seps(seps, need)
            if new_seps is None:
                return raw
            count += 1
            return new[0] + "".join(sep + seg for sep, seg in zip(new_seps, new[1:]))
        text = pattern.sub(repl, text)
    return text, count


_SRC_VAR = re.compile(
    r"""^[ \t]*([A-Z_][A-Z0-9_]*)[ \t]*(?::[^=\n]+)?=[ \t]*.*["']src["'][ \t]*\)?[ \t]*(?:#[^\r\n]*)?\r?$""", re.M)


_FILE_EXPR = re.compile(
    r"(?:pathlib\.)?Path\(__file__\)(?:\.resolve\(\)|\.absolute\(\))*((?:\.parent\b(?!s))*)(?:\.parents\[(\d+)\])?")


def _src_names(text: str, path: str) -> set[str]:
    """Names and ``Path(__file__)`` expressions in ``text`` that denote the repo's src/."""
    names = {m.group(1) for m in _SRC_VAR.finditer(text)}
    names |= {n for n in ("SRC", "SRC_ROOT", "SRC_DIR") if re.search(rf"^[ \t]*{n}[ \t]*=", text, re.M)}
    parts = PurePosixPath(path).parts
    if parts and parts[0] == "src":
        for m in _FILE_EXPR.finditer(text):
            level = _level(m.group(1), m.group(2))
            if level and len(parts) - level == 1:
                names.add(m.group(0))
        names |= {name for name, level in _var_levels(text).items() if level > 0 and len(parts) - level == 1}
    return names


def _parent_of(name: str) -> str:
    m = re.search(r"\.parents\[(\d+)\]$", name)
    if m:
        return f"{name[:m.start()]}.parents[{int(m.group(1)) + 1}]"
    return f"{name}.parent"


def rewrite_srcvar(text: str, mapping: dict[str, str], path: str = "") -> tuple[str, int]:
    """(e) ``SRC / "site" / "fleet"`` where ``SRC`` names the repo's ``src/`` folder (a
    constant assigned ``... "src"``, named SRC/SRC_ROOT/SRC_DIR, or a ``Path(__file__)``
    chain or variable that reaches src/) becomes ``SRC.parent / "operations" / "fleet"``.
    The legacy scanner cannot see this form."""
    names = _src_names(text, path)
    if not names:
        return text, 0
    count = 0
    for old in sorted(mapping, key=len, reverse=True):
        if not old.startswith("src/"):
            continue
        segs = old.split("/")[1:]
        if not all(seg in text for seg in segs):
            continue
        body = "(" + "|".join(map(re.escape, sorted(names, key=len, reverse=True))) + r")(\s*/\s*)([\"'])"
        body += f"({_SEPARATOR})".join(map(re.escape, segs))
        pattern = re.compile(r"(?<![\w.])" + body + _END)

        def repl(match: re.Match) -> str:
            nonlocal count
            name, op, quote = match.group(1), match.group(2), match.group(3)
            seps = [g for g in match.groups()[3:]]
            new = mapping[old].split("/")
            need = len(new) - 1
            if not seps:
                seps = [f"{quote}{op}{quote}"]
            new_seps = _fit_seps(seps, need)
            if new_seps is None:
                return match.group(0)
            count += 1
            return f"{_parent_of(name)}{op}{quote}" + new[0] + "".join(s + g for s, g in zip(new_seps, new[1:]))
        text = pattern.sub(repl, text)
    return text, count


def rewrite_relative(text: str, old_file: str, new_file: str, mapf, old_paths: set[str],
                     residue: list[str]) -> tuple[str, int]:
    if "../" not in text:
        return text, 0
    old_folders = PurePosixPath(old_file).parent.parts
    new_folder = str(PurePosixPath(new_file).parent)
    edits = []
    for match in _RELATIVE.finditer(text):
        raw = match.group(0)
        rel = re.sub(r"(?<=\w)\.$", "", raw)
        trail = "/" if rel.endswith("/") else ""
        for depth in range(len(old_folders), -1, -1):
            base = "/".join(old_folders[:depth]) or "."
            resolved = posixpath.normpath(posixpath.join(base, rel))
            if resolved.startswith(".."):
                continue
            if resolved not in old_paths:
                continue
            if base == ".":
                new_base = "."
            elif depth == len(old_folders):
                new_base = new_folder
            else:
                new_base = mapf(base)
                if new_base == base and mapf(old_file) != old_file:
                    residue.append(f"{new_file}: relative {raw!r} resolves from {base}, above the moved root")
                    break
            new_resolved = mapf(resolved)
            if new_base == base and new_resolved == resolved:
                break
            new_rel = posixpath.relpath(new_resolved, new_base) + trail
            if new_rel.rstrip("/") != rel.rstrip("/"):
                edits.append((match.start(), match.start() + len(rel), new_rel))
            break
    for start, end, new in reversed(edits):
        text = text[:start] + new + text[end:]
    return text, len(edits)


_DEF_LINE = re.compile(
    r"""^[ \t]*(\w+)[ \t]*(?::[^=\n]+)?=[ \t]*((?:pathlib\.)?Path\(__file__\)(?:\.resolve\(\)|\.absolute\(\))*|\w+)"""
    r"""((?:\.parent\b(?!s))*)(?:\.parents\[(\d+)\])?((?:[ \t]*/[ \t]*["'][^"'\n]+["'])*)"""
    r"""[ \t]*(?:#[^\r\n]*)?\r?$""", re.M)


def _var_levels(text: str) -> dict[str, int]:
    """Variable -> steps above the file, for ``Path(__file__)``-rooted definitions,
    following other such variables and subtracting appended ``/ "a/b"`` segments."""
    levels: dict[str, int] = {}
    for m in _DEF_LINE.finditer(text):
        base = m.group(2)
        if base.endswith(")"):
            base_level = 0
        elif base in levels:
            base_level = levels[base]
        else:
            continue
        segs = sum(len([p for p in s.split("/") if p]) for s in re.findall(r"""["']([^"']+)["']""", m.group(5)))
        levels[m.group(1)] = base_level + _level(m.group(3), m.group(4)) - segs
    return levels


def _level(chain_parents: str, index: str | None) -> int:
    level = chain_parents.count(".parent")
    if index is not None:
        level += int(index) + 1
    return level


def rewrite_parents(text: str, old_file: str, new_file: str, moved_old: str, moved_new: str,
                    residue: list[str]) -> tuple[str, int]:
    """Adjust ``parents[N]`` / ``.parent`` chains whose old ancestor lies above the moved root."""
    if "__file__" not in text:
        return text, 0
    old_parts = PurePosixPath(old_file).parts
    new_parts = PurePosixPath(new_file).parts
    root_depth = len(PurePosixPath(moved_old).parts)
    levels = _var_levels(text)
    names = "|".join(map(re.escape, levels))
    base_expr = r"(?:pathlib\.)?Path\(__file__\)(?:\.resolve\(\)|\.absolute\(\))*"
    if names:
        base_expr = f"(?:{base_expr}|(?<![\\w.])(?:{names})\\b)"
    expr = re.compile(f"({base_expr})((?:\\.parent\\b(?!s))*)(?:\\.parents\\[(\\d+)\\])?")
    edits = []
    for m in expr.finditer(text):
        base, chain, index = m.group(1), m.group(2), m.group(3)
        if not chain and index is None:
            continue
        base_level = 0 if base.startswith(("Path", "pathlib")) else levels[base]
        if base_level and len(old_parts) - base_level < root_depth:
            continue  # the variable itself is rewritten to keep naming the same folder
        level = base_level + _level(chain, index)
        keep = len(old_parts) - level  # number of leading parts of the old ancestor
        if keep < 0:
            continue
        if keep >= root_depth and old_parts[:root_depth] == PurePosixPath(moved_old).parts:
            continue  # inside the moved root: same relative depth
        ancestor = old_parts[:keep]
        suffix = ""
        if keep == 0:
            new_keep = 0
        elif tuple(new_parts[:keep]) == tuple(ancestor):
            new_keep = keep
        else:
            # An ancestor such as src/ that the new location no longer has: reach the
            # repository root and name the folder from there.
            new_keep = 0
            suffix = "".join(f' / "{part}"' for part in ancestor)
        new_level = len(new_parts) - new_keep
        delta = new_level - level
        if delta == 0 and not suffix:
            continue
        if suffix:
            k = new_level - base_level - 1
            if k < 0:
                residue.append(f"{new_file}: {m.group(0)!r} cannot reach the repository root")
                continue
            edits.append((m.start(), m.end(), f"({base}.parents[{k}]{suffix})"))
            continue
        if index is not None:
            new_index = int(index) + delta
            if new_index < 0:
                residue.append(f"{new_file}: {m.group(0)!r} needs a negative parents index")
                continue
            new_text = f"{base}{chain}.parents[{new_index}]"
        else:
            steps = chain.count(".parent") + delta
            if steps < 1:
                residue.append(f"{new_file}: {m.group(0)!r} needs fewer .parent than it has")
                continue
            new_text = base + ".parent" * steps if steps <= 3 else f"{base}.parents[{steps - 1}]"
        edits.append((m.start(), m.end(), new_text))
    for start, end, new in reversed(edits):
        text = text[:start] + new + text[end:]
    return text, len(edits)


def eligible(path: str, moved: bool) -> bool:
    pure = PurePosixPath(path)
    if path in FROZEN_BYTES or path == MANIFEST_REL or pure.name in HISTORY_NAMES:
        return False
    if path.startswith(HISTORY_DIRS):
        return False
    if in_scope(path):
        return True
    return moved and pure.suffix.lower() == ".md"


def read(path: Path) -> str | None:
    try:
        data = path.read_bytes() if path.stat().st_size <= MAX_BYTES else b"\0"
        return None if b"\0" in data[:8192] else data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def edit_manifest(new_path: dict[str, str], mapf) -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    lines = text.split("\n")
    out, current = [], None
    for line in lines:
        m = re.match(r"^  - path: (\S+)\s*$", line)
        if m and m.group(1) in new_path:
            current = m.group(1)
            out.append(f"  - path: {new_path[current]}")
            continue
        if m:
            current = None
        out.append(line)
        if current and re.match(r"^    d427_target: ", line):
            out.append(f"    legacy: {current}")
            current = None
    text = "\n".join(out)
    # safety_modules entries are repo paths too.
    block = re.search(r"^safety_modules:\n((?:  - .*\n)+)", text, re.M)
    if block:
        body = re.sub(r"^(  - )(\S+)", lambda m: m.group(1) + mapf(m.group(2)), block.group(1), flags=re.M)
        text = text[:block.start(1)] + body + text[block.end(1):]
    MANIFEST.write_text(text, encoding="utf-8")


def update_colcon_roots(files: list[str]) -> list[str]:
    """Top-level folders that hold a package.xml; add COLCON_IGNORE to wheel-only dirs."""
    text = MANIFEST.read_text(encoding="utf-8")
    current = [r.strip() for r in re.search(r"^colcon_roots: \[([^\]]*)\]", text, re.M).group(1).split(",")]
    tops = {PurePosixPath(f).parts[0] for f in files if PurePosixPath(f).name == "package.xml"}
    keep = [r for r in current if r in tops or (r == "src" and any(f.startswith("src/") for f in files))]
    roots = [r for r in ROOT_ORDER if r in keep or r in tops] + [r for r in keep if r not in ROOT_ORDER]
    text = re.sub(r"^colcon_roots: \[[^\]]*\]", f"colcon_roots: [{', '.join(roots)}]", text, count=1, flags=re.M)
    MANIFEST.write_text(text, encoding="utf-8")
    added = []
    have = set(files)
    for f in files:
        pure = PurePosixPath(f)
        if pure.name != "pyproject.toml" or pure.parts[0] not in roots:
            continue
        folder = str(pure.parent)
        if f"{folder}/package.xml" in have or f"{folder}/COLCON_IGNORE" in have:
            continue
        (ROOT / folder / "COLCON_IGNORE").write_bytes(b"")
        added.append(f"{folder}/COLCON_IGNORE")
    if added:
        git("add", "--", *added)
    return roots


def residue_report() -> list[str]:
    roots = load_roots()
    legacies = {r["legacy"]: r["path"] for r in roots if r.get("legacy")}
    scan = LegacyScan(legacies)
    from test_platform_parts import LEGACY_SCAN_ALLOWLIST as allow
    found = []
    for path in tracked():
        if not in_scope(path):
            continue
        data = (ROOT / path).read_bytes() if (ROOT / path).is_file() else b"\0"
        text = data.decode("utf-8", "replace") if b"\0" not in data[:8192] else ""
        for form, matched, legacy in scan.findings(path, text):
            if (path, matched) in allow:
                continue
            found.append(f"{path}: {form} {matched!r} -> {legacy} (now {legacies[legacy]})")
    return sorted(set(found))


def run(wave: str, dry_run: bool) -> None:
    roots = load_roots()
    moves, new_path = plan(wave, roots)
    if not new_path:
        raise SystemExit(f"wave {wave}: nothing pending")
    mapf = mapper(new_path)
    print(f"wave {wave}:")
    for old, new in new_path.items():
        print(f"  {old} -> {new}")
    for src, dst in moves:
        print(f"  git mv {src} {dst}")
    if dry_run:
        return
    dirty = [line for line in git("status", "--porcelain", "--untracked-files=no").splitlines()
             if not line.endswith("tools/harness/d427_move.py")]
    if dirty:
        raise SystemExit("worktree not clean")

    before = tracked()
    old_paths = set(before) | {"."}
    for f in before:
        parts = PurePosixPath(f).parts
        for i in range(1, len(parts)):
            old_paths.add("/".join(parts[:i]))
    for src, dst in moves:
        (ROOT / dst).parent.mkdir(parents=True, exist_ok=True)
        if (ROOT / dst).exists() and not git("ls-files", "--", dst).strip():
            shutil.rmtree(ROOT / dst)  # untracked leftovers only (__pycache__ of an earlier run)
        git("mv", src, dst)
    old_of = {mapf(f): f for f in before}
    moved_files = sum(1 for f in before if mapf(f) != f)

    edit_manifest(new_path, mapf)
    tops = [old for old in new_path if not any(under(old, o) and old != o for o in new_path)]
    slash = slash_pattern(sorted(new_path, key=len, reverse=True))
    joins = join_patterns(new_path)
    last_segs = {old.rsplit("/", 1)[-1] for old in new_path}
    residue: list[str] = []
    changed, stats = [], {"relative": 0, "slash": 0, "join": 0, "parents": 0}
    after = tracked()
    for path in after:
        old_file = old_of.get(path, path)
        moved = old_file != path
        if not eligible(path, moved):
            continue
        text = read(ROOT / path)
        if text is None:
            continue
        new = text
        if moved or "../" in new:
            new, n = rewrite_relative(new, old_file, path, mapf, old_paths, residue)
            stats["relative"] += n
        if moved and path.endswith(".py"):
            top = next(o for o in tops if under(old_file, o))
            new, n = rewrite_parents(new, old_file, path, top, new_path[top], residue)
            stats["parents"] += n
        if any(seg in new for seg in last_segs):
            new, n = rewrite_slash(new, slash, new_path, "Dockerfile" in PurePosixPath(path).name)
            stats["slash"] += n
            new, n = rewrite_join(new, joins, new_path)
            stats["join"] += n
            new, n = rewrite_srcvar(new, new_path, path)
            stats["srcvar"] = stats.get("srcvar", 0) + n
        if new != text:
            if path.endswith(".py"):
                try:
                    compile(new, path, "exec")
                except SyntaxError as error:
                    residue.append(f"{path}: rewrite broke the syntax ({error}); kept the old text")
                    continue
            (ROOT / path).write_bytes(new.encode("utf-8"))
            changed.append(path)
    roots = update_colcon_roots(tracked())
    git("add", "--", MANIFEST_REL, *changed)
    print(f"moved files: {moved_files}; rewritten files: {len(changed)}; {stats}")
    print(f"colcon_roots: {roots}")
    for line in sorted(set(residue)):
        print(f"  manual: {line}")
    print_report()


def print_report() -> None:
    report = residue_report()
    print(f"legacy residue: {len(report)}")
    for line in report:
        print(f"  {line}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("wave", nargs="?")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--srcvars", action="store_true",
                        help="re-apply only the SRC-variable rewrite (e) for an already moved wave")
    args = parser.parse_args()
    if args.srcvars:
        mapping = {r["legacy"]: r["path"] for r in load_roots() if r.get("wave") == args.wave and r.get("legacy")}
        for path in (path for path in tracked() if eligible(path, False)):
            text = read(ROOT / path)
            new, n = rewrite_srcvar(text, mapping, path) if text is not None else (text, 0)
            if n:
                (ROOT / path).write_bytes(new.encode("utf-8"))
                print(f"  srcvar x{n}: {path}")
    elif args.report or not args.wave:
        print_report()
    else:
        run(args.wave, args.dry_run)


if __name__ == "__main__":
    main()
