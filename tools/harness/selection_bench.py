"""Selection bench: replay the affected-tests selector over fixed commits and report what it selects.

Usage (from the repository root)::

    python tools/harness/selection_bench.py --sample FILE [--harness-yaml X] [--parts-yaml Y]
        [--weights JSON] [--baseline JSON] [--out JSON]
    python tools/harness/selection_bench.py edges operations/fleet/fleet/server

--sample lists one commit per line; each is measured as c^...c with the files read at c
(as "rosy_harness.py affected --base c^ --head c"). --harness-yaml / --parts-yaml replace those
registries for every commit, so a mapping change is measured before it lands. --weights maps a test path
or basename to seconds (default: Fleet's CI timings; others weigh 1). --baseline is an earlier --out:
the report then counts tests the baseline selected that this run drops. "edges" counts imports between the
subfolders of a flat-installed package ("from pkg import name", "pkg.name" and relative imports).
Read-only: it writes only --out. Standard library plus PyYAML, like the rest of the harness.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml  # noqa: E402

import affected_narrow  # noqa: E402
from affected_repo import Repo, _git  # noqa: E402
from affected_pack import SelectionError  # noqa: E402
from affected_tests import _full_paths, changed_files, moves, select  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = Path(__file__).with_name("fleet_test_seconds.json")
#: The first word of a selector reason, grouped: own module, reverse dependent, import, path reference, guard.
KINDS = (("own", ("changed", "module")), ("reverse", ("reverse",)), ("imports", ("imports",)),
         ("references", ("references", "reads")), ("guard", ("guard",)))
IMPORT = re.compile(r"^\s*from\s+(\.*[\w.]*)\s+import\s+\(?([\w, ]+)|^\s*import\s+([\w.]+)", re.M)


def kind(reasons: list[str]) -> str:
    words = {r.split(" ", 1)[0] for r in reasons}
    return next((name for name, firsts in KINDS if words & set(firsts)), "other")


def weight(path: str, weights: dict[str, float]) -> float:
    return weights.get(path, weights.get(PurePosixPath(path).name, 1.0))


def override(repo: Repo, harness_yaml: str | None, parts_yaml: str | None) -> None:
    """Swap in replacement registries the way Repo.load reads them."""
    if harness_yaml:
        repo.modules = list(yaml.safe_load(harness_yaml).get("modules") or [])
        repo._texts["tools/harness/harness.yaml"] = harness_yaml
    if parts_yaml:
        parts = yaml.safe_load(parts_yaml)
        repo.owners = [(r["path"], tuple(r.get("import_prefix") or ())) for r in parts.get("roots") or []]
        repo.safety_roots, repo.safety_modules = list(parts.get("roots") or []), set(parts.get("safety_modules") or ())
        repo._texts["tools/harness/platform_parts.yaml"] = parts_yaml


def measure(root: Path, commit: str, harness_yaml: str | None = None, parts_yaml: str | None = None) -> dict:
    """One commit: mode, each selected test file with its reason kind, escalations."""
    repo = Repo.load(root, commit)
    override(repo, harness_yaml, parts_yaml)
    base = f"{commit}^"
    changed = changed_files(root, base, commit)

    def base_text(path: str) -> str | None:
        try:
            return _git(root, "show", f"{base}:{path}")
        except SelectionError:
            return None
    texts = None
    if affected_narrow.HARNESS_YAML in changed:
        texts = (base_text(affected_narrow.HARNESS_YAML) or "", repo.text(affected_narrow.HARNESS_YAML))
    sel = select(repo, changed, moves(root, base, commit), texts, base_text)
    tests: dict[str, str] = {}
    if sel.mode == "full":
        for path in _full_paths(repo):
            tests.update((t, "full") for t in repo.test_files_under(path))
    else:
        for path, why in sel.reasons.items():
            tests.update((t, kind(why)) for t in repo.test_files_under(path) if t not in tests)
    return {"commit": commit, "mode": sel.mode, "changed": changed, "escalations": sel.escalations, "tests": tests}


def summarize(rows: list[dict], weights: dict[str, float], baseline: dict | None = None) -> dict:
    counts = sorted(len(r["tests"]) for r in rows)
    by_kind: dict[str, int] = {}
    for r in rows:
        for k in r["tests"].values():
            by_kind[k] = by_kind.get(k, 0) + 1
    out = {"commits": len(rows), "full": sum(r["mode"] == "full" for r in rows),
           "files_sum": sum(counts), "files_median": statistics.median(counts) if counts else 0,
           "files_p90": counts[int(len(counts) * 0.9)] if counts else 0,
           "seconds_sum": round(sum(weight(t, weights) for r in rows for t in r["tests"]), 1),
           "weighted_selections": sum(1 for r in rows for t in r["tests"] if weight(t, weights) != 1.0),
           "by_kind": by_kind}
    if baseline is not None:
        before = {b["commit"]: b for b in baseline.get("rows", [])}
        out["dropped"] = {}
        for r in rows:
            old = before.get(r["commit"])
            if old and "full" not in (old["mode"], r["mode"]):
                lost = sorted(set(old["tests"]) - set(r["tests"]))
                if lost:
                    out["dropped"][r["commit"]] = lost
    return out


def edges(root: Path, folder: str, package: str | None = None) -> dict[str, dict[str, int]]:
    """Import counts between the direct subfolders of folder, for a package installed flat.

    Modules are named by file stem (package.stem): source_packages installs every subfolder into one package.
    A file directly in folder belongs to "(root)".
    """
    base = root / folder
    package = package or ".".join(PurePosixPath(folder).parts[-2:])
    files = [f for f in sorted(base.rglob("*.py")) if "test" not in f.relative_to(base).parts]
    owner = {f.stem: (f.relative_to(base).parts[0] if len(f.relative_to(base).parts) > 1 else "(root)")
             for f in files if f.stem != "__init__"}
    counts: dict[str, dict[str, int]] = {}
    for f in files:
        src = owner.get(f.stem)
        if src is None:
            continue
        for frm, names, plain in IMPORT.findall(f.read_text(encoding="utf-8", errors="replace")):
            if plain:
                stems = [plain[len(package) + 1:]] if plain.startswith(package + ".") else []
            elif frm.startswith(package + "."):
                stems = [frm[len(package) + 1:]]
            elif frm in (package, "") or set(frm) == {"."}:
                stems = [n.strip() for n in names.split(",")]
            elif frm.startswith("."):
                stems = [frm.lstrip(".")]
            else:
                stems = []
            for stem in stems:
                dst = owner.get(stem.split(".")[0])
                if dst and dst != src:
                    counts.setdefault(src, {}).setdefault(dst, 0)
                    counts[src][dst] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("cmd", nargs="?", choices=("run", "edges"), default="run")
    ap.add_argument("folder", nargs="?", help="edges: the folder whose subfolders are counted")
    ap.add_argument("--package", help="edges: the flat package name (default: the folder's last two parts)")
    ap.add_argument("--sample", type=Path)
    ap.add_argument("--harness-yaml", type=Path)
    ap.add_argument("--parts-yaml", type=Path)
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--repo", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    if args.cmd == "edges":
        if not args.folder:
            ap.error("edges needs a folder")
        print(json.dumps(edges(args.repo, args.folder, args.package), indent=1, sort_keys=True))
        return 0
    if not args.sample:
        ap.error("--sample is required")
    commits = [c.strip() for c in args.sample.read_text(encoding="utf-8").splitlines() if c.strip()]
    harness_yaml = args.harness_yaml.read_text(encoding="utf-8") if args.harness_yaml else None
    parts_yaml = args.parts_yaml.read_text(encoding="utf-8") if args.parts_yaml else None
    weights = json.loads(args.weights.read_text(encoding="utf-8")) if args.weights else {}
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    rows = [measure(args.repo, c, harness_yaml, parts_yaml) for c in commits]
    report = summarize(rows, weights, baseline)
    if args.out:
        args.out.write_text(json.dumps({"summary": report, "rows": rows}, ensure_ascii=False), encoding="utf-8")
    dropped = report.pop("dropped", None)
    if dropped is not None:
        report["dropped_commits"], report["dropped_tests"] = len(dropped), sum(map(len, dropped.values()))
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
