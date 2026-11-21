"""Land a personal topic branch through a GitHub PR + Merge Queue (D-762 / D-1052).

Usage::

    python tools/pr_land.py [--title "..."] [--self-review "<reason>"] [--evidence] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
for _extra in (str(TOOLS), str(TOOLS / "remote"), str(TOOLS / "harness"), str(TOOLS.parent / "test")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import affected_ci  # noqa: E402
import affected_exclusive  # noqa: E402
import land_cache  # noqa: E402
import land_freeze  # noqa: E402
import work_queue  # noqa: E402

ACT = next(e for e in affected_ci.CI_FULL_MATRIX if e["name"] == "omx-act-cpu")
ROOT_TEST = {"name": "root-test", "invocations": [["test"]]}
EXCLUDED_PREFIXES = ("integrations/simulation/", "learning/envs/isaac/", "middleware/devices/omx/adapter/")
PASSED_ID = re.compile(r"(?m)^(?:PASSED\s+(\S+)|(\S+::\S+)\s+PASSED\b)")


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> str:
    res = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and res.returncode != 0:
        raise SystemExit(f"{' '.join(cmd[:3])} failed ({res.returncode}): {(res.stderr or res.stdout).strip()}")
    return res.stdout.strip()


def ci_entry(inv: list[str]) -> dict | None:
    """Matching gating CI_FULL_MATRIX entry (or root test/), mirroring land_ci.ci_entry."""
    paths = [w.split("::", 1)[0].replace("\\", "/") for w in inv if not w.startswith("-")]
    acts = set(ACT["invocations"][0])
    if any(a == p or a.startswith(p.rstrip("/") + "/") for p in paths for a in acts):
        return ACT if all(p in acts for p in paths) else None
    for entry in (*affected_ci.CI_FULL_MATRIX, ROOT_TEST):
        roots = [w for i in entry["invocations"] for w in i if not w.startswith("-")]
        if entry is not ACT and entry.get("gating", True) and all(
                any(p == r or p.startswith(r + "/") for r in roots) for p in paths):
            return entry
    return None


def ci_runnable(inv: list[str]) -> bool:
    """Same CI-runnable filter as land_ci.runnable(), plus OMX adapter hardware suites."""
    paths = [w.replace("\\", "/") for w in inv if not w.startswith("-")]
    return bool(paths) and not (
        any(work_queue.ENV_WORD.match(w) for w in inv)
        or work_queue.lab_only(inv, above=False)  # a folder above the lab-only file is CI's root-test, not lab evidence
        or work_queue.host_alone(inv)
        or affected_exclusive.dedicated(inv)
        or any(p.startswith(EXCLUDED_PREFIXES) for p in paths)
    ) and ci_entry(inv) is not None


def split_by_ci_entry(inv: list[str]) -> list[list[str]]:
    """Split a mixed invocation into one part per CI entry; paths no entry covers stay together.

    Non-path words (flags, env tokens) go to every part, so ci_runnable() still rejects env/lab_only/alone parts.
    """
    paths = [w for w in inv if not w.startswith("-") and not work_queue.ENV_WORD.match(w)]
    extras = [w for w in inv if w not in paths]
    groups: dict[str, list[str]] = {}
    for p in paths:
        entry = ci_entry([p])
        groups.setdefault(entry["name"] if entry else "", []).append(p)
    parts = [extras + g for g in groups.values()]
    # a group that fails as a whole may hold only one bad path: isolate it so the CI-runnable paths drop out
    parts = [q for part in parts for q in ([part] if ci_runnable(part) or len(part) - len(extras) < 2
             else [extras + [p] for p in part[len(extras):]])]
    return parts if len(parts) > 1 else [inv]


def passed_ids(text: str) -> set[str]:
    first = text.split("=== D-762 flaky quarantine rerun ===", 1)[0]
    return {a or b for a, b in PASSED_ID.findall(first)}


def covers_lab_baseline(cwd: Path, head: str, argv: list[str], candidate_text: str) -> bool:
    """Guard ``CI passed IDs >= lab passed IDs`` (fix/landing-speed-bundle 27f65df867)."""
    rows = [r for r in land_cache.entries(cwd) if r["argv"] == argv and not str(r["env"]).startswith("gha:")]
    for row in reversed(rows[-50:]):
        log = Path(row.get("log", ""))
        try:
            data = log.read_bytes()
        except OSError:
            continue
        base_ids = passed_ids(data.decode("utf-8-sig", errors="replace"))
        if base_ids and row.get("log_sha256") == hashlib.sha256(data).hexdigest():
            if any(subprocess.run(["git", "-C", str(cwd), "merge-base", "--is-ancestor", row["commit"], tip],
                                  capture_output=True).returncode == 0 for tip in (head, "main")):
                return base_ids <= passed_ids(candidate_text)
    return True


def activated(cwd: Path) -> bool:
    """Activation marker for the shared publishOnly clone: git config rosy.prLandActivated=true or D-1055 Accepted."""
    if _run(["git", "config", "--bool", "rosy.prLandActivated"], cwd, check=False).lower() == "true":
        return True
    for adr in (cwd / "docs/adr").glob("D-1055-*.md"):
        if re.search(r"(?m)^\*\*Status:\*\*\s*Accepted\b", adr.read_text(encoding="utf-8", errors="replace")):
            return True
    return False


def cutover_refusal(cwd: Path) -> str | None:
    """Refuse submission while the cutover phase is drain; open and normal pass (activation is checked separately)."""
    state = land_freeze.load(cwd)
    if state["phase"] != "drain":
        return None
    who = state.get("owner") or "unknown"
    return f"[pr-land] cutover phase drain: PR submission closed; owner {who}; state file {land_freeze.path(cwd)}"


def check_coexistence(cwd: Path, head: str, *, allow_backlog: bool = False) -> str:
    """Enforce D-868 publishOnly separation and return base ref for PR diff checks."""
    if _run(["git", "config", "--bool", "rosy.publishOnly"], cwd, check=False).lower() == "true" and not activated(cwd):
        raise SystemExit(
            "[pr-land] rosy.publishOnly=true clone follows D-868: use land_async.py -> publish_main.py --via-ci "
            "(D-1055 not Accepted and rosy.prLandActivated unset; activation needs human approval)"
        )
    origin_main = _run(["git", "rev-parse", "--verify", "-q", "origin/main"], cwd, check=False)
    local_main = _run(["git", "rev-parse", "--verify", "-q", "main"], cwd, check=False)
    base = origin_main or local_main
    if not base:
        raise SystemExit("[pr-land] neither origin/main nor main exists; fetch origin/main first (refusing HEAD^ fallback)")
    behind_only = origin_main and local_main and subprocess.run(  # local main merely behind origin/main has nothing unpublished
        ["git", "-C", str(cwd), "merge-base", "--is-ancestor", local_main, origin_main], capture_output=True).returncode == 0
    if not allow_backlog and origin_main and local_main and origin_main != local_main and not behind_only:
        anc = subprocess.run(["git", "-C", str(cwd), "merge-base", "--is-ancestor", local_main, head], capture_output=True)
        if anc.returncode == 0:
            raise SystemExit(
                "[pr-land] branch descends from un-published local main ahead of origin/main; rebase onto origin/main or pass --allow-backlog"
            )
    return base


def required_lab_invocations(cwd: Path, base: str, head: str) -> list[list[str]]:
    """Return non-CI-runnable invocations touched by base..head (OMX adapter, browser, host_alone, LAB_ONLY, sim)."""
    sel = json.loads(_run([sys.executable, "tools/harness/rosy_harness.py", "affected", "--base", base, "--head", head, "--json"], cwd))
    invs = list(sel.get("local_invocations" if sel.get("mode") == "full" else "invocations") or [])
    changed = _run(["git", "diff", "--name-only", f"{base}...{head}"], cwd, check=False).splitlines()
    if any(p.startswith("middleware/devices/omx/adapter/") for p in changed):
        omx_suite = ["middleware/devices/omx/adapter/test"]
        if omx_suite not in invs:
            invs.append(omx_suite)
    if changed and (cwd / "test/browser_scope.py").is_file() and (cwd / "tools/land_browser.py").is_file():
        import browser_scope
        import land_browser
        import land_selection
        b_paths = browser_scope.targets(changed)
        for group in land_selection.pack(cwd, b_paths):
            invs.extend(land_browser.chunks(cwd, group))
    return [part for inv in invs for part in split_by_ci_entry(inv) if not ci_runnable(part)]


def lab_missing(cwd: Path, head: str, required: list[list[str]]) -> list[list[str]]:
    """Lab-only invocations without an intact land_cache pass on head's tree & env."""
    if not required:
        return []
    tree = _run(["git", "rev-parse", f"{head}^{{tree}}"], cwd)
    env = land_cache.env_id(cwd, head)
    rows = [
        r for r in land_cache.entries(cwd)
        if r.get("tree") == tree and r.get("env") == env and not str(r.get("env", "")).startswith("gha:")
    ]
    missing: list[list[str]] = []
    for inv in required:
        ok = False
        for row in reversed(rows):
            if row.get("argv") != inv:
                continue
            log = Path(row.get("log", ""))
            try:
                data = log.read_bytes()
            except OSError:
                continue
            if row.get("log_sha256") != hashlib.sha256(data).hexdigest():
                continue
            text = data.decode("utf-8-sig", errors="replace")
            if (passed_ids(text) or land_cache.ALL_SKIPPED.search(text)) and covers_lab_baseline(cwd, head, inv, text):
                ok = True
                break
        if not ok:
            missing.append(inv)
    return missing


def verify_lab_evidence(cwd: Path, head: str, required: list[list[str]]) -> None:
    """Require an intact lab land_cache pass for each lab-only invocation on head's tree & env."""
    missing = lab_missing(cwd, head, required)
    if missing:
        cmds = "; ".join(" ".join(inv) for inv in missing[:3])
        raise SystemExit(f"[pr-land] lab-only change requires remote_pytest lab evidence before auto-merge: {cmds}")


def session_name() -> str:
    return os.environ.get("ROSY_SESSION_NAME") or os.environ.get("CLAUDE_SESSION_NAME") or "unknown"


def build_body(summary: str, self_review: str) -> str:
    lines = [summary.strip() or "PR landing via Merge Queue (D-1052)."]
    if self_review.strip():
        lines += ["", f"Overlap-Review: self ({self_review.strip()})"]
    lines += ["", f"Session: {session_name()}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, repo: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", default="", help="PR title (default: tip commit subject)")
    parser.add_argument("--body", default="", help="PR description summary")
    parser.add_argument("--self-review", default="", metavar="REASON", help="include Overlap-Review: self (<REASON>)")
    parser.add_argument("--remote-prepush", action="store_true", help="keep remote pre-push tests enabled")
    parser.add_argument("--allow-backlog", action="store_true", help="allow PR from un-published local main ancestor")
    parser.add_argument("--verify-ci-log", nargs=2, metavar=("ARGV_JSON", "LOG_PATH"),
                        help="verify a CI log covers the lab baseline passed IDs for ARGV_JSON")
    parser.add_argument("--evidence", action="store_true",
                        help="run pr_evidence.py HEAD (real remote lab run) first when lab evidence is required")
    parser.add_argument("--dry-run", action="store_true", help="print commands without pushing/merging")
    args = parser.parse_args(argv)
    cwd = (repo or Path.cwd()).resolve()

    if args.verify_ci_log:
        head = _run(["git", "rev-parse", "HEAD"], cwd)
        inv = json.loads(args.verify_ci_log[0])
        text = Path(args.verify_ci_log[1]).read_text(encoding="utf-8-sig", errors="replace")
        if not covers_lab_baseline(cwd, head, inv, text):
            raise SystemExit(f"[pr-land] CI log misses lab baseline passed IDs for {inv}")
        print("[pr-land] CI log covers lab baseline passed IDs")
        return 0

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if branch in ("main", "HEAD"):
        raise SystemExit(f"[pr-land] checkout a topic branch first (got {branch})")
    if _run(["git", "status", "--porcelain"], cwd):
        raise SystemExit("[pr-land] working tree is dirty; commit explicit files first")

    head = _run(["git", "rev-parse", "HEAD"], cwd)
    refused = cutover_refusal(cwd)
    if refused and not args.dry_run:
        raise SystemExit(refused)
    base = check_coexistence(cwd, head, allow_backlog=args.allow_backlog)
    lab_needed = required_lab_invocations(cwd, base, head)
    if args.evidence and lab_needed:
        import pr_evidence  # lazy: pr_evidence imports pr_land

        if pr_evidence.main(["HEAD", "--base", base], repo=cwd):
            raise SystemExit("[pr-land] pr_evidence failed; no evidence recorded")
    verify_lab_evidence(cwd, head, lab_needed)

    title = args.title or _run(["git", "log", "-1", "--format=%s", "HEAD"], cwd)
    body = build_body(args.body, args.self_review)
    if args.dry_run:
        if refused:
            print(f"{refused} (a real run would stop here)")
        print(f"[pr-land] dry-run branch={branch} lab_required={len(lab_needed)} title={title!r}")
        print(f"[pr-land] plan: git push -u origin {branch}; gh pr create|edit (base main, head {branch}); "
              f"gh pr merge --auto --merge --match-head-commit {head}; then exit (no waiting)")
        return 0

    env = dict(os.environ)
    if not args.remote_prepush:
        env["ROSY_STATIC_PRE_PUSH"] = "1"
    if _run(["git", "config", "--bool", "rosy.publishOnly"], cwd, check=False).lower() == "true" and activated(cwd):
        # D-1055: reason only for this push's env, never global; check_coexistence already required activation.
        session = os.environ.get("ROSY_SESSION_NAME") or os.environ.get("CLAUDE_SESSION_NAME") or "unknown"
        env["ROSY_PUSH_REASON"] = f"pr_land D-1055 {session}"
    _run(["git", "push", "-u", "origin", branch], cwd, env=env)
    existing = json.loads(_run(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number"], cwd) or "[]")
    if existing:
        pr = str(existing[0]["number"])
        if args.self_review:
            _run(["gh", "pr", "edit", pr, "--body", body], cwd)
    else:
        url = _run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", body], cwd)
        pr = url.rstrip("/").rsplit("/", 1)[-1]
    _run(["gh", "pr", "merge", pr, "--auto", "--merge", "--match-head-commit", head], cwd)
    print(f"[pr-land] queued PR #{pr} ({branch}) in Merge Queue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
