"""D-1036 addendum (2026-11-18): publication evidence scoped by app instead of one whole-repo FULL.

``check(publish, repo, sha)`` decides for one candidate sha whether its delta ``origin/main...sha`` is an
app-only delta and, if so, whether its affected selection plus mapped browser chunks have clean exact
evidence (``publish_evidence`` variants/clean/reach: no second oracle). Anything that needs FULL returns
mode ``full`` and the caller keeps today's rule: a delta touching ``core``, a safety-tagged path
(``safety_review.is_safety``) or a path the selector itself escalates to FULL (checked in the candidate's own
checkout). A red open MAIN-RED id (nightly or landing) blocks only a delta touching the app that owns its file.
App ``repo`` (addendum 2, 2026-11-19: docs, test infrastructure, operator-only tools) is never deployed: it neither
forces FULL nor adds an app, so a docs-only delta is published on its affected selection like an app delta;
``neutral`` (folder notes, ADRs) neither, and ``tooling`` (the landing and publish gate) forces FULL like core.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

import yaml

TOOLS = Path(__file__).resolve().parent
for _p in (TOOLS, TOOLS / "harness"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import affected_repo  # noqa: E402  (app_of)
import safety_review  # noqa: E402  (is_safety: the D-430 tag source)

SCOPED_TRIES = 20  # newest candidates tried in app mode; each costs a checkout of the candidate
PARTS = "tools/harness/platform_parts.yaml"
NEVER_DEPLOYED = {"repo", "neutral"}  # platform_parts.yaml apps that are no publish unit
WHOLE_REPO = ("core", "tooling")  # shared runtime and the landing/publish gate keep FULL
ALONE = re.compile(r"^tools/collect_alone\.py::test_(?:runs|collects)_alone\[(.+)\]$")


def parts_at(publish, repo: Path, sha: str) -> dict | None:
    shown = publish.git(repo, "show", f"{sha}:{PARTS}", check=False)
    parts = (yaml.safe_load(shown.stdout) or None) if shown.returncode == 0 else None
    # 11-19: a candidate from before the app split (no root "app") crashed publish_sha with KeyError; it has no app scope
    return parts if parts and all("app" in root for root in parts.get("roots") or []) else None


def full_reason(paths: list[str], parts: dict) -> str | None:
    """Why this delta keeps the whole-repo rule, or None for an app-only delta."""
    hit = next((app for p in paths if (app := affected_repo.app_of(p, parts)) in WHOLE_REPO), None)
    if hit:
        return f"touches {hit}"
    modules = set(parts.get("safety_modules") or ())
    hit = next((p for p in paths if safety_review.is_safety(p, parts.get("roots") or [], modules)), None)
    return f"safety path {hit}" if hit else None


def red_apps(repo: Path, parts: dict) -> dict[str, list[str]]:
    """App -> open MAIN-RED ids whose test file it owns (``land_mainred`` is the one red record)."""
    import land_mainred
    out: dict[str, list[str]] = {}
    for nodeid in land_mainred.state(repo):
        alone = ALONE.match(nodeid)
        out.setdefault(affected_repo.app_of(alone[1] if alone else nodeid.split("::")[0], parts), []).append(nodeid)
    return out


def check(publish, repo: Path, sha: str) -> tuple[bool, str | None]:
    """(qualified in app mode, one output line); the line is None when there is no scope to report."""
    import publish_evidence
    parts = parts_at(publish, repo, sha)
    base = publish.git(repo, "rev-parse", "origin/main").stdout.strip()
    if not parts:
        return False, None
    paths = publish.git(repo, "diff", "--name-only", f"{base}...{sha}").stdout.splitlines()
    apps = sorted({affected_repo.app_of(p, parts) for p in paths} - NEVER_DEPLOYED)
    head = f"{sha[:10]} apps={','.join(apps) or '-'}"
    why = full_reason(paths, parts)
    if why or not paths:
        return False, f"{head} mode=full ({why or 'empty delta'})"
    try:
        blocked = {a: ids for a, ids in red_apps(repo, parts).items() if a in apps}
    except (OSError, ValueError, ImportError) as exc:
        return False, f"{head} mode=app blocked: red record unreadable ({exc!r})"
    if blocked:
        shown = "; ".join(f"{a}: {ids[0]}" + (f" +{len(ids) - 1}" if len(ids) > 1 else "") for a, ids in blocked.items())
        return False, f"{head} mode=app blocked by red nightly/main-red in a touched app ({shown})"
    stats: dict = {}
    ok = publish_evidence.qualified(publish, repo, sha, {"base": base}, scoped=True, stats=stats)
    mode = "full" if stats.get("escalated") else "app"
    return ok, f"{head} mode={mode} required={stats.get('required', 0)} evidenced={stats.get('evidenced', 0)}"
