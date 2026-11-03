#!/usr/bin/env python3
"""Replay joint_push over follower motor-health logs: what it would have caught, and the normal envelope.

Run after every supervised session (and before changing a `windup.*` cell param), on the field PC:

  push_replay.py "<prep dir>/motor-health-*.jsonl" [--params cell-params.json] [--json out.json]

Per arm (USB serial tail): hours sampled, the hits (session, t, reason), the session faults, and per load-bearing
joint the largest wind-up seen at a standstill and the largest |PWM| there. A hit before a fault is a catch, a hit
in a session that ended well needs a look (a real press or a false alarm), and the envelope against
windup.rest_rise is the margin the threshold keeps from normal holds.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402
import joint_push as jp  # noqa: E402


def deg(raw):
    return raw * 360 / 4096


def replay(paths, params=None):
    arms = {}
    for path in paths:
        rows = []
        for line in Path(path).read_text(errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue  # a log cut mid-line by a killed session
        samples = [r for r in rows if r.get("event") == "sample" and len(r.get("motors", [])) == 6]
        if not samples:
            continue
        port = samples[0]["motors"][0]["usb_port"].rsplit("_", 1)[-1].split("-")[0][-8:]
        arm = arms.setdefault(port, {"hours": 0.0, "hits": [], "faults": [],
                                     "envelope": {m: {"rise": 0, "pwm": 0, "top": []} for m in jp.MOTORS[:4]}})
        session, t0, last, window, armed = Path(path).stem, samples[0]["sample_time"], None, [], True
        for r in samples:
            if last is not None and r["sample_time"] - last < 0.95:
                continue  # the runner reads health at 1 Hz; the session sampler runs ~4 Hz
            if last is not None and r["sample_time"] - last > 3:
                window = []
            arm["hours"] += (r["sample_time"] - last) / 3600 if window else 0
            last, motors = r["sample_time"], r["motors"]
            window = (window + [([deg(m["command_raw"]) for m in motors], [deg(m["present_raw"]) for m in motors],
                                 [m["pwm"] for m in motors])])[-jp.REST_SAMPLES:]
            limits = {m["joint"]: m.get("pwm_limit") for m in motors}
            hit = jp.pushing(window, limits, params=params)
            if hit and armed:
                arm["hits"].append({"session": session, "t": round(last - t0, 1), "reason": hit[1]})
            elif not hit and len(window) == jp.REST_SAMPLES:
                for i, motor in enumerate(jp.MOTORS[:4]):
                    target, present, pwm = ([s[k][i] for s in window] for k in range(3))
                    env = arm["envelope"][motor]
                    up = jp.windup(target, present, pwm)
                    env["rise"] = max(env["rise"], up)
                    if up:  # the largest normal wind-ups, with the PWM they reached: the margin both gates keep
                        env["top"] = sorted(env["top"] + [{"rise": up, "pwm": abs(pwm[-1]), "cap": limits.get(motor),
                                                           "session": session, "t": round(last - t0, 1)}],
                                            key=lambda w: -w["rise"])[:3]
                    if max(present) - min(present) < jp.STILL:
                        env["pwm"] = max(env["pwm"], abs(pwm[-1]))
            armed = not hit
        arm["faults"] += [{"session": session, "fault": str(r.get("fault"))[:120]} for r in rows if r.get("event") == "fault"]
    for arm in arms.values():
        arm["hours"] = round(arm["hours"], 1)
    return arms


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logs", help="glob of motor-health-*.jsonl")
    parser.add_argument("--params", help="cell-params file (default: shipped values)")
    parser.add_argument("--json", help="also write the full result here")
    args = parser.parse_args(argv)
    params = prm.load(Path(args.params))["values"] if args.params else None
    arms = replay(sorted(glob.glob(args.logs)), params)
    rise = prm.get(params, "windup.rest_rise")
    for port, arm in sorted(arms.items()):
        print(f"== {port}: {arm['hours']} h, {len(arm['hits'])} hits, {len(arm['faults'])} faults")
        for motor, env in arm["envelope"].items():
            print(f"   {motor:13s} normal wind-up {env['rise']:4d} (threshold {rise}), still |PWM| up to {env['pwm']}")
            for w in env["top"]:
                print(f"      {w['rise']:4d} to PWM {w['pwm']} of {w['cap']}  {w['session']} t={w['t']}")
        for hit in arm["hits"]:
            print(f"   HIT   {hit['session']} t={hit['t']} {hit['reason']}")
        for fault in arm["faults"]:
            print(f"   FAULT {fault['session']} {fault['fault']}")
    if args.json:
        Path(args.json).write_text(json.dumps(arms, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
