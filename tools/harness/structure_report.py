"""Structure report: where the tree is over its size rule and what to split next (D-773).

python tools/harness/structure_report.py [--json] [--top N]

Measures the current tree with the same counter as test/architecture/test_module_structure.py
(``size_limits.measure``), so every number matches the size gate. For each unit or package above
the 10,000-line unit limit it groups the files the unit still owns directly (not yet in a
registered sub-unit) by folder and file-name prefix and lists the largest groups: those are the
split candidates. It also counts the frozen exception lists that should only shrink (known import
violations, known safety violations, Fleet ledger writers). Read-only; it changes nothing.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/harness"))
import size_limits  # noqa: E402

ARCH = ROOT / "test/architecture"
#: test module -> the exception set it keeps (each only shrinks).
FROZEN_LISTS = (
    ("test_platform_parts.py", "KNOWN_VIOLATIONS", "import edges across manifest roots"),
    ("test_safety_separation.py", "KNOWN_SAFETY_VIOLATIONS", "safety separation exceptions"),
    ("test_fleet_ledger_writers.py", "KNOWN_WRITERS", "modules writing Fleet ledger tables"),
)
MIN_GROUP_LINES = 300


def _load(name: str):
    path = ARCH / name
    if not path.is_file():
        return None
    sys.path.insert(0, str(ARCH))
    spec = importlib.util.spec_from_file_location(f"_structure_report_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _group(path: str) -> str:
    """folder + the file name's first word: server/goal_evidence_store.py -> server/goal_*."""
    pure = PurePosixPath(path)
    return f"{pure.parent.as_posix()}/{pure.stem.split('_', 1)[0]}*"


def report(top: int = 5) -> dict:
    structure = _load("test_module_structure.py")
    files_lines = {}
    counts, over, owner = structure._measure()
    for path in owner:
        full = ROOT / path
        if full.is_file():
            files_lines[path] = sum(1 for _ in full.open(encoding="utf-8", errors="replace"))
    units = []
    for key, lines in sorted(counts.items(), key=lambda item: -item[1]):
        if lines <= size_limits.UNIT_LIMIT:
            continue
        groups: dict[str, int] = defaultdict(int)
        for path, unit in owner.items():
            if unit == key and path in files_lines:
                groups[_group(path)] += files_lines[path]
        candidates = sorted(((g, n) for g, n in groups.items() if n >= MIN_GROUP_LINES), key=lambda gn: -gn[1])
        units.append({"unit": key, "lines": lines, "limit": size_limits.UNIT_LIMIT,
                      "excess": lines - size_limits.UNIT_LIMIT,
                      "split_candidates": [{"group": g, "lines": n} for g, n in candidates[:top]]})
    over_files = sorted(((k, v) for k, v in over.items() if PurePosixPath(k).suffix), key=lambda kv: -kv[1])
    frozen = []
    for module_name, attribute, meaning in FROZEN_LISTS:
        module = _load(module_name)
        if module is not None and hasattr(module, attribute):
            frozen.append({"list": f"{module_name}::{attribute}", "meaning": meaning,
                           "entries": len(getattr(module, attribute))})
    return {"units_over_limit": units, "files_over_limit": len(over_files),
            "largest_files": [{"file": k, "lines": v} for k, v in over_files[:top]], "frozen_lists": frozen}


def markdown(data: dict) -> str:
    out = ["# Structure report", "", "## Units over the 10,000-line limit", "",
           "| unit | lines | over by | split candidates (folder/prefix: lines) |", "|---|---|---|---|"]
    for unit in data["units_over_limit"]:
        hint = ", ".join(f"`{c['group']}` {c['lines']}" for c in unit["split_candidates"]) or "-"
        out.append(f"| `{unit['unit']}` | {unit['lines']} | {unit['excess']} | {hint} |")
    out += ["", f"## Files over their limit: {data['files_over_limit']}", ""]
    out += [f"- `{f['file']}` {f['lines']}" for f in data["largest_files"]]
    out += ["", "## Frozen lists (only shrink)", "", "| list | entries | what |", "|---|---|---|"]
    out += [f"| `{f['list']}` | {f['entries']} | {f['meaning']} |" for f in data["frozen_lists"]]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--top", type=int, default=5, help="candidates and files to list per section")
    args = ap.parse_args(argv)
    data = report(max(args.top, 1))
    sys.stdout.write(json.dumps(data, indent=2) + "\n" if args.json else markdown(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
