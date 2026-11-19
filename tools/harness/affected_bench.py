"""CI selection bench: replay a fixed commit list through the affected selector (11-20, ralph loop).

Reports total CI jobs and selected test paths, and checks one safety invariant per commit: every test file
that names a changed Python module (import or path string) is still selected, unless the selection is FULL.
Exit 0 only when the job total is at or under --max-jobs and no invariant is broken.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8").stdout


def select(sha: str) -> dict:
    out = subprocess.run([sys.executable, str(ROOT / "tools/harness/rosy_harness.py"), "affected", "--base", f"{sha}^",
                          "--head", sha, "--ci-matrix"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    data = json.loads(out.stdout.strip().splitlines()[-1])
    jobs = data["matrix"]["include"]
    paths = set()
    for job in jobs:
        for inv in job.get("invocations", []) or []:
            paths.update(a for a in (inv if isinstance(inv, list) else str(inv).split()) if not a.startswith("-"))
    return {"mode": data.get("mode"), "jobs": len(jobs), "paths": paths}


def named_by_tests(sha: str) -> set[str]:
    changed = [p for p in _git("show", "--name-only", "--format=", sha).split() if p.endswith(".py") and "/test" not in p]
    need = set()
    for path in changed:
        stem = Path(path).stem
        if stem in ("__init__", "conftest"):
            continue
        # a bare module name collides across packages (vision, store): an import counts only inside the same
        # top-level tree; a full repo path string counts anywhere
        tree = "/".join(path.split("/")[:2])
        by_import = _git("grep", "-l", "-w", "-e", f"import {stem}", "-e", f"from {stem} import", sha, "--",
                         f"{tree}/**/test_*.py").split()
        by_path = _git("grep", "-l", "-F", "-e", path, sha, "--", "*test_*.py").split()
        need.update(h.split(":", 1)[1] for h in by_import + by_path if ":" in h)
    return need


def covered(test: str, paths: set[str]) -> bool:
    return any(test == p or test.startswith(p.rstrip("/") + "/") or p.startswith(test + "::") for p in paths)


def bench(sha: str) -> tuple[str, int, list[str], str]:
    sel = select(sha)
    if sel["mode"] == "full":
        return sha, sel["jobs"], [], "full"
    missing = sorted(t for t in named_by_tests(sha) if not covered(t, sel["paths"]))
    return sha, sel["jobs"], missing, sel["mode"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commits-file", required=True)
    ap.add_argument("--max-jobs", type=int, required=True)
    ap.add_argument("--allow", help="file of 'sha10 test' lines already missing at the baseline (selector gaps owned elsewhere)")
    args = ap.parse_args(argv)
    shas = [s.strip() for s in Path(args.commits_file).read_text().split() if s.strip()]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(bench, shas))
    total = sum(r[1] for r in rows)
    allowed = set(Path(args.allow).read_text().split("\n")) if args.allow else set()
    rows = [(s, n, [t for t in miss if f"{s[:10]} {t}" not in allowed], m) for s, n, miss, m in rows]
    broken = [(r[0][:10], r[2]) for r in rows if r[2]]
    print(f"commits={len(rows)} jobs={total} max={args.max_jobs} full={sum(r[3] == 'full' for r in rows)} broken={len(broken)}")
    for sha, miss in broken[:20]:
        print(f"  MISSING {sha}: {miss[:5]}")
    return 0 if total <= args.max_jobs and not broken else 1


if __name__ == "__main__":
    raise SystemExit(main())
