"""D-430 §5: commits that touch safety-tagged paths carry a ``Safety-Review:`` trailer.

Usage: python tools/harness/safety_review.py BASE HEAD [--warn-only]

Checks the commits in BASE..HEAD, minus ancestors of BASELINE (history from
before this check landed) and the reviewed ``EXEMPT`` list. CI passes exactly the
event's range: the PR base for ``pull_request``, ``before`` for ``push``. When
BASE is empty, all zeros (a new branch) or unreachable (a force push), only
HEAD itself is checked (HEAD^..HEAD), never the whole history, so one old
untrailered commit cannot keep CI red. Needs full history (``fetch-depth: 0``).

What is safety-tagged comes from ``tools/harness/platform_parts.yaml``: files under
a ``concern: safety`` root (deepest root wins) and the ``safety_modules`` list. A
path counts when the manifest at HEAD, at BASE, at the commit, or at its parent
tags it, so a branch forked before a path was tagged is still checked. A commit needs the
trailer when it

- changes such a path (a ``git mv`` changes both the old and the new path, so wave
  3/4 moves of safety roots or modules need the trailer), or
- stops tagging a root, module or ``safety_anchors`` entry that its parent tagged.

A non-merge commit is checked on its diff to its parent. A merge is checked only
on the paths it changes against every parent (``diff-tree --cc``: conflict
resolutions and evil-merge edits); what it brings in is checked on the merged
commits themselves.

``--warn-only`` prints the same report and exits 0; ``tools/hooks/pre-push`` uses it
as an opt-in early warning. The CI step is the enforcement.
"""

from __future__ import annotations

import re
import subprocess
import sys

import yaml

#: main when this check landed (D-430 wave 0). Its ancestors are never checked.
BASELINE = "46b8720c297db5729297de4442051a0265f097ea"  # git commit revision
#: Reviewed historical commits after BASELINE that touch safety paths without a
#: trailer, as full SHA -> reason. Add only with an independent review.
EXEMPT: dict[str, str] = {
    "f8165b2a44d01ff628d5bd75ec923953bd09d000":  # git commit revision
        "Independently reviewed by Codex /root on 2026-10-05: D-463 retains existing "
        "operator policy/idempotency and goal authority, including legacy compatibility; fresh LOCALIZED finite map "
        "pose and lane band precede the short next point. Source review and 11 host "
        "route tests; no device acceptance. See docs/validation/"
        "d463-route-independent-review-2026-10-05/README.md. Also independently reviewed "
        "by the OpenCode GLM session on 2026-10-05: route uses the existing goal path; "
        "non-LOCALIZED pose is refused and cancel/stop generation stays untouched.",
    "7e34baacebc02dd6103dbdd17c5e861b92a02945":  # git commit revision
        "Independently reviewed by Codex /root/pilot_review on 2026-10-04: D-432 "
        "device TXT metadata, bounded opt-in admission, verified TLS and key-only SSH; "
        "moved firmware preserves handlers/interlocks. See docs/validation/"
        "ui-release-integration-2026-10-04/README.md.",
    "a4caeed0f5119df17f138203cd6e01eb373da671":  # git commit revision
        "Independently reviewed by Codex /root/pilot_review on 2026-10-04: D-447 "
        "validated fresh bound heartbeat reuse, monotonic age and stale/offline REST fallback; "
        "dispatch/traffic and CORE command ownership unchanged. See docs/validation/"
        "ui-release-integration-2026-10-04/README.md.",
    "a075a0bba2bec616c12dc2c99a6987c3764ae055":  # git commit revision
        "Independent security-reviewer agent, 2026-10-06: only drops memory points within "
        "1e-6 m of range_min (float rounding, below LiDAR resolution); D-422 blind-gap lower "
        "bound still applies, no-echo never clears, memory only shortens gaps; repro test "
        "fails pre-fix, C1/0.12 post latch tests pass (56/56, 463 filtered).",
    "c8eb84a769798065169dee920f37f29feea96f1f":  # git commit revision
        "Independent security-reviewer agent, 2026-10-07: console.py adds a default-false trip_busy hook "
        "and refuses goal (unless trip=True) and formation_start with TRIP_ROBOT_BUSY for a robot on a "
        "running trip; task_dispatch_routes.py refuses /goal before a task is queued and the dispatch "
        "loop skips trip robots. Only refusals were added: estop_all, cancel, cancel-all, formation stop,"
        " D-421/D-430 latches and auth are unchanged, and no stop path is wrapped. 273 host tests pass at"
        " branch head 2dbb81946 (trip_runner, server_console, site_map_trip, cancel_all, lane_route, "
        "line_stuck_api, stuck_resolver_loop, dispatch_admission, dispatch_stop_latch, server_formation, "
        "server_traffic); probes confirm estop/cancel/cancel-all reach a trip robot; no device "
        "acceptance.",
    "7b2146db26853544a3d59204488517e85a6fc4b6":  # git commit revision
        "Independent security-reviewer agent, 2026-10-07: console.py and task_dispatch_routes.py inline "
        "the same TRIP_ROBOT_BUSY refusals (set_trip_busy/refuse_trip_robot replaced by a trip_busy "
        "attribute and one guard per site); behaviour is the same as c8eb84a76 and only adds refusals. No"
        " stop, E-stop, cancel, traffic, auth or trust path changed; 273 host tests pass at branch head; "
        "no device acceptance.",
    "77a86a2775be6ac5e06d4119019a6111ed4ad593":  # git commit revision
        "Independent security-reviewer agent, 2026-10-07: console.py net -2 lines: the TRIP_ROBOT_BUSY "
        "checks move to trip_guard.py, which wraps goal/formation_start/line_follow_mode on the instance "
        "(line_follow_mode OFF is always forwarded and also cancels the trip); FleetConsole inherits "
        "TripAware (trip_busy defaults to False); _make_room gives a trip robot no yield bay and it is "
        "never a degraded-capability reassignment candidate. estop_all, cancel, cancel-all and latches "
        "are unwrapped and unchanged; the trip runner's own cancel_goal is the pre-guard bound method (no"
        " recursion). 6773eb6b0 then wraps cancel and estop_all so every operator stop also ends the trip"
        " after the stop is sent (re-reviewed 2026-10-07). 287 host tests pass; no device acceptance.",
}
MANIFEST = "tools/harness/platform_parts.yaml"
TRAILER = re.compile(r"^Safety-Review:[ \t]*\S", re.MULTILINE)
ZERO = re.compile(r"^0*$")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def _exists(commit: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", commit + "^{commit}"], capture_output=True).returncode == 0


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _manifest(commit: str) -> dict:
    """Manifest at ``commit``; empty before it existed."""
    try:
        return yaml.safe_load(_git("show", f"{commit}:{MANIFEST}")) or {}
    except subprocess.CalledProcessError:
        return {}


def is_safety(path: str, roots: list[dict], modules: set[str]) -> bool:
    if path in modules:
        return True
    owner = max((root for root in roots if _under(path, root["path"])),
                key=lambda root: len(root["path"]), default=None)
    return owner is not None and owner.get("concern") == "safety"


def _is_safety_in(path: str, manifest: dict) -> bool:
    return is_safety(path, manifest.get("roots") or [], set(manifest.get("safety_modules") or ()))


def tagged(manifest: dict) -> set[str]:
    """Every safety tag: roots, modules and anchors (removing any is a safety change)."""
    anchors = {f"anchor:{anchor.get('symbol') or anchor.get('in', '') + '.' + anchor.get('string', '')}"
               for anchor in manifest.get("safety_anchors") or ()}
    return ({f"root:{root['path']}" for root in manifest.get("roots") or () if root.get("concern") == "safety"}
            | {f"module:{path}" for path in manifest.get("safety_modules") or ()} | anchors)


def _parents(commit: str) -> list[str]:
    return _git("rev-list", "--parents", "-n", "1", commit).split()[1:]


def needs_review(commit: str, range_manifests: tuple[dict, ...]) -> list[str]:
    """Why ``commit`` needs a trailer (empty when it does not)."""
    parents = _parents(commit)
    if len(parents) > 1:
        changed = _git("diff-tree", "--cc", "--no-commit-id", "--name-only", commit).split()
    else:
        changed = _git("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "--root", commit).split()
    own = _manifest(commit)
    parent_manifests = [_manifest(parent) for parent in parents]
    manifests = (*range_manifests, own, *parent_manifests[:1])
    reasons = [f"touches {path}" for path in changed if any(_is_safety_in(path, m) for m in manifests)]
    # A merge untags only what every parent tagged; a branch's own removal is
    # reported on that branch's commit.
    kept = set.intersection(*(tagged(m) for m in parent_manifests)) if parent_manifests else set()
    reasons += [f"untags {entry}" for entry in sorted(kept - tagged(own))]
    return reasons


def resolve_base(base: str, head: str) -> str:
    if not base or ZERO.match(base) or not _exists(base):
        return f"{head}^"  # new branch or force push: the pushed tip only
    return base


def commits(base: str, head: str) -> list[str]:
    return [commit for commit in _git("rev-list", "--reverse", head, "^" + base, "^" + BASELINE).split()
            if commit not in EXEMPT]


def main(argv: list[str]) -> int:
    warn_only = "--warn-only" in argv
    args = [arg for arg in argv if arg != "--warn-only"]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    base, head = args
    if not _exists(BASELINE):
        print(f"[safety-review] baseline {BASELINE} is not in this clone; fetch full history "
              "(actions/checkout fetch-depth: 0)", file=sys.stderr)
        return 0 if warn_only else 1
    base = resolve_base(base, head)
    range_manifests = (_manifest(head), _manifest(base))
    missing = []
    checked = commits(base, head)
    for commit in checked:
        reasons = needs_review(commit, range_manifests)
        if reasons and not TRAILER.search(_git("log", "-1", "--format=%B", commit)):
            subject = _git("log", "-1", "--format=%h %s", commit).strip()
            missing.append(f"{subject}\n    " + "\n    ".join(reasons))
    print(f"[safety-review] {len(checked)} commit(s) checked after baseline {BASELINE[:9]}")
    if not missing:
        return 0
    print("[safety-review] safety-tagged changes without a `Safety-Review: <reviewer/lane> <evidence>` "
          "trailer (D-430 section 5):\n" + "\n".join(missing), file=sys.stderr)
    return 0 if warn_only else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
