#!/usr/bin/env python3
"""Fit the per-arm load model load_predict.py applies, from follower motor-health logs (run on the field PC):

  load_model.py "<prep dir>/motor-health-*.jsonl" --out load-model.json

Standstill samples only: the body joints' command and present each within STILL_RAW counts over a 4-sample window
at 1 Hz (push_replay's cadence) and the command within HOLD_RAW of the present. Per load-bearing joint a linear fit
of PWM on the gravity terms of load_predict.features (the elbow/wrist senses against the lift picked per arm by the
lowest error), refit once without the points beyond 3 sigma (wind-ups and presses are not holds). Prints the fit
error per arm and joint, with the error on every 4th session held out of the fit.
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_predict as lp  # noqa: E402

STILL_RAW, HOLD_RAW, WINDOW = 4, 24, 4
BODY6 = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def units(raw):
    return raw * 200 / 4095 - 100  # LeRobot RANGE_M100_100 over a 0..4095 calibration


def read(path):
    rows = []
    for line in Path(path).read_text(errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # a log cut mid-line by a killed session
    return [r for r in rows if r.get("event") == "sample" and len(r.get("motors", [])) == 6]


def standstill(samples):
    """(pose in units, pwm, caps) of every still sample: the last of WINDOW 1 Hz samples, none a gap apart."""
    out, win, last = [], [], None
    for r in samples:
        if last is not None and r["sample_time"] - last < 0.95:
            continue
        win = [] if last is not None and r["sample_time"] - last > 3 else win
        last, m = r["sample_time"], r["motors"]
        win = (win + [([x["command_raw"] for x in m], [x["present_raw"] for x in m], [x["pwm"] for x in m],
                       [x.get("hardware_error", 0) for x in m], [x.get("pwm_limit") for x in m])])[-WINDOW:]
        if len(win) < WINDOW or any(w[3][i] for w in win[-1:] for i in range(6)):
            continue
        cmd, pre = np.array([w[0][:4] for w in win]), np.array([w[1][:4] for w in win])
        if np.ptp(cmd, 0).max() <= STILL_RAW and np.ptp(pre, 0).max() <= STILL_RAW and abs(cmd[-1] - pre[-1]).max() <= HOLD_RAW:
            out.append(([units(v) for v in win[-1][1]], win[-1][2], win[-1][4]))
    return out


def fit(poses, pwm, signs, fold):
    """coef, then residual stats; `fold` marks the held-out rows (not in the fit)."""
    x = np.array([lp.features(p, signs) for p in poses])
    keep = ~fold
    coef = np.linalg.lstsq(x[keep], pwm[keep], rcond=None)[0]
    sigma = (pwm[keep] - x[keep] @ coef).std()
    trim = keep & (abs(pwm - x @ coef) <= 3 * max(sigma, 1.0))
    coef = np.linalg.lstsq(x[trim], pwm[trim], rcond=None)[0]
    return coef, pwm - x @ coef, trim


def build(paths, min_cell=20):
    """{tail: samples} -> the model dict; also the per-arm report numbers inside it."""
    arms = {}
    for n, path in enumerate(paths):
        s = read(path)
        if s:
            tail = s[0]["motors"][0]["usb_port"].rsplit("_", 1)[-1].split("-")[0][-8:]
            arms.setdefault(tail, []).extend((*row, n) for row in standstill(s))
    model = {"schema": lp.SCHEMA, "arms": {}}
    for tail, rows in arms.items():
        poses, pwm = [r[0] for r in rows], np.array([r[1] for r in rows], dtype=float)
        fold = np.array([r[3] % 4 == 3 for r in rows])  # every 4th session held out of the fit
        best = min(itertools.product((1, -1), repeat=2), key=lambda sg: sum(
            ((fit(poses, pwm[:, i], sg, fold)[1][fold]) ** 2).mean() for i in (1, 2, 3)))
        joints = {}
        for i, name in enumerate(lp.BODY):
            if i == 0:
                continue
            coef, res, trim = fit(poses, pwm[:, i], best, fold)
            caps = [r[2][i] for r in rows if r[2][i]]
            joints[name] = {"coef": [round(float(c), 3) for c in coef], "n": int(trim.sum()), "cap": max(caps),
                            "rms": round(float(res[trim].std()), 1), "p95_abs_pwm": round(float(np.percentile(abs(pwm[:, i]), 95))),
                            "max_abs_pwm": int(abs(pwm[:, i]).max()), "resid_p95": round(float(np.percentile(abs(res[trim]), 95)), 1),
                            "holdout_rms": round(float(res[fold].std()), 1), "r2": round(1 - res[trim].var() / pwm[trim, i].var(), 3)}
        cells = {}
        for p in poses:
            cells[lp.cell(p)] = cells.get(lp.cell(p), 0) + 1
        model["arms"][tail] = {"signs": list(best), "samples": len(rows), "sessions": len({r[3] for r in rows}),
                               "joints": joints, "cells": {c: k for c, k in cells.items() if k >= min_cell},
                               "range": {j: [round(min(p[i] for p in poses), 1), round(max(p[i] for p in poses), 1)]
                                         for i, j in ((0, "shoulder_pan"), (4, "wrist_roll"))}}
    return model


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", help="glob of motor-health-*.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-cell", type=int, default=20, help="standstill samples a coverage cell needs to be kept")
    args = ap.parse_args(argv)
    model = build(sorted(glob.glob(args.logs)), args.min_cell)
    Path(args.out).write_text(json.dumps(model, separators=(",", ":")))
    for tail, arm in model["arms"].items():
        print(f"== {tail}: {arm['samples']} standstill samples, {arm['sessions']} sessions, signs {arm['signs']}, "
              f"{len(arm['cells'])} cells, range {arm['range']}")
        for name, j in arm["joints"].items():
            print(f"   {name:13s} n {j['n']:6d} rms {j['rms']:6.1f} holdout {j['holdout_rms']:6.1f} p95 {j['resid_p95']:6.1f} "
                  f"R2 {j['r2']:.2f}  |PWM| p95 {j['p95_abs_pwm']} max {j['max_abs_pwm']} of cap {j['cap']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
