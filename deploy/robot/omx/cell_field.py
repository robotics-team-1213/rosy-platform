#!/usr/bin/env python3
"""Field operations for arm S as one tool, so a trial on the real cell is a command and leaves the same evidence every
time: frames before and after, the attempt rows it produced, a side-by-side picture and a JSON report under
work_dir/field/ (2026-10-29: every one of these was done by hand over ssh, and a hand-sequenced place retreated after
a strain and the guard dropped the arm).

Motion goes only through the cell's own programs (cell_auto_pick, cell_push, cell_pipeline.recover), which carry the
recovery rules; this tool sequences, waits, collects and ranks. It runs on the arm's host while a chunk session is up.

  cell_field.py --config C --catalog K snapshot NAME
  cell_field.py --config C --catalog K carry --from floor --dest pinky [--roi x0 y0 x1 y1] [--dry-run]
  cell_field.py --config C --catalog K push-search --site floor --px 228,358 --away 1,1 [--radius 12 --step 6] [--top 5]
  cell_field.py --config C --catalog K push --site floor --px 228,358 --away 1,1
  cell_field.py --config C --catalog K marks --library L --commissioning --person-at-switch [--goto "goto above_pick"]
  cell_field.py --config C --catalog K recover --site floor --person-at-switch
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 2), (2, 1), (-1, 2), (-2, 1)]


def rank_pushes(candidates: list, away) -> list:
    """Clear push candidates, best first: a direction pointing away from the neighbour (`away`, image px), then the
    shorter push (less to go wrong). Each candidate: {px, dir, half_mm, mm, blocked}."""
    ax, ay = away
    na = math.hypot(ax, ay) or 1.0

    def score(c):
        dx, dy = c["dir"]
        return -((dx * ax + dy * ay) / ((math.hypot(dx, dy) or 1.0) * na)), c["mm"]
    clear = [c for c in candidates if not c["blocked"]]
    return sorted(clear, key=score)


def summarize(rows: list) -> list:
    """The attempt rows of one carry, short: outcome, where it stopped, the looks and the steps that mattered."""
    out = []
    for r in rows:
        moved = r.get("transfer") or {}
        wrist = r.get("wrist") if isinstance(r.get("wrist"), dict) else {}
        steps = [{"command": s.get("command", "")[:20], **{k: s[k] for k in ("verdict", "holding", "contact") if s.get(k) is not None}}
                 for s in moved.get("steps", []) if any(k in s.get("command", "") for k in ("wrist", "descend", "grasp", "release", "lift"))]
        out.append({"attempt_id": r.get("attempt_id"), "from": r.get("from"), "to": r.get("to"), "outcome": r.get("outcome"),
                    "result": moved.get("result"), "at": moved.get("at"), "why": r.get("fail_class"),
                    "pick": (r.get("plan") or {}).get("pick"), "placed_seen": (r.get("verify") or {}).get("inside"),
                    "looks": [l.get("box_minus_tcp_mm") for l in wrist.get("looks", [])], "steps": steps})
    return out


def side_by_side(before, after, labels=("before", "after"), gain: float | None = None):
    """One picture of two frames; a dark scene is brightened so a person can see it (the stored frames are not)."""
    import cv2
    import numpy as np

    frames = []
    for img, text in zip((before, after), labels):
        if gain is None:
            mean = float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean())
            g = min(3.0, max(1.0, 110.0 / max(mean, 1.0)))
        else:
            g = gain
        shown = np.clip(img.astype(np.float32) * g, 0, 255).astype(np.uint8)
        cv2.putText(shown, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        frames.append(shown)
    return np.hstack(frames)


class Field:
    def __init__(self, config_path: Path, catalog: Path):
        import cell_pipeline as cp

        self.config_path, self.catalog = config_path, catalog
        self.config = json.loads(config_path.read_text())
        self.config.pop("_operating_profile_binding", None)
        if self.config.get("operating_profile_path"):
            from cell_robot_profile import bind_pipeline

            self.config = bind_pipeline(self.config)
        self.cell = cp.FifoCell(Path(self.config["io"]).expanduser(), self.config["cameras"],
                                operating_profile=self.config.get("_operating_profile_binding"))
        self.work = Path(self.config["work_dir"]).expanduser()
        self.dir = self.work / "field"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stamp = time.strftime("%Y%m%d-%H%M%S")

    def snapshot(self, name: str):
        import cv2

        img = self.cell.frame("top")
        path = self.dir / f"{self.stamp}-{name}.jpg"
        cv2.imwrite(str(path), img)
        return img, path

    def run(self, script: str, args: list) -> tuple:
        proc = subprocess.run([sys.executable, str(HERE / script), *map(str, args)], capture_output=True, text=True)
        text = proc.stdout
        start = text.find("{")
        try:
            return proc.returncode, json.loads(text[start:]) if start >= 0 else {}, proc.stderr[-400:]
        except ValueError:
            return proc.returncode, {"raw": text[-400:]}, proc.stderr[-400:]

    def report(self, kind: str, body: dict, before=None, after=None) -> dict:
        import cv2

        body = {"kind": kind, "stamp": self.stamp, **body}
        if before is not None and after is not None:
            picture = self.dir / f"{self.stamp}-{kind}.jpg"
            cv2.imwrite(str(picture), side_by_side(before, after))
            body["picture"] = str(picture)
        (self.dir / f"{self.stamp}-{kind}.json").write_text(json.dumps(body, indent=1, default=str))
        return body

    def attempts_since(self, t0: float) -> list:
        path = self.work / "attempts.jsonl"
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        return [r for r in rows if (r.get("t_start") or 0) >= t0 - 1]

    def carry(self, source: str, dest: str, roi, dry_run: bool) -> dict:
        site = self.config["sites"][source]
        roi = roi or site.get("auto_roi")
        before, _ = self.snapshot(f"carry-{source}-before")
        t0 = time.time()
        args = ["--config", self.config_path, "--catalog", self.catalog,
                "--roi", *roi, "--from", source, "--dest", dest] + (["--dry-run"] if dry_run else [])
        code, result, err = self.run("cell_auto_pick.py", args)
        after, _ = self.snapshot(f"carry-{source}-after")
        return self.report("carry", {"from": source, "to": dest, "exit": code, "result": result.get("result"),
                                     "stderr": err if code not in (0, 1) else "", "attempts": summarize(self.attempts_since(t0))},
                           before, after)

    def push_search(self, site: str, px, away, radius: int, step: int, top: int, roi=None) -> list:
        roi = roi or self.config["sites"][site].get("auto_roi")
        candidates = []
        for ox in range(-radius, radius + 1, step):
            for oy in range(-radius, radius + 1, step):
                p = (px[0] + ox, px[1] + oy)
                for d in DIRS:
                    for half, mm in ((15, 15), (15, 25), (30, 15), (30, 25)):
                        _, out, _ = self.run("cell_push.py", ["--config", self.config_path, "--site", site, "--roi", *roi,
                                                              f"--px={p[0]},{p[1]}", f"--dir={d[0]},{d[1]}", "--mm", mm,
                                                              "--half-mm", half, "--dry-run"])
                        candidates.append({"px": p, "dir": d, "half_mm": half, "mm": mm, "blocked": out.get("blocked", ["no plan"])})
        return rank_pushes(candidates, away)[:top]

    def push(self, site: str, px, away, roi=None) -> dict:
        best = self.push_search(site, px, away, 12, 6, 1, roi)
        if not best:
            return self.report("push", {"site": site, "result": "no clear push"})
        c = best[0]
        before, _ = self.snapshot(f"push-{site}-before")
        roi = roi or self.config["sites"][site].get("auto_roi")
        code, out, err = self.run("cell_push.py", ["--config", self.config_path, "--site", site, "--roi", *roi,
                                                   f"--px={c['px'][0]},{c['px'][1]}", f"--dir={c['dir'][0]},{c['dir'][1]}",
                                                   "--mm", c["mm"], "--half-mm", c["half_mm"],
                                                   "--catalog", self.catalog])
        after, _ = self.snapshot(f"push-{site}-after")
        return self.report("push", {"site": site, "chosen": c, "exit": code, "result": out.get("result"), "look": out.get("look"),
                                    "after_objects": out.get("after"), "stderr": err if code not in (0, 1) else ""}, before, after)

    def marks(self, library: str, goto: str, *, commissioning=False, person_at_switch=False) -> dict:
        if self.cell.operating_profile is None:
            return self.report("marks", {"result": "held: select a per-device operating profile"})
        if not (commissioning is True and person_at_switch is True):
            return self.report("marks", {"result": "held: supervised commissioning required"})
        import cv2

        import cell_params as prm
        import cell_pipeline as cp
        import cell_pivot

        params = prm.load(self.config.get("params_path"))["values"]
        rows = []
        try:
            for c in (f"load {library}", goto):
                if not self.cell.act(c).get("ok"):
                    return self.report("marks", {"result": f"refused at {c}"})
            for k in range(3):
                if not cp.grip_to(self.cell, self.config.get("jaw_mark", {}).get("closed", prm.get(params, "pivot.grip_closed"))):
                    return self.report("marks", {"result": "refused at grip closed"})
                closed = cell_pivot.settled_frame(self.cell, params=params)
                if not cp.grip_to(self.cell, prm.get(params, "pivot.grip_open", 62.0)):
                    return self.report("marks", {"result": "refused at grip open"})
                opened = cell_pivot.settled_frame(self.cell, params=params)
                blobs = cell_pivot.jaw_blobs(closed, opened, params)
                cv2.imwrite(str(self.dir / f"{self.stamp}-marks-{k}.jpg"), side_by_side(closed, opened, ("closed", "open"), 1.0))
                rows.append([(round(b[0]), round(b[1]), b[2]) for b in blobs])
        finally:
            self.cell.act("park")
        return self.report("marks", {"library": library, "goto": goto, "blobs": rows})

    def recover(self, site: str, person_at_switch: bool) -> dict:
        import cell_pipeline as cp

        config = dict(self.config, plan=json.loads(Path(self.config["plan_path"]).expanduser().read_text()))
        before, _ = self.snapshot("recover-before")
        out = cp.recover(self.cell, config, site, self.dir, person_at_switch)
        after, _ = self.snapshot("recover-after")
        return self.report("recover", out, before, after)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--catalog", required=True, type=Path)
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("snapshot").add_argument("name")
    c = sub.add_parser("carry")
    c.add_argument("--from", dest="source", required=True)
    c.add_argument("--dest", required=True)
    c.add_argument("--roi", type=int, nargs=4)
    c.add_argument("--dry-run", action="store_true")
    for verb in ("push-search", "push"):
        p = sub.add_parser(verb)
        p.add_argument("--site", required=True)
        p.add_argument("--px", required=True, help="x,y top-camera pixel on the object to push")
        p.add_argument("--away", required=True, help="dx,dy image direction away from the neighbour")
        p.add_argument("--roi", type=int, nargs=4)
        if verb == "push-search":
            p.add_argument("--radius", type=int, default=12)
            p.add_argument("--step", type=int, default=6)
            p.add_argument("--top", type=int, default=5)
    m = sub.add_parser("marks")
    m.add_argument("--library", required=True)
    m.add_argument("--goto", default="goto above_pick")
    m.add_argument("--commissioning", action="store_true")
    m.add_argument("--person-at-switch", action="store_true")
    r = sub.add_parser("recover")
    r.add_argument("--site", required=True)
    r.add_argument("--person-at-switch", action="store_true")
    args = ap.parse_args(argv)
    if args.verb == "marks" and not (args.commissioning and args.person_at_switch):
        ap.error("marks requires supervised --commissioning --person-at-switch")
    field = Field(args.config, args.catalog)
    xy = lambda s: tuple(int(v) for v in s.split(","))  # noqa: E731
    if args.verb == "snapshot":
        out = {"picture": str(field.snapshot(args.name)[1])}
    elif args.verb == "carry":
        out = field.carry(args.source, args.dest, args.roi, args.dry_run)
    elif args.verb == "push-search":
        out = {"candidates": field.push_search(args.site, xy(args.px), xy(args.away), args.radius, args.step, args.top, args.roi)}
    elif args.verb == "push":
        out = field.push(args.site, xy(args.px), xy(args.away), args.roi)
    elif args.verb == "marks":
        out = field.marks(args.library, args.goto, commissioning=args.commissioning,
                          person_at_switch=args.person_at_switch)
    else:
        out = field.recover(args.site, args.person_at_switch)
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
