#!/usr/bin/env python3
"""Replay joint_jitter over runner traces and motor-health logs: the normal envelope, the worst and the flagged windows.

Run after every supervised session (and before changing a `jitter.*` cell param), on the field PC:

  jitter_replay.py [--trace "<prep dir>/trace-*.jsonl"] [--health "<prep dir>/motor-health-*.jsonl"]
                   [--params cell-params.json] [--json out.json]

Trace (30 Hz, ROSY_CHUNK_TRACE): per joint the std of present around the command (0.5 s moving mean removed), the
crossings per second of that residual and the peak-to-peak of present, in holds and in moves. Health (~4 Hz, so only
"PWM varies / flips at a standstill"): PWM std and sign changes per second. A trace uses its explicit trace-arm_a-*
or trace-arm_b-* name (as upkeep's jaw check does), else "trace"; mtime cannot establish an arm. Percentiles are over 2 s (trace)
or ~4 s (health) windows; `worst` is the three highest-std windows per joint with the chunk, lag and pose they had.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402
import joint_jitter as jj  # noqa: E402

ARMS = {"FF06202D": "arm_a", "FF061D2D": "arm_b"}
PCT = (50, 99, 99.9, 100)


def pct(values, p):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(p / 100 * len(values)))], 3) if values else None


def rows_of(path, keep=None):
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a log cut mid-line by a killed session
            if keep is None or keep(row):
                yield row


def health_windows(path, batch=4096):
    """(arm port tail, windows, faults) of one motor-health log, streamed so a 250 MB log stays small."""
    port, out, faults, buf = None, [], [], []
    for r in rows_of(path):
        if r.get("event") == "fault":
            faults.append(str(r.get("fault"))[:120])
        elif r.get("event") == "sample" and len(r.get("motors", [])) == 6:
            port = port or r["motors"][0]["usb_port"].rsplit("_", 1)[-1].split("-")[0][-8:]
            buf.append(r)
            if len(buf) >= batch:
                out += jj.health_windows(buf)
                buf = []
    return port, out + jj.health_windows(buf), faults


def replay(trace_paths, health_paths=(), params=None):
    arms = {}

    def arm_of(label):
        return arms.setdefault(label, {"trace_h": 0.0, "health_h": 0.0, "faults": [], "flagged": [], "joints": {
            m: {"hold": [], "move": [], "pwm": []} for m in jj.MOTORS}})

    def add(arm, wins, source, session):
        for w in wins:
            w["session"] = source
            arm["joints"][w["joint"]]["pwm" if "pwm_std" in w else "hold" if w["still"] else "move"].append(w)
        for joint, reason in jj.shaking(trace=[w for w in wins if "std" in w], health=[w for w in wins if "pwm_std" in w],
                                        params=params):
            arm["flagged"].append({"session": session, "joint": joint, "reason": reason})

    for path in map(Path, health_paths):
        port, wins, faults = health_windows(path)
        if port:
            label = ARMS.get(port, port)
            arm = arm_of(label)
            arm["health_h"] += len(wins) / 6 * jj.HEALTH_WINDOW / 4 / 3600
            arm["faults"] += [{"session": path.stem, "fault": f} for f in faults]
            add(arm, wins, path.stem, path.stem)
    for path in map(Path, trace_paths):
        label = next((arm for arm in ARMS.values() if path.name.startswith(f"trace-{arm}-")), "trace")
        wins = jj.trace_windows(rows_of(path, lambda r: "present" in r and "t" in r))
        arm = arm_of(label)
        arm["trace_h"] += len(wins) / 6 * jj.WINDOW_S / 3600
        add(arm, wins, path.stem, path.stem)
    for arm in arms.values():
        arm["trace_h"], arm["health_h"] = round(arm["trace_h"], 3), round(arm["health_h"], 1)
        for joint, kinds in arm["joints"].items():
            arm["joints"][joint] = {
                kind: {"windows": len(ws), **{m: [pct([w[m] for w in ws], p) for p in PCT]
                                              for m in (("pwm_std", "pwm_flips_hz") if kind == "pwm" else ("std", "flips_hz", "p2p"))},
                       "worst": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in w.items()}
                                 for w in sorted(ws, key=lambda w: -w.get("std", w.get("pwm_std")))[:3]]}
                for kind, ws in kinds.items()}
    return arms


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace", default="", help="glob of trace-*.jsonl")
    parser.add_argument("--health", default="", help="glob of motor-health-*.jsonl")
    parser.add_argument("--params", help="cell-params file (default: shipped values)")
    parser.add_argument("--json", help="also write the full result here")
    args = parser.parse_args(argv)
    params = prm.load(Path(args.params))["values"] if args.params else None
    arms = replay(sorted(glob.glob(args.trace)) if args.trace else [], sorted(glob.glob(args.health)) if args.health else [], params)
    for label, arm in sorted(arms.items()):
        print(f"== {label}: trace {arm['trace_h']} h, health {arm['health_h']} h, {len(arm['flagged'])} flagged, "
              f"{len(arm['faults'])} faults   (percentiles {PCT})")
        for joint, kinds in arm["joints"].items():
            for kind, e in kinds.items():
                if not e["windows"]:
                    continue
                cols = ("pwm_std", "pwm_flips_hz") if kind == "pwm" else ("std", "flips_hz", "p2p")
                print(f"   {joint:13s} {kind:4s} n={e['windows']:6d} " + "  ".join(f"{m} {e[m]}" for m in cols))
                for w in e["worst"][:1]:
                    print(f"      worst {w['session']} t={w['t']:.1f} chunk={w.get('chunk')} "
                          + " ".join(f"{k}={w[k]}" for k in ("std", "flips_hz", "p2p", "lag", "at", "pwm_std", "pwm_flips_hz") if k in w))
        for hit in arm["flagged"][:40]:
            print(f"   FLAG  {hit['session']} {hit['reason']}")
        for fault in arm["faults"]:
            print(f"   FAULT {fault['session']} {fault['fault']}")
    if args.json:
        Path(args.json).write_text(json.dumps(arms, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
