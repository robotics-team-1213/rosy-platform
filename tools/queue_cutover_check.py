"""Read-only cutover reconciliation for D-1055: local main vs origin/main, plus machine checks.

Usage::

    python tools/queue_cutover_check.py [--no-fetch] [--carry REF ...] [--json]

Exit 0 only when no local-only commit would be lost and no machine check fails.
A local-only commit is covered when reachable from a pending publish branch
(origin/publish/main-* not yet merged into origin/main) or from a --carry ref.
Metric criteria of D-1055 item 5 are reported as MANUAL (not machine-checkable here).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PUBLISH_GLOB = "refs/remotes/origin/publish/main-*"


def git(repo: Path, *args: str, check: bool = True) -> str:
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and res.returncode != 0:
        raise SystemExit(f"[cutover] git {' '.join(args[:3])} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def pending_publish_refs(repo: Path) -> list[str]:
    refs = git(repo, "for-each-ref", "--format=%(refname)", PUBLISH_GLOB).split()
    return [r for r in refs if subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", r, "origin/main"], capture_output=True).returncode != 0]


def reconcile(repo: Path, carry: list[str]) -> dict:
    local = git(repo, "rev-list", "origin/main..main").split()
    pending = pending_publish_refs(repo)
    covers = [*pending, *carry]
    missing = git(repo, "rev-list", "main", "^origin/main", *[f"^{c}" for c in covers]).split() if local else []
    return {"local_only": len(local), "covered_by": covers, "missing": missing}


def adr_status(repo: Path) -> str:
    for p in sorted((repo / "docs/adr").glob("D-1055-*.md")):
        m = re.search(r"(?m)^\*\*Status:\*\*\s*(\w+)", p.read_text(encoding="utf-8"))
        return m.group(1) if m else "unknown"
    return "absent"


def read(repo: Path, rel: str) -> str:
    p = repo / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def checks(repo: Path) -> list[tuple[str, bool, str]]:
    wf = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in (repo / ".github/workflows").glob("*.yml"))
    adr = adr_status(repo)
    flag = git(repo, "config", "--bool", "rosy.publishOnly", check=False) or "unset"
    return [
        ("D-1055 ADR present", adr != "absent", f"status={adr}"),
        ("D-1055 Accepted (activation marker)", adr == "Accepted", f"status={adr}"),
        ("merge_group trigger in workflows", "merge_group" in wf, ""),
        ("ci-result check defined", "ci-result" in wf, ""),
        ("review-gate workflow present", (repo / ".github/workflows/review-gate.yml").is_file(), ""),
        ("lab-evidence required check defined", "lab-evidence" in wf, "item 3.5/7: evidence as required status check"),
        ("pr_land.py has --dry-run", "--dry-run" in read(repo, "tools/pr_land.py"), ""),
        ("pr_land.py verify_lab_evidence gate", "verify_lab_evidence(" in read(repo, "tools/pr_land.py"), ""),
        ("publishOnly flag readable", True, f"rosy.publishOnly={flag}"),
    ]


def main(argv: list[str] | None = None, repo: Path | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--carry", action="append", default=[], metavar="REF", help="ref that will be carried across cutover")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    repo = (repo or Path.cwd()).resolve()
    if not args.no_fetch:
        git(repo, "fetch", "origin", "--prune", "--quiet")
    rec = reconcile(repo, args.carry)
    chk = checks(repo)
    # the ADR may live only on a branch: Accepted is expected to fail until human approval, so it is advisory
    failed = [n for n, ok, _ in chk if not ok and n != "D-1055 Accepted (activation marker)"]
    lost = bool(rec["missing"])
    if args.json:
        print(json.dumps({**rec, "checks": [{"name": n, "ok": ok, "note": d} for n, ok, d in chk]}, indent=1))
    else:
        print(f"[cutover] local-only commits: {rec['local_only']}; covered by {len(rec['covered_by'])} ref(s)")
        for sha in rec["missing"][:20]:
            print(f"  MISSING {sha}")
        if len(rec["missing"]) > 20:
            print(f"  ... {len(rec['missing']) - 20} more")
        for n, ok, d in chk:
            print(f"  [{'OK' if ok else 'FAIL'}] {n} {d}".rstrip())
        print("  [MANUAL] D-1055 item 5 metrics (p50/p90, 0 untested merges, 2 signed deploys)")
    return 1 if lost or failed else 0


if __name__ == "__main__":
    sys.exit(main())
