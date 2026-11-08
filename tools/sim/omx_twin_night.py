#!/usr/bin/env python3
"""One night of the OMX twin from the operator laptop: both lab PCs in parallel, rerun after their nightly reboot.

  AI PC     omx_twin.py batch --watch (MuJoCo, shard 0/2): every closed real episode replayed as it appears, plus
            omx_twin.py live on arm_b's live.json while the cell runs.
  model PC  the Isaac problem-case suite first (cell_cases.py -> cell_case_suite.py, real outcome vs Isaac's, D-872;
            Isaac wants the GPU alone), then omx_twin.py batch --watch shard 1/2.
At the deadline the twin results of both hosts come back and omx_twin.py report writes report.md beside them.
Everything heavy runs through remote_sim.py / remote_isaac.py (committed sha, caps, locks; never this laptop, D-584);
the site PC is only read (D-571).

  python tools/sim/omx_twin_night.py --sha <committed> --cell-on-host ~/rosy-scratch/ladder-core/cell.json \
      --out <records dir> [--until 08:30]
"""
import argparse
import datetime as dt
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = "robttt@100.82.51.8"
EPISODES = "/home/robttt/rosy-data/omx-auto/episodes-20261028"
LIVE = "/home/robttt/rosy-test/omx-record-prep-20261019/chunk-io-b/live.json"
CASES = "/home/robttt/rosy-test/omx-record-prep-20261019/cell-pipeline/cases.jsonl"
PY = "MUJOCO_GL=egl $HOME/rosy-test/venvs/sim-mujoco/bin/python tools/sim/omx_twin.py"
JOBS = {"ai": 3, "model": 6}  # remote_sim caps: ai 4 cores/4 GB, model 8 cores/6 GB


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def remote_sim(args, role, minutes, command):
    cmd = [sys.executable, str(ROOT / "tools/remote/remote_sim.py"), "--host", role, "--sha", args.sha, "--durable",
           "--minutes", str(minutes), "--log-dir", str(args.out / f"remote-{role}"), "cmd", "--", command]
    return subprocess.run(cmd, cwd=ROOT).returncode


def mujoco_loop(args, role, shard, live=False):
    """Keep this host's twin running until the deadline; a reboot or a refused start is retried 5 min later."""
    out = f"~/rosy-scratch/twin-night/{args.night}"
    while (left := (args.deadline - time.time()) / 60) > 20:
        minutes = int(left) - 10
        body = (f"{PY} batch --site {SITE} --root {EPISODES} --since {args.since} --shard {shard} --cell {args.cell_on_host} "
                f"--out {out} --jobs {JOBS[role]} --watch {minutes - 15}")
        if live:
            body = (f"( {PY} live --site {SITE} --live {LIVE} --cell {args.cell_on_host} --out {out}/live "
                    f"--minutes {minutes - 15} > {out}-live.log 2>&1 & ) ; {body}")
        body = f"mkdir -p {out} && {body}"
        log(role, "start", shard, f"{minutes} min")
        rc = remote_sim(args, role, minutes, body)
        log(role, "ended rc", rc)
        if (args.deadline - time.time()) / 60 > 20:
            time.sleep(300)


def isaac_cases(args):
    work = args.out / "isaac"
    work.mkdir(parents=True, exist_ok=True)
    cases = work / "cases.jsonl"
    cases.write_bytes(subprocess.run(["ssh", "-o", "BatchMode=yes", SITE, f"cat {shlex.quote(CASES)}"],
                                     capture_output=True, check=True).stdout)
    omx = ROOT / "deploy/robot/omx"
    env = dict(os.environ, PYTHONPATH=str(ROOT / "middleware/devices/omx/adapter"))  # teach_trajectory imports omx_adapter
    subprocess.run([sys.executable, str(omx / "cell_cases.py"), "--cases", str(cases), "--out", str(work / "suite.json")], check=True, env=env)
    log("model", "isaac suite start")
    with (work / "suite.log").open("w") as f:
        rc = subprocess.run([sys.executable, str(omx / "cell_case_suite.py"), "--suite", str(work / "suite.json"),
                             "--sha", args.sha, "--out", str(work / "runs")], stdout=f, stderr=subprocess.STDOUT, env=env).returncode
    log("model", "isaac suite rc", rc, "(1 = a case no longer matches the real outcome, see suite.log)")


def model_lane(args):
    try:
        isaac_cases(args)
    except Exception as e:  # the MuJoCo half still runs
        log("model", "isaac suite failed:", e)
    mujoco_loop(args, "model", "1/2")


def collect(args):
    """Twin results (not the copied episodes) of both hosts into out/twin, then the report."""
    for host in ("rosy@100.98.162.71", "ai@100.108.76.123"):
        tar = subprocess.run(["ssh", "-o", "BatchMode=yes", host,
                              f"cd ~/rosy-scratch/twin-night/{args.night} 2>/dev/null && tar -cf - --exclude=./episodes . || true"],
                             capture_output=True).stdout
        if tar:
            dest = args.out / "twin" / host.split("@")[0]
            dest.mkdir(parents=True, exist_ok=True)
            subprocess.run(["tar", "-xf", "-", "-C", str(dest)], input=tar, check=True)
    report = subprocess.run([sys.executable, str(ROOT / "tools/sim/omx_twin.py"), "report", str(args.out / "twin")],
                            capture_output=True, text=True)
    (args.out / "report.md").write_text(report.stdout + report.stderr, encoding="utf-8")
    log("report", args.out / "report.md")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--sha", required=True)
    p.add_argument("--cell-on-host", required=True, help="the private MuJoCo cell file, same path on both lab PCs")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--until", default="08:30")
    p.add_argument("--since", default="20261101")
    p.add_argument("--no-isaac", action="store_true")
    args = p.parse_args(argv)
    now = dt.datetime.now()
    h, m = (int(x) for x in args.until.split(":"))
    end = now.replace(hour=h, minute=m, second=0, microsecond=0)
    end += dt.timedelta(days=1) if end <= now else dt.timedelta()
    args.deadline, args.night = end.timestamp(), now.strftime("%Y%m%d")
    args.out.mkdir(parents=True, exist_ok=True)
    lanes = [threading.Thread(target=mujoco_loop, args=(args, "ai", "0/2", True)),
             threading.Thread(target=(lambda: mujoco_loop(args, "model", "1/2")) if args.no_isaac else model_lane, args=() if args.no_isaac else (args,))]
    for t in lanes:
        t.start()
    for t in lanes:
        t.join()
    collect(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
