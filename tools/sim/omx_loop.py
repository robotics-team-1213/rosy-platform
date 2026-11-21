#!/usr/bin/env python3
"""One driver for an OMX real-to-sim / sim-to-real loop iteration. It only calls the existing tools as subprocess CLIs; it never
moves an arm, never opens ssh to a cell host (the real attempt stays a person-supervised step, D-911, from landed main, D-932).

  omx_loop.py STAGE --run-dir RUN [--preset P] [--run]          default: print the commands (plan), write nothing
stages, in loop order (each writes RUN/<n>-<stage>/manifest.json with inputs+digests, commands, outputs, code sha):
  r2s     --capture DIR [--prev SNAP] [--twin D] [--dr-next F]   copy the capture, measure, diff against --prev
  rank    --sweep DIR [--run-sweep] [--snapshot SNAP]            (sim), (sweep run), rank; same --preset/--choice everywhere
  offer   --sweep DIR --store FILE [--site-store]                offers --merge into FILE; the live site store needs --site-store
  ingest  --sweep DIR --attempts F --cell C [--episodes ROOT]    attempt-episode join, then ingest (tier-proof verdicts)
  gate    --sweep DIR --fit F --candidate N --base-stack F --stack F --grasp F   omx_sysid task --real real_outcomes.jsonl (needs physics-tagged rows)
  twin    --cell C [--twin-host ai|model] [--local-twin]         omx_twin replay + report on a remote_sim host (episodes ship on a WIP commit); --cell is a path on that host
  all     r2s -> rank -> offer, and with --attempts also ingest -> gate (only with --fit) -> twin -> r2s again (twin + dr_next fed in)
Shortcuts: `omx_twin batch` reads episodes over ssh from the site PC, so the twin stage replays the joined local episodes instead;
`capture` (ssh to the site PC) is not a stage, pass an existing capture folder. The live store is told by its path (work/choices.json).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from omx_real2sim_stage import stage_files  # noqa: E402

_REAL_STAGE_FILES = stage_files
PRESET = "v24-20261114-cad194"  # physical cell: switch to cad190 only after the v25 docks are printed and the plates are moved (DL-52)
R2S, SWEEP, TWIN = "tools/sim/omx_real2sim.py", "tools/sim/omx_carry_sweep.py", "tools/sim/omx_twin.py"
SYSID = "tools/sim/omx_sysid.py"
JOIN = "deploy/robot/omx/cell_attempt_episodes.py"
REMOTE_SIM, TWIN_HOSTS, EP_PREFIX = "tools/remote/remote_sim.py", ("ai", "model"), "deploy/robot/omx/sim/twin_episodes/"
ALLOWED = {REMOTE_SIM: {"--host"}, R2S: {"measure", "diff", "sim"}, SWEEP: {"run", "rank", "offers", "ingest"}, TWIN: {"replay", "report"}, SYSID: {"task"}, JOIN: None}


class Refused(SystemExit):
    pass


def guard(argv) -> None:
    """Every command is one of the allowed tool CLIs with an allowed subcommand: no ssh/scp, no arm, no capture/batch/live."""
    tokens = [str(t) for t in argv]
    if any(Path(t).name.lower().removesuffix(".exe") in ("ssh", "scp", "sftp", "adb") for t in tokens):
        raise Refused(f"refused: {tokens[:3]} would reach a host")
    script = tokens[1].replace("\\", "/") if len(tokens) > 1 else ""
    script = script.removeprefix(str(ROOT).replace("\\", "/") + "/")
    if script == REMOTE_SIM and (tokens[3:4] != [] and tokens[3] not in TWIN_HOSTS or "--sha" not in tokens):  # sim hosts by role only, never a cell or site host
        raise Refused(f"refused: remote_sim host {tokens[3:4]} is not one of {TWIN_HOSTS}")
    subs = ALLOWED.get(script, "nope")
    if subs == "nope" or (subs is not None and (len(tokens) < 3 or tokens[2] not in subs)):
        raise Refused(f"refused: {' '.join(tokens[1:3])} is not a loop command (no arm, no ssh, no capture/batch/live)")


def digest(path) -> str | None:
    p = Path(path)
    if p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    if p.is_dir():
        h = hashlib.sha256()
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            h.update(f.relative_to(p).as_posix().encode() + f.read_bytes())
        return h.hexdigest()[:16]
    return None


def code_sha() -> str:
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return git("rev-parse", "HEAD") + ("+dirty" if git("status", "--porcelain", "--", "tools", "deploy") else "")


def is_live_store(path: Path) -> bool:
    live = os.environ.get("ROSY_SITE_STORE")
    return path.name == "choices.json" and (path.resolve().parent.name == "work" or bool(live and path.resolve() == Path(live).resolve()))


class Loop:
    def __init__(self, a, runner=None):
        self.a, self.runner, self.n = a, runner or self.subprocess_runner, 0
        self.run_dir, self.py, self.sha = Path(a.run_dir), a.python, None
        # a stub runner never reaches a real git repo: stage only for real unless stage_files was swapped in on purpose
        self.stubbed = runner is not None and stage_files is _REAL_STAGE_FILES
        self.stage_files = (lambda *_: "<wip sha>") if self.stubbed else stage_files

    @staticmethod
    def subprocess_runner(argv):
        r = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE, text=True, encoding="utf-8")
        return r.returncode, r.stdout

    def tool(self, script, *args):
        missing = ROOT / script
        if not missing.exists():
            raise SystemExit(f"{script} is not on this branch (it lives on fix/omx-tier-measured-proof-v5); land both branches first, nothing was faked")
        return [self.py, script, *map(str, args)]

    def stage(self, name, inputs, steps, outputs, copy=(), after=None):
        """steps: [(argv, stdout_file|None)] or callables returning that list at run time (they read earlier steps' files)."""
        self.n += 1
        d = self.run_dir / f"{self.n:02d}-{name}"
        steps = steps(d) if callable(steps) else steps
        if not self.a.run:
            print(f"## {d.name}")
            for src, dst in copy:
                print(f"  copy {src} -> {dst}")
            for argv, out in [x for st in steps for x in (st() if callable(st) else [st])]:
                guard(argv)
                print("  " + " ".join(map(str, argv)) + (f" > {out}" if out else ""))
            return d
        d.mkdir(parents=True, exist_ok=True)
        self.sha = self.sha or code_sha()
        import shutil
        for src, dst in copy:
            shutil.copytree(src, dst, dirs_exist_ok=True)
        ran = []
        for step in steps:
            for argv, out in (step() if callable(step) else [step]):
                guard(argv)
                rc, text = self.runner(argv)
                if out:
                    Path(out).parent.mkdir(parents=True, exist_ok=True)
                    Path(out).write_text(text or "", encoding="utf-8")
                ran.append(dict(argv=[str(t) for t in argv], rc=rc, stdout=str(out) if out else None))
                if rc:
                    self.manifest(d, name, inputs, ran, outputs)
                    raise SystemExit(f"stage {name} stopped: {' '.join(map(str, argv[1:3]))} returned {rc} (see {d / 'manifest.json'})")
        if after:
            after()
        self.manifest(d, name, inputs, ran, outputs)
        return d

    def manifest(self, d, name, inputs, ran, outputs):
        doc = dict(stage=name, preset=self.a.preset, at=time.strftime("%Y-%m-%dT%H:%M:%S"), code_sha=self.sha, python=self.py,
                   inputs=[dict(path=str(p), sha256=digest(p)) for p in inputs],
                   commands=ran, outputs=[dict(path=str(p), sha256=digest(p)) for p in outputs])
        (d / "manifest.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")

    # -- stages -------------------------------------------------------------------------------------------------------------
    def r2s(self, twin=None, dr_next=None, prev=None):
        a = self.a
        prev = prev or a.prev
        d0 = self.run_dir / f"{self.n + 1:02d}-r2s"
        cap, snap = d0 / "capture", d0 / "capture" / "snapshot.json"
        opts = [*(["--twin", twin] if twin else []), *(["--dr-next", dr_next] if dr_next else [])]
        m = self.tool(R2S, "measure", cap, *(["--prev", prev] if prev and not a.fresh else []), "--preset", a.preset, *opts,
                      *(["--camera-moved-ok"] if a.camera_moved_ok else []))
        steps = [(m, d0 / "measure.json")] + ([(self.tool(R2S, "diff", prev, snap, "--preset", a.preset, *opts), d0 / "diff.json")] if prev else [])
        return self.stage("r2s", [a.capture, *([prev] if prev else []), *[x for x in (twin, dr_next) if x]], steps, [snap, d0 / "diff.json"],
                          copy=[(a.capture, cap)]), snap

    def rank(self, measured_snapshot=None):
        a = self.a
        d0 = self.run_dir / f"{self.n + 1:02d}-rank"
        choices = [f"preset={a.preset}", *a.choice]
        flags = [x for c in choices for x in ("--choice", c)]
        snapshot = measured_snapshot or a.snapshot
        bound = ["--snapshot", snapshot] if snapshot else []
        steps = []
        if a.snapshot and measured_snapshot is None:
            steps.append((self.tool(R2S, "sim", a.snapshot, "--sha", self.sha or code_sha(), "--out", d0 / "sim", "--preset", a.preset,
                                    *[x for c in a.choice for x in ("--choice", c)]), d0 / "sim.json"))
        if a.run_sweep:
            steps.append((self.tool(SWEEP, "run", "--out", a.sweep, *flags, *bound, *(["--dr", a.dr_next] if a.dr_next else [])), d0 / "sweep.txt"))
        steps.append((self.tool(SWEEP, "rank", a.sweep, *bound), d0 / "rank.md"))
        return self.stage("rank", [x for x in (snapshot, a.dr_next) if x] + ([] if a.run_sweep else [a.sweep]), steps, [a.sweep])

    def offer(self, measured_snapshot=None):
        a = self.a
        store = Path(a.store)
        if is_live_store(store) and not a.site_store:
            raise Refused(f"refused: {store} is the live site choices store; pass --site-store to write an offer there on purpose")
        snapshot = measured_snapshot or a.snapshot
        bound = ["--snapshot", snapshot] if snapshot else []
        step = self.tool(SWEEP, "offers", a.sweep, "--preset", a.preset, *bound, "--merge", store)
        return self.stage("offer", [a.sweep, *([snapshot] if snapshot else [])], [(step, None)], [store])

    def ingest(self, join_only=False):
        """join_only (the twin stage): make joined.json and stop; the sweep is not needed and not touched."""
        a = self.a
        d0 = self.run_dir / f"{self.n + 1:02d}-ingest"
        joined = d0 / "joined.json"

        def after_join():
            paths = [e["episode"]["path"] for e in json.loads(joined.read_text(encoding="utf-8")).get("joined", []) if e["status"] == "ok"]
            return [(self.tool(SWEEP, "ingest", a.sweep, "--attempts", a.attempts, *(["--stack-check", a.stack_check] if a.stack_check else []),
                               *(["--episodes", *paths] if paths else []), *(["--cell", a.cell] if a.cell and paths else [])), d0 / "ingest.out")]
        join = self.tool(JOIN, a.attempts, *(["--episodes", a.episodes] if a.episodes else []))
        if not self.a.run:  # the plan shows the second command with its episode list still to come
            after_join = lambda: [(self.tool(SWEEP, "ingest", a.sweep, "--attempts", a.attempts, "--episodes", "<ok episodes of joined.json>",  # noqa: E731
                                              *(["--cell", a.cell] if a.cell else [])), d0 / "ingest.out")]
        if join_only:
            return self.stage("ingest", [a.attempts], [(join, joined)], [joined]), joined, None
        return self.stage("ingest", [x for x in (a.attempts, a.stack_check, a.sweep) if x], [(join, joined), after_join],
                          [joined, Path(a.sweep) / "real_outcomes.jsonl", Path(a.sweep) / "dr_next.json", Path(a.sweep) / "ingest.json"]), \
            joined, Path(a.sweep) / "dr_next.json"

    def gate(self):
        """The sysid task gate with the real outcomes: refuses a candidate whose sim predicts the real attempts worse than base's, never promotes.
        Inputs: the sweep dir (trials.jsonl + real_outcomes.jsonl from ingest) and the fit candidates. Real rows need no physics tag."""
        a = self.a
        miss = [f for f in ("fit", "candidate", "base_stack", "stack", "grasp") if not getattr(a, f)]
        if miss:
            raise SystemExit(f"gate needs --{', --'.join(m.replace('_', '-') for m in miss)}")
        real, trials = Path(a.sweep) / "real_outcomes.jsonl", Path(a.sweep) / "trials.jsonl"
        if a.run and not (real.exists() and trials.exists()):
            raise SystemExit(f"gate stopped: {real if trials.exists() else trials} is missing; run rank and ingest on this sweep first")
        d0 = self.run_dir / f"{self.n + 1:02d}-gate"
        step = self.tool(SYSID, "task", a.fit, "--candidate", a.candidate, "--base-stack", a.base_stack, "--stack", a.stack,
                         "--grasp", a.grasp, "--real", real, "--sweep", a.sweep, *(["--base", a.base_physics] if a.base_physics else []))
        return self.stage("gate", [a.fit, real, trials, a.base_stack, a.stack, a.grasp], [(step, d0 / "verdict.json")], [a.fit, d0 / "verdict.json"])

    def twin(self, joined):
        """Replay and report on a remote sim host (MuJoCo is not on the laptop); --local-twin runs omx_twin here instead."""
        a = self.a
        d0 = self.run_dir / f"{self.n + 1:02d}-twin"
        eps = lambda: [e["episode"] for e in json.loads(Path(joined).read_text(encoding="utf-8")).get("joined", []) if e["status"] == "ok"]  # noqa: E731
        if a.local_twin:
            def replays():
                selected = eps()
                if not selected:
                    raise Refused("no verified episodes joined; replay and calibration feedback cannot run")
                return [(self.tool(TWIN, "replay", e["path"], "--cell", a.cell, "--out", d0 / e["id"]), None) for e in selected]
            if not a.run:
                replays = lambda: [(self.tool(TWIN, "replay", "<each ok episode of joined.json>", "--cell", a.cell, "--out", d0 / "<id>"), None)]  # noqa: E731
            return self.stage("twin", [joined], [replays, (self.tool(TWIN, "report", d0), d0 / "report.md")], [d0]), d0
        py = "MUJOCO_GL=egl $HOME/rosy-test/venvs/sim-mujoco/bin/python"
        remote = lambda sha, ids: [self.py, REMOTE_SIM, "--host", a.twin_host, "--sha", sha, "--minutes", "40", "--log-dir", d0 / "remote", "cmd", "--", (  # noqa: E731
            f"mkdir -p $OUT/twin && for e in {' '.join(ids)}; do {py} tools/sim/omx_twin.py replay {EP_PREFIX}$e --cell {shlex.quote(str(a.cell))} --out $OUT/twin/$e || exit 1; done; "
            f"{py} tools/sim/omx_twin.py report $OUT/twin > $OUT/twin/report.md")]

        def ship():
            if not a.run:
                return [(remote("<wip commit of the joined episodes>", ["<id>"]), None)]
            ok = eps()
            if not ok:
                return []  # nothing to replay: bring_back stops with the reason, no remote job is started
            files = {f"{EP_PREFIX}{e['id']}/{f.relative_to(e['path']).as_posix()}": f for e in ok for f in sorted(Path(e["path"]).rglob("*")) if f.is_file()}
            sha = self.stage_files(ROOT, "HEAD", files, EP_PREFIX, "loop-twin")  # stage_files resolves HEAD to the full code sha
            return [(remote(sha, [e["id"] for e in ok]), None)]

        def bring_back():
            out = d0 / "remote" / "out" / "twin"
            if self.stubbed:  # the stub runner started no remote job, so there is nothing to bring back
                return
            if not list(out.glob("*/twin.json")):
                raise SystemExit(f"stage twin stopped: no twin.json came back under {out} (no ok episode in joined.json, or the remote replay wrote none)")
            import shutil
            shutil.copytree(out, d0, dirs_exist_ok=True)
        return self.stage("twin", [joined], [ship], [d0], after=bring_back), d0


def build(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["r2s", "rank", "offer", "ingest", "gate", "twin", "all"])
    p.add_argument("--run-dir", required=True)
    p.add_argument("--preset", default=PRESET, help="same preset (and so map frame) in every stage")
    p.add_argument("--choice", action="append", default=[], help="extra key=value Layout choice for sim/run")
    p.add_argument("--twin-host", default="ai", choices=TWIN_HOSTS, help="twin: the remote_sim role that replays (never a cell or site host)")
    p.add_argument("--local-twin", action="store_true", help="twin: run omx_twin here (needs MuJoCo) instead of on the remote sim host")
    p.add_argument("--python", default=sys.executable)
    p.set_defaults(run=False)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--plan", "--dry-run", dest="run", action="store_false", help="print the commands only (default)")
    g.add_argument("--run", dest="run", action="store_true", help="execute them")
    for f in ("capture", "prev", "twin", "dr-next", "sweep", "snapshot", "store", "attempts", "stack-check", "episodes", "cell", "fit", "candidate", "base-stack", "stack", "grasp", "base-physics"):
        p.add_argument("--" + f)
    p.add_argument("--camera-moved-ok", action="store_true")
    p.add_argument("--fresh", action="store_true", help="r2s: measure without --prev (the diff still uses it); for a --prev read in another map frame, which the map gate refuses to refit from")
    p.add_argument("--run-sweep", action="store_true", help="rank: also run the sweep (--sweep is its out dir)")
    p.add_argument("--site-store", action="store_true", help="allow offer to write the live site choices store")
    a = p.parse_args(argv)
    need = dict(r2s=["capture"], rank=["sweep"], offer=["sweep", "store"], ingest=["sweep", "attempts"], gate=["sweep", "fit", "candidate", "base_stack", "stack", "grasp"], twin=["cell"],
                all=["capture", "sweep", "store"])[a.stage]
    miss = [f for f in need if not getattr(a, f)]
    if miss:
        p.error(f"{a.stage} needs --{', --'.join(miss)}")
    return a


def main(argv=None, runner=None):
    a = build(argv)
    loop = Loop(a, runner)
    s = a.stage
    if s == "r2s":
        loop.r2s(a.twin, a.dr_next)
    elif s == "rank":
        loop.rank()
    elif s == "offer":
        loop.offer()
    elif s == "ingest":
        loop.ingest()
    elif s == "gate":
        loop.gate()
    elif s == "twin":
        if not a.attempts:
            raise SystemExit("twin replays the joined episodes: pass --attempts (and --episodes) so the join is made first")
        loop.twin(loop.ingest(join_only=True)[1])
    else:
        if a.camera_moved_ok:
            raise Refused("all requires an accepted calibration; use r2s for camera diagnostics")
        _, snap = loop.r2s(a.twin, a.dr_next)
        loop.rank(snap)
        loop.offer(snap)
        if a.attempts:
            if not a.cell:
                raise SystemExit("--attempts needs --cell for the twin stage")
            _, joined, dr = loop.ingest()
            if a.fit:
                loop.gate()
            _, twin_dir = loop.twin(joined)
            loop.a.capture = a.capture
            loop.r2s(twin_dir, dr, prev=snap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
