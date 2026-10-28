"""tools/land.py conflict auto-resolution (split from land.py, pure move).

Which conflicted paths land.py may resolve itself (ADR Log, logs.md, adr_gaps.txt, index.md and the
generated files) and the bytes it writes for them. ``plan`` touches nothing; ``land.merge`` applies it.
Standard library only.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from land_logs import append_blocks, shared  # logs.md: whole entries, date order

ADR_LOG = "docs/reference/ROSY ADR Log.md"
ADR_GAPS = "tools/harness/adr_gaps.txt"  # from the ADR-reservation branch; absent until it lands
ADR_ROW = re.compile(rb"^\| D-(\d+) \|")
GENERATED = {"STATUS.md", "docs/reference/sim2real-gaps.md"}
ENV = {**os.environ, "PYTHONUTF8": "1"}


def generate_records(wt: Path, python: str, harness: str) -> list[str]:
    """Use this checkout's renderer; return only its declared, written paths."""
    root = wt.resolve()
    script = (wt / harness).resolve()
    if not script.is_relative_to(root) or ".git" in script.relative_to(root).parts:
        raise ValueError("harness must belong to the worktree")
    program = """
import json, runpy, sys
from pathlib import Path
repo, script = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
sys.path.insert(0, str(script.parent))
namespace = runpy.run_path(str(script))
targets = namespace["generated_targets"](repo)
for path in targets:
    resolved = path.resolve()
    if (resolved == repo or not resolved.is_relative_to(repo)
            or ".git" in resolved.relative_to(repo).parts
            or (resolved.exists() and not resolved.is_file())):
        raise ValueError("unsafe generated target: " + str(path))
written = namespace["generate"](repo)
print(json.dumps({"targets": [p.resolve().relative_to(repo).as_posix() for p in targets],
                  "written": [p.resolve().relative_to(repo).as_posix() for p in written]}))
"""
    result = subprocess.run([python, "-c", program, str(root), str(script)], cwd=wt,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV)
    if result.returncode:
        raise ValueError(f"canonical generation failed:\n{(result.stdout + result.stderr)[-3000:]}")
    data = json.loads(result.stdout)
    targets, written = data["targets"], data["written"]
    if not isinstance(targets, list) or not isinstance(written, list):
        raise ValueError("invalid canonical generation result")
    for rel in targets + written:
        if not isinstance(rel, str) or not rel:
            raise ValueError("invalid generated path")
        path = (root / rel).resolve()
        if path == root or not path.is_relative_to(root) or ".git" in path.relative_to(root).parts:
            raise ValueError(f"unsafe generated path: {rel}")
    if not set(written).issubset(targets):
        raise ValueError("generator wrote undeclared targets")
    print(f"[generate] {len(written)} canonical record(s)", flush=True)
    return written


def resolver(path: str) -> str | None:
    """How a conflicted path is auto-resolved, or None when a human must decide."""
    name = PurePosixPath(path).name
    if path == ADR_LOG:
        return "adr-log"
    if name == "logs.md":
        return "append"
    if path == ADR_GAPS:
        return "union-dedupe"
    if name == "AGENTS.md":
        return "table-rows"
    # progress.md is hand-written lint input (gates), not generated: a human resolves it.
    if name == "index.md" or path in GENERATED:
        return "generated"
    return None


def _blob(wt: Path, oid: str, path: str) -> bytes:
    # --filters gives the working-tree form (CRLF under core.autocrlf), so the
    # result keeps the file's line endings and `git add` cleans it as usual.
    return subprocess.run(["git", "-C", str(wt), "cat-file", "--filters", f"--path={path}", oid],
                          capture_output=True, check=True, env=ENV).stdout


def conflict_stages(text: str) -> dict[str, dict[int, str]]:
    """`<mode> <oid> <stage>\\t<path>` lines (ls-files -u, merge-tree) -> {path: {stage: oid}}."""
    found: dict[str, dict[int, str]] = {}
    for line in text.splitlines():
        match = re.match(r"^\d+ ([0-9a-f]+) ([123])\t(.+)$", line)
        if match:
            found.setdefault(match.group(3), {})[int(match.group(2))] = match.group(1)
    return found


def union(base: bytes, ours: bytes, theirs: bytes) -> bytes:
    """Both sides' added lines, ours then theirs (git merge-file --union)."""
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
            files.append(Path(tmp, name))
            files[-1].write_bytes(data)
        return subprocess.run(["git", "merge-file", "-p", "--union", *map(str, files)],
                              capture_output=True, env=ENV).stdout


def clashes_are_insertions(base: bytes, ours: bytes, theirs: bytes) -> bool:
    """True when every change touching the other side's change only adds lines.

    A side that rewrote or dropped a base line next to the other side's append
    would come back from a line union with the old line resurrected.
    """
    b = base.splitlines(keepends=True)

    def changes(side: bytes) -> list[tuple[str, int, int]]:
        ops = difflib.SequenceMatcher(None, b, side.splitlines(keepends=True), autojunk=False).get_opcodes()
        return [(op, i1, i2) for op, i1, i2, _, _ in ops if op != "equal"]

    mine, other = changes(ours), changes(theirs)
    for side, against in ((mine, other), (other, mine)):
        for op, i1, i2 in side:
            # Adjacent (touching) ranges conflict in git too, hence <= on both ends.
            if op != "insert" and any(i1 <= j2 and j1 <= i2 for _, j1, j2 in against):
                return False
    return True


def sort_adr_rows(data: bytes) -> bytes:
    """Sort each run of ``| D-n |`` rows by number and drop identical rows; BOM/EOL kept."""
    rows = data.splitlines(keepends=True)
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    result: list[bytes] = []
    i = 0
    while i < len(rows):
        if not ADR_ROW.match(rows[i]):
            result.append(rows[i])
            i += 1
            continue
        j = i
        while j < len(rows) and ADR_ROW.match(rows[j]):
            j += 1
        run = [r.rstrip(b"\r\n") for r in rows[i:j]]
        run = sorted(dict.fromkeys(run), key=lambda r: int(ADR_ROW.match(r).group(1)))
        last_eol = rows[j - 1][len(rows[j - 1].rstrip(b"\r\n")):]
        result += [r + eol for r in run[:-1]] + [run[-1] + last_eol]
        i = j
    return b"".join(result)


def _rows(data: bytes) -> tuple[list[bytes], dict[tuple[int, bytes], bytes]] | None:
    """(lines outside tables, {(table number, first cell): row}), or None when a table repeats a first cell."""
    other, rows, table, inside = [], {}, -1, False
    for line in data.splitlines(keepends=True):
        if line.startswith(b"|"):
            table += not inside
            inside = True
            key = (table, line.split(b"|")[1].strip())
            if key in rows:
                return None
            rows[key] = line
        else:
            inside = False
            other.append(line)
    return other, rows


def table_rows(base: bytes, ours: bytes, theirs: bytes) -> bytes | None:
    """Both sides' row edits of AGENTS.md tables keyed by first cell, in theirs' (main's) order with this branch's
    new rows after the row they follow; None when a row changed on both sides (or was dropped on one and edited
    on the other) or anything outside the tables changed. Two landings lost 121 and 149 min of queue to one
    AGENTS.md table where each had edited a different row (2026-10-26)."""
    parts = [_rows(x) for x in (base, ours, theirs)]
    if None in parts or not parts[0][0] == parts[1][0] == parts[2][0]:
        return None
    (_, b), (_, o), (_, t) = parts
    chosen = {}
    for key in {*b, *o, *t}:
        bv, ov, tv = b.get(key), o.get(key), t.get(key)
        if ov == bv:
            chosen[key] = tv
        elif tv == bv or tv == ov:
            chosen[key] = ov
        else:
            return None
    out, table, inside = [], -1, False
    ours_order = list(o)
    for line in theirs.splitlines(keepends=True):
        if not line.startswith(b"|"):
            inside = False
            out.append(line)
            continue
        table += not inside
        inside = True
        key = (table, line.split(b"|")[1].strip())
        if chosen.get(key) is not None:
            out.append(chosen[key])
        for later in ours_order[ours_order.index(key) + 1:] if key in o else []:
            if later in t or later in b or chosen.get(later) is None:
                break
            out.append(chosen[later])  # this branch's new row(s) right after the row they follow
    added = [chosen[k] for k in o if k not in b and k not in t]
    return b"".join(out) if all(row in out for row in added) else None  # a new row's neighbour was dropped


MARKER = re.compile(rb"^(<{7,}|>{7,}) ", re.MULTILINE)  # a virtual base nests longer markers (9 for one level)


def _resolve(kind: str, base: bytes, ours: bytes, theirs: bytes) -> bytes | None:
    if kind == "generated":
        return theirs
    if kind == "append":
        return append_blocks(base, ours, theirs)
    if kind == "table-rows":
        return table_rows(base, ours, theirs)
    if not clashes_are_insertions(base, ours, theirs):
        return None
    data = union(base, ours, theirs)
    return sort_adr_rows(data) if kind == "adr-log" else b"".join(dict.fromkeys(data.splitlines(keepends=True)))


def _real_bases(wt: Path, sides: tuple[str, str], path: str) -> list[bytes]:
    """``path`` at each real merge base of ``sides`` (``git merge-base --all``), oldest first."""
    found = subprocess.run(["git", "-C", str(wt), "merge-base", "--all", *sides], capture_output=True, text=True,
                           env=ENV).stdout.split()
    found.sort(key=lambda sha: subprocess.run(["git", "-C", str(wt), "show", "-s", "--format=%ct", sha],
                                              capture_output=True, text=True, env=ENV).stdout.strip())
    blobs = []
    for sha in found:
        oid = subprocess.run(["git", "-C", str(wt), "rev-parse", "--verify", "-q", f"{sha}:{path}"],
                             capture_output=True, text=True, env=ENV).stdout.strip()
        if oid:
            blobs.append(_blob(wt, oid, path))
    return blobs


def plan(wt: Path, conflicts: dict[str, dict[int, str]],
         sides: tuple[str, str] | None = None) -> tuple[dict[str, bytes], list[str]]:
    """Resolved bytes per auto-resolvable path, and `path: why` for the rest. Touches nothing.

    With criss-cross history (two merge bases) git's stage 1 is a virtual base that may itself hold conflict
    markers, so every base entry looks dropped (2026-10-28, isaac3-environment-repair, publish-pinned-hook).
    Given the merged ``sides``, such a base is replaced: for the append-only logs by the entries both sides hold
    (``land_logs.shared``), for the other records by each real merge base in turn, oldest first."""
    resolved: dict[str, bytes] = {}
    manual: list[str] = []
    for path, stage in conflicts.items():
        kind = resolver(path)
        if not kind:
            manual.append(f"{path}: not in the auto-resolvable set")
            continue
        if set(stage) != {1, 2, 3}:
            manual.append(f"{path}: modify/delete or add/add (stages {sorted(stage)})")
            continue
        base, ours, theirs = (_blob(wt, stage[n], path) for n in (1, 2, 3))
        data = _resolve(kind, base, ours, theirs)
        if data is None and sides and MARKER.search(base):
            bases = [shared(ours, theirs)] if kind == "append" else _real_bases(wt, sides, path)
            data = next((d for real in bases if (d := _resolve(kind, real, ours, theirs)) is not None), None)
        if data is None:
            manual.append(f"{path}: a side changed existing lines, not only appended")
        else:
            resolved[path] = data
    return resolved, manual


def landed_gaps(wt: Path) -> tuple[bytes, list[str]]:
    """adr_gaps.txt without the lines whose ADR now exists (docs/adr file or Log row), and the ids dropped.

    adr_gaps.txt merges with merge=union, so a merge of main keeps this branch's copy of a line main already
    removed when that ADR landed, and lint then fails "declared gap now exists" (three branches, 2026-10-19).
    """
    path = wt / ADR_GAPS
    if not path.is_file():
        return b"", []
    present = {f"D-{m.group(1)}" for p in (wt / "docs/adr").glob("D-*.md") if (m := re.match(r"D-(\d+)-", p.name))}
    if (wt / ADR_LOG).is_file():
        present |= {f"D-{int(m.group(1))}" for row in (wt / ADR_LOG).read_bytes().splitlines()
                    if (m := ADR_ROW.match(row))}
    data = path.read_bytes()
    kept, dropped = [], []
    for line in data.splitlines(keepends=True):
        words = line.decode("utf-8", "replace").lstrip("﻿").split(None, 1)
        if words and words[0] in present:
            dropped.append(words[0])
        else:
            kept.append(line)
    result = b"".join(kept)
    if data.startswith(b"\xef\xbb\xbf") and not result.startswith(b"\xef\xbb\xbf"):
        result = b"\xef\xbb\xbf" + result
    return result, sorted(set(dropped), key=lambda i: int(i[2:]))
