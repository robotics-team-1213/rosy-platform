#!/usr/bin/env python3
"""Read-only release timing: PR head -> merge-queue SHA -> public main SHA -> artifact digest -> signature
-> R / cell / Pinky install -> accepted on site, with p50/p90 per stage over a window.

It only reads files that already exist; it never touches a host. Record locations (copy them from the
hosts, or point at a mount):
  --pr-events      JSON lines {pr, head_sha, queue_sha, main_sha, head_at, queue_at, main_at}, exported from GitHub
                   (PR head commit, merge_group run, merge commit). tools/pr_land.py queues the PR.
  --artifacts      JSON lines {source_commit, manifest_sha256, created_at}: the unsigned site candidate release
                   (build-site-candidate.yml; its release.json source_commit and manifest digest).
  --sign-audit     <state_dir>/audit.jsonl of deploy/site/auto_sign_candidates.py ("signed" rows: source_commit,
                   manifest_sha256, time; "refused"/"ci-red"/"error" rows are ignored here).
  --r-state        /var/lib/rosy/site-autoupdate.json (deploy/site/site_update_io.py Paths.state): installed/previous/
                   failed/hold. --r-journal: journal lines of rosy-site-autoupdate ("installed", "held",
                   "rolled-back" events with commit).
  --cell-state     NAME=<root>/state.json of deploy/robot/omx/omx_autoupdate.py (history[], release = sha[:12]);
                   --cell-journal NAME=file: its log() lines ("deferred" step = busy, "rolled_back").
  --robot-cd-audit <state_dir>/audit.jsonl of tools/release/robot_cd.py (sha, release_id, phase, result);
                   --rollout-evidence: <evidence-dir> with <date>/rollout.jsonl of publish_payload_release.py.
  --acceptance     JSON lines {target, sha, at}: a person's field acceptance. Health or canary-ok is not
                   acceptance, so an install without one is reported as unconfirmed-acceptance.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

SHA = re.compile(r"[0-9a-f]{40}")
STAGES = ("head->queue", "queue->main", "main->artifact", "artifact->signed", "signed->install", "install->accepted")


def ts(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def rows(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                yield json.loads(line)
            except ValueError:
                continue  # a torn last line from a live writer


def labelled(spec):
    name, _, path = spec.rpartition("=")
    return name or "cell", path


def percentile(values, q):
    """Nearest rank; shortcut: no interpolation, fine for tens of releases."""
    ordered = sorted(values)
    return ordered[max(0, -(-len(ordered) * q // 100) - 1)] if ordered else None


class Chain:
    def __init__(self):
        self.prs = defaultdict(list)       # main sha -> pr rows
        self.artifacts = defaultdict(list)
        self.signed = defaultdict(list)
        self.events = defaultdict(list)    # (target, sha) -> (kind, time)
        self.problems = []                 # (kind, text) with kind in duplicate / mismatch

    def event(self, target, sha, kind, at, release=None):
        self.events[(target, sha)].append((kind, ts(at)))


def load(args):
    c = Chain()
    for path in args.pr_events:
        for r in rows(path):
            c.prs[r["main_sha"]].append(r)
            if r.get("queue_sha") != r["main_sha"]:
                c.problems.append(("mismatch", f"PR #{r.get('pr')}: queue sha {r.get('queue_sha')} != main sha {r['main_sha']}"))
    for path in args.artifacts:
        for r in rows(path):
            c.artifacts[r["source_commit"]].append(r)
    for path in args.sign_audit:
        for r in rows(path):
            if r.get("decision") == "signed":
                c.signed[r["source_commit"]].append(r)
    shas = set(c.prs) | set(c.artifacts) | set(c.signed)

    def full(prefix):  # cell releases are named by sha[:12]
        hits = [s for s in shas if s.startswith(prefix)]
        return hits[0] if len(hits) == 1 else prefix

    if args.r_state:
        state = json.loads(Path(args.r_state).read_text(encoding="utf-8"))
        if state.get("installed", {}).get("commit"):
            c.event("R", state["installed"]["commit"], "installed", state["installed"].get("time"))
        if state.get("previous", {}) and state["previous"].get("commit"):
            c.event("R", state["previous"]["commit"], "installed", state["previous"].get("time"))
        for tag, f in state.get("failed", {}).items():
            c.event("R", full(tag.removeprefix("site-")), "rollback", f.get("time"))
        if state.get("hold"):
            for sha in state["hold"].get("until_contains") or []:
                c.event("R", sha, "held", state["hold"].get("time"))
    if args.r_journal:
        for r in rows(args.r_journal):
            sha = r.get("commit") or full(str(r.get("tag", "")).removeprefix("site-"))
            kind = {"installed": "installed", "rolled-back": "rollback", "held": "held"}.get(r.get("event"))
            if kind:
                c.event("R", sha, kind, r.get("time"))
    for spec in args.cell_state:
        name, path = labelled(spec)
        for h in json.loads(Path(path).read_text(encoding="utf-8")).get("history", []):
            c.event(f"cell:{name}", full(h["release"]), "installed" if h["result"] == "active" else "rollback", h["at"])
    for spec in args.cell_journal:
        name, path = labelled(spec)
        for r in rows(path):
            if r.get("step") == "deferred":
                c.event(f"cell:{name}", full(r["release"]), "busy", r["t"])
    if args.robot_cd_audit:
        release_sha = {}
        for r in rows(args.robot_cd_audit):
            if r.get("release_id") and r.get("sha"):
                release_sha[r["release_id"]] = r["sha"]
            kind = {"delivery_held": "held", "waiting_idle_canary": "busy", "canary_not_started": "busy"}.get(r.get("result"))
            if kind and r.get("sha"):
                c.event("pinky", r["sha"], kind, r["at"])
        for path in sorted(Path(args.rollout_evidence).glob("*/rollout.jsonl")) if args.rollout_evidence else []:
            for r in rows(path):
                sha = release_sha.get(r.get("release_id"))
                kind = {"canary-ok": "installed", "withdrawn": "rollback"}.get(r.get("event"))
                if sha and kind:
                    c.event("pinky", sha, kind, r["at"])
    for path in args.acceptance:
        for r in rows(path):
            c.event(r["target"], r["sha"], "accepted", r["at"])
    return c


def analyse(c, targets, since, until, assert_complete):
    stages = defaultdict(list)
    report = {"releases": [], "problems": [m for _, m in c.problems], "missing": [], "duplicate": [], "mismatch": [m for k, m in c.problems if k == "mismatch"]}
    report["problems"] = []
    for sha in sorted(set(c.prs) | set(c.artifacts) | set(c.signed)):
        prs = c.prs.get(sha, [])
        main_at = ts(prs[0].get("main_at")) if prs else None
        if (since and main_at is not None and main_at < since) or (until and main_at is not None and main_at > until):
            continue
        shipped = bool(c.artifacts.get(sha) or c.signed.get(sha))
        row = {"sha": sha, "pr": prs[0].get("pr") if prs else None, "targets": {}}
        if not prs:
            report["missing"].append(f"{sha[:12]}: artifact/signature without a PR/queue/main record")
        if len(prs) > 1:
            report["duplicate"].append(f"{sha[:12]}: {len(prs)} PR rows")
        if prs:
            p = prs[0]
            if ts(p.get("queue_at")) is not None and ts(p.get("head_at")) is not None:
                stages["head->queue"].append(ts(p["queue_at"]) - ts(p["head_at"]))
            if main_at is not None and ts(p.get("queue_at")) is not None:
                stages["queue->main"].append(main_at - ts(p["queue_at"]))
        if not shipped:
            row["state"] = "not-shipped"  # a main commit with no artifact: not every merge ships
            report["releases"].append(row)
            continue
        arts, sigs = c.artifacts.get(sha, []), c.signed.get(sha, [])
        if len(arts) > 1:
            report["duplicate"].append(f"{sha[:12]}: {len(arts)} artifacts")
        if len(sigs) > 1:
            report["duplicate"].append(f"{sha[:12]}: {len(sigs)} signatures")
        if not arts:
            report["missing"].append(f"{sha[:12]}: no artifact record")
        if not sigs:
            report["missing"].append(f"{sha[:12]}: no signing audit")
        if arts and sigs and arts[0].get("manifest_sha256") != sigs[0].get("manifest_sha256"):
            report["mismatch"].append(f"{sha[:12]}: artifact digest differs from the signed digest")
        built, signed = (ts(arts[0].get("created_at")) if arts else None), (ts(sigs[0].get("time")) if sigs else None)
        if built is not None and main_at is not None:
            stages["main->artifact"].append(built - main_at)
        if built is not None and signed is not None:
            stages["artifact->signed"].append(signed - built)
        for target in targets:
            ev = sorted((t, k) for k, t in c.events.get((target, sha), []) if t is not None)
            installs = [t for t, k in ev if k == "installed"]
            accepts = [t for t, k in ev if k == "accepted"]
            if len(installs) > 1:
                report["duplicate"].append(f"{sha[:12]} {target}: {len(installs)} installs")
            last = next((k for t, k in reversed(ev) if k in ("installed", "rollback", "held", "busy")), None)
            if last is None:
                state = "missing"
                report["missing"].append(f"{sha[:12]} {target}: no install/hold/busy/rollback record")
            elif last == "installed":
                state = "accepted" if accepts else "unconfirmed-acceptance"
                if signed is not None:
                    stages["signed->install"].append(installs[-1] - signed)
                if accepts:
                    stages["install->accepted"].append(accepts[0] - installs[-1])
            else:
                state = last
            row["targets"][target] = state
        report["releases"].append(row)
    report["stages"] = {s: {"n": len(stages[s]), "p50": percentile(stages[s], 50), "p90": percentile(stages[s], 90)} for s in STAGES}
    report["problems"] = report["missing"] + report["duplicate"] + report["mismatch"]
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--pr-events", action="append", default=[])
    p.add_argument("--artifacts", action="append", default=[])
    p.add_argument("--sign-audit", action="append", default=[])
    p.add_argument("--r-state")
    p.add_argument("--r-journal")
    p.add_argument("--cell-state", action="append", default=[], metavar="NAME=PATH")
    p.add_argument("--cell-journal", action="append", default=[], metavar="NAME=PATH")
    p.add_argument("--robot-cd-audit")
    p.add_argument("--rollout-evidence")
    p.add_argument("--acceptance", action="append", default=[])
    p.add_argument("--since", help="ISO time; window on the main merge time")
    p.add_argument("--until")
    p.add_argument("--json", action="store_true")
    p.add_argument("--assert-complete", action="store_true", help="exit 1 on missing, duplicate or SHA-mismatch links")
    args = p.parse_args(argv)
    c = load(args)
    targets = (["R"] if args.r_state or args.r_journal else []) + [f"cell:{labelled(s)[0]}" for s in args.cell_state] \
        + (["pinky"] if args.robot_cd_audit else [])
    report = analyse(c, targets, ts(args.since), ts(args.until), args.assert_complete)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for s, v in report["stages"].items():
            fmt = lambda x: "-" if x is None else f"{x / 60:.1f}m"
            print(f"{s:20} n={v['n']:<3} p50={fmt(v['p50'])} p90={fmt(v['p90'])}")
        for r in report["releases"]:
            print(r["sha"][:12], f"PR#{r['pr']}", r.get("state") or " ".join(f"{t}={s}" for t, s in r["targets"].items()))
        for line in report["problems"]:
            print("PROBLEM", line)
    return 1 if args.assert_complete and report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
