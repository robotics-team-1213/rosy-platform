"""Cutover freeze state (D-1055 panel 11-20): one file, <git-common-dir>/rosy-cutover.json, read by every landing path.

    {"phase": "normal" | "drain" | "open", "allow": [{"branch": ..., "sha": ...}], "owner": ..., "updated": ...}

normal (or no file): nothing changes. drain: only commits covered by an allowed sha may start, resume, requeue,
roll up, batch or move main; "covered" = every non-merge commit of the ref outside main is reachable from an
allowed sha, so a sha that changed or was removed mid-landing is refused at the last guard (land.py's fast-forward).
open: new landings on a publishOnly clone are refused (use pr_land.py); a landing already in a hidden tree drains.
An unreadable file counts as drain with nothing allowed: a damaged state stops publishing, never opens it.

    python tools/land_freeze.py show
    python tools/land_freeze.py set normal|drain|open [--owner NAME]
    python tools/land_freeze.py allow <branch> <sha> [--remove]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

NAME, PHASES, HOLDER = "rosy-cutover.json", ("normal", "drain", "open"), "rosy-land-wt"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def path(cwd: Path) -> Path:
    return Path(_git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()) / NAME


def load(cwd: Path) -> dict:
    """The state; no file is normal, an unreadable or malformed one is drain with nothing allowed."""
    try:
        state = json.loads(path(cwd).read_text(encoding="utf-8"))
        if state["phase"] not in PHASES or not all(isinstance(a["sha"], str) for a in state.get("allow", [])):
            raise ValueError(state["phase"])
        return state
    except FileNotFoundError:
        return {"phase": "normal", "allow": []}
    except (OSError, ValueError, KeyError, TypeError):
        return {"phase": "drain", "allow": [], "broken": True}


def save(cwd: Path, state: dict) -> None:
    """Atomic: write beside the file, then replace, so a reader sees the old or the new state, never half."""
    target = path(cwd)
    state = {**state, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    fd, tmp = tempfile.mkstemp(prefix=NAME + ".", dir=target.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1)
    os.replace(tmp, target)


def refusal(cwd: Path, ref: str | None = None, *, new: bool = True) -> str | None:
    """One-line refusal, or None when this landing may go on. ``new``: a start (open phase refuses it);
    False for the last guard before main moves, where an open-phase landing drains."""
    state = load(cwd)
    where = path(cwd)
    if state["phase"] == "open":
        publish_only = _git(cwd, "config", "--bool", "rosy.publishOnly").stdout.strip() == "true"
        if new and publish_only and HOLDER not in Path(cwd).resolve().parts:
            return f"[freeze] {where}: phase open: new landings are closed on this clone; use tools/pr_land.py"
        return None
    if state["phase"] != "drain" or ref is None:
        return None
    shas = [a["sha"] for a in state.get("allow", []) if _git(cwd, "cat-file", "-e", a["sha"] + "^{commit}").returncode == 0]
    extra = _git(cwd, "rev-list", "--no-merges", ref, "^main", *(f"^{s}" for s in shas))
    if extra.returncode == 0 and not extra.stdout.split():
        return None
    why = "state file unreadable" if state.get("broken") else f"{ref[:40]} is not in the allowed list"
    return f"[freeze] {where}: phase drain: {why}; no new landing (python tools/land_freeze.py show)"


def guard(cwd: Path, ref: str | None = None, new: bool = True) -> None:
    if why := refusal(cwd, ref, new=new):
        raise SystemExit(why)


def _sync_github_vars(cwd: Path, state: dict) -> None:
    allow_shas = " ".join(a["sha"] for a in state.get("allow", []))
    for name, value in (("ROSY_CUTOVER_PHASE", state["phase"]), ("ROSY_CUTOVER_ALLOW", allow_shas)):
        try:
            res = subprocess.run(
                ["gh", "variable", "set", name, "--body", value],
                cwd=str(cwd), capture_output=True, text=True,
            )
            if res.returncode != 0:
                detail = (res.stderr or res.stdout or f"exit {res.returncode}").strip()
                print(f"[freeze] warning: gh variable set {name} failed: {detail}", file=sys.stderr)
        except OSError as exc:
            print(f"[freeze] warning: gh variable set {name} failed: {exc}", file=sys.stderr)


def main(argv: list[str]) -> int:
    cwd = Path.cwd()
    if argv[:1] == ["show"]:
        print(f"{path(cwd)}\n{json.dumps(load(cwd), indent=1)}")
        return 0
    state = load(cwd)
    if argv[:1] == ["set"] and len(argv) >= 2 and argv[1] in PHASES:
        state.pop("broken", None)
        state["phase"] = argv[1]
        if "--owner" in argv[:-1]:
            state["owner"] = argv[argv.index("--owner") + 1]
    elif argv[:1] == ["allow"] and len(argv) >= 3:
        sha = _git(cwd, "rev-parse", "--verify", argv[2] + "^{commit}").stdout.strip()
        if not sha:
            print(f"[freeze] {argv[2]} is not a commit here", file=sys.stderr)
            return 1
        state.pop("broken", None)
        rest = [a for a in state.get("allow", []) if (a["branch"], a["sha"]) != (argv[1], sha)]
        state["allow"] = rest if "--remove" in argv else [*rest, {"branch": argv[1], "sha": sha}]
    else:
        print(__doc__)
        return 2
    save(cwd, state)
    _sync_github_vars(cwd, state)  # every saved change, so ROSY_CUTOVER_ALLOW never goes stale
    print(f"[freeze] {path(cwd)}: phase {state['phase']}, {len(state.get('allow', []))} allowed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
