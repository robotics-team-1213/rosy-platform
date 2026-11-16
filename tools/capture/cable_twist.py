#!/usr/bin/env python3
"""Cable twist: judge whether a tethered robot's cable is twisted, and unwind it (D-512 tether, D-1034 cable mode).

    cable_twist.py judge  --token-file FILE --out DIR [--probe-deg 30]
    cable_twist.py unwind --token-file FILE --out DIR [--twist-deg +/-N] [--max-deg 360]

The robot turns in place and its own LiDAR measures how far it really turned (consecutive scans are
shifted by the turn; wheel odometry is not trusted on carpet). Two ideas, both in plain logic below:

* Twist is the signed net rotation since the cable was last slack: + means the robot wound it by turning
  counter-clockwise, so the cable is undone by turning clockwise. `TwistTracker` sums the measured turns.
* Direction probe: turn a little each way. The direction in which the robot turns LESS than commanded is
  the one the cable resists (the winding direction); the unwinding direction is the opposite one.

Every step is refused, not warned, when the shared RobotBody says the in-place turn is not clear (forward is
the URDF 180 deg, never scan index 0). Each step must turn the robot and shift the scan; a cable that stops the
turn ends the run and asks a person. It always ends with zero teleop and mode IDLE. Charging is expected here
(the cable may be the charger), so unlike map_drive this tool does not refuse a charging robot.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "contracts" / "foundation"))

ANG = 0.30                  # rad/s, hard cap of this tool
STEP_DEG = 20.0
PROBE_DEG = 30.0
SLACK_DEG = 20.0            # twist within this is "slack"
WARN_DEG, UNWIND_DEG, TRIP_DEG = 180.0, 270.0, 405.0   # TRIP matches fleet TetherWatch.TURN_LIMIT_DEG
ASYMMETRY = 0.25            # probe: relative difference of the two turning ratios that counts as resistance
SLACK_ASYMMETRY = 0.15      # unknown-twist unwind: below this the two directions are equally easy = slack
CHUNK_DEG = 90.0            # unknown-twist unwind: probe again after this much turning
MIN_RATIO = 0.25            # a step that turns less than this share of its command is "not turning"
SCAN_MAX_AGE_S = 0.6
SCAN_MIN_AGE_S = -0.5

_now, _sleep = time.time, time.sleep      # tests replace these with a fake clock


class Abort(Exception):
    pass


# ---------------------------------------------------------------- pure logic
def scan_yaw_delta(prev, cur, angle_inc_rad, max_deg=45.0, min_pairs=60):
    """Degrees the robot turned (+ counter-clockwise) between two in-place scans; None when unreliable.

    A turn of +d moves every feature d lower in sensor bearing, so cur[i] == prev[i + d/inc]."""
    n = len(prev)
    if n != len(cur) or n < 90 or angle_inc_rad <= 0:
        return None
    max_k = min(int(math.radians(max_deg) / angle_inc_rad), n // 2 - 2)
    costs = {}
    for k in range(-max_k, max_k + 1):
        total, count = 0.0, 0
        for i in range(n):
            a, b = prev[(i + k) % n], cur[i]
            if a is None or b is None:
                continue
            total += min(abs(a - b), 0.5)      # clipped, so one bad return cannot decide the shift
            count += 1
        if count >= min_pairs:
            costs[k] = total / count
    if len(costs) < 5:
        return None
    best = min(costs, key=costs.get)
    typical = sorted(costs.values())[len(costs) // 2]
    if typical < 1e-9 or costs[best] > 0.6 * typical:   # no clear minimum: a featureless or moving scene
        return None
    frac = 0.0
    if best - 1 in costs and best + 1 in costs:
        lo, mid, hi = costs[best - 1], costs[best], costs[best + 1]
        denom = lo - 2 * mid + hi
        frac = 0.5 * (lo - hi) / denom if denom > 1e-12 else 0.0
    return math.degrees((best + frac) * angle_inc_rad)


class TwistTracker:
    """Signed net rotation (deg) since the cable was slack, from measured turns."""

    def __init__(self, start_deg=0.0):
        self.twist_deg, self.turned_deg = float(start_deg), 0.0

    def add(self, delta_deg):
        self.twist_deg += delta_deg
        self.turned_deg += abs(delta_deg)

    def state(self):
        a = abs(self.twist_deg)
        return "trip" if a >= TRIP_DEG else "unwind" if a >= UNWIND_DEG else "warn" if a >= WARN_DEG else "ok"

    def unwind_sign(self):
        return -1 if self.twist_deg > 0 else 1


def probe_verdict(achieved_ccw_deg, achieved_cw_deg, commanded_deg):
    """Compare the turn achieved each way (cw is negative). unwind_sign: +1 ccw, -1 cw, None when no twist shows."""
    r_ccw, r_cw = achieved_ccw_deg / commanded_deg, -achieved_cw_deg / commanded_deg
    best = max(r_ccw, r_cw)
    if best < MIN_RATIO:
        return dict(verdict="not_turning", unwind_sign=None, asymmetry=None, r_ccw=r_ccw, r_cw=r_cw)
    asymmetry = abs(r_ccw - r_cw) / best
    resisted = 1 if r_ccw < r_cw else -1         # the direction that turns less is the winding direction
    if asymmetry < ASYMMETRY:
        return dict(verdict="symmetric", unwind_sign=None, winding_sign=resisted, asymmetry=asymmetry, r_ccw=r_ccw, r_cw=r_cw)
    return dict(verdict="twisted", unwind_sign=-resisted, winding_sign=resisted, asymmetry=asymmetry, r_ccw=r_ccw, r_cw=r_cw)


# ---------------------------------------------------------------- robot side
def _core(args):
    from edge_drive import Core, tls_context
    return Core(args.robot, Path(args.token_file).read_text(encoding="utf-8").strip(), args.port, tls_context(None, True))


def fresh_scan(core):
    s, scan = core.call("GET", "/sensors/lidar")
    if s != 200 or not isinstance(scan, dict):
        raise Abort(f"no LiDAR scan ({s})")
    ranges, stamp = scan.get("ranges"), scan.get("received_at")
    if not isinstance(ranges, list) or not ranges or not isinstance(stamp, (int, float)):
        raise Abort("LiDAR scan lacks ranges or received_at")
    age = _now() - float(stamp)
    if not SCAN_MIN_AGE_S <= age <= SCAN_MAX_AGE_S:
        raise Abort(f"LiDAR scan age {age:.2f}s outside [{SCAN_MIN_AGE_S}, {SCAN_MAX_AGE_S}]")
    return scan


def _ranges(scan):
    return [r if isinstance(r, (int, float)) and math.isfinite(r) and r >= scan.get("range_min", 0.05) else None
            for r in scan["ranges"]]


def _teleop_for(core, ang, secs):
    t0 = _now()
    while _now() - t0 < secs:
        s, b = core.call("POST", "/teleop", {"linear": 0.0, "angular": ang}, attempts=1)
        if s != 200:
            raise Abort(f"teleop refused {s} {b}")
        _sleep(0.1)
    core.call("POST", "/teleop", {"linear": 0.0, "angular": 0.0})


def rotate_step(core, sign, deg, forward_deg, log):
    """Turn `deg` in direction `sign` under the body guard; return the degrees really turned (signed)."""
    from core_common.robot_body import PINKY_PRO
    before = fresh_scan(core)
    kind, why = PINKY_PRO.rotation_check(PINKY_PRO.scan_view(before, forward_deg=forward_deg))
    if kind:
        raise Abort(f"turn not clear: {why}")
    _teleop_for(core, sign * ANG, math.radians(deg) / ANG)
    _sleep(0.3)
    after = fresh_scan(core)
    if after["received_at"] <= before["received_at"]:
        raise Abort("LiDAR scan did not advance after the step")
    delta = scan_yaw_delta(_ranges(before), _ranges(after), before["angle_increment"])
    log({"event": "step", "sign": sign, "commanded_deg": deg, "measured_deg": delta})
    if delta is None:
        raise Abort("the turn could not be measured from the scans (featureless room or the robot was held)")
    return delta


def run_judge(core, args, log, forward_deg, probe_deg=None):
    probe_deg = probe_deg or args.probe_deg
    ccw = rotate_step(core, +1, probe_deg, forward_deg, log)
    cw = rotate_step(core, -1, probe_deg, forward_deg, log)
    verdict = probe_verdict(ccw, cw, probe_deg)
    log({"event": "verdict", **verdict, "net_turn_deg": ccw + cw})
    return verdict


def run_unwind(core, args, log, forward_deg):
    stuck = 0
    if args.twist_deg is not None:                         # known twist: bring it to slack
        tracker = TwistTracker(args.twist_deg)
        while abs(tracker.twist_deg) > SLACK_DEG:
            sign = tracker.unwind_sign()
            step = min(STEP_DEG, abs(tracker.twist_deg))
            delta = rotate_step(core, sign, step, forward_deg, log)
            tracker.add(delta)
            stuck = stuck + 1 if delta * sign < MIN_RATIO * step else 0
            log({"event": "twist", "twist_deg": round(tracker.twist_deg, 1), "state": tracker.state()})
            if stuck >= 2:
                raise Abort("the robot is not turning toward slack: the cable is snagged or the robot is held; ask a person")
            if tracker.turned_deg > abs(args.twist_deg) + 90.0:
                raise Abort("turned far more than the twist said; the estimate is wrong, stopping")
        return dict(outcome="slack", twist_deg=tracker.twist_deg)
    verdict = run_judge(core, args, log, forward_deg)      # unknown twist: the probe picks the direction
    if verdict["unwind_sign"] is None:
        return dict(outcome="no_twist_detected", verdict=verdict["verdict"])
    sign, turned = verdict["unwind_sign"], 0.0
    while turned < args.max_deg:
        chunk = 0.0
        while chunk < CHUNK_DEG and turned < args.max_deg:
            delta = rotate_step(core, sign, STEP_DEG, forward_deg, log)
            if delta * sign < MIN_RATIO * STEP_DEG:
                raise Abort("the robot stopped turning while unwinding; the cable is snagged. Ask a person")
            chunk += abs(delta)
            turned += abs(delta)
        verdict = run_judge(core, args, log, forward_deg, probe_deg=args.probe_deg / 2)   # slack = both ways equally easy
        if verdict["verdict"] == "not_turning":
            raise Abort("the probe turns did not move the robot; the cable is snagged. Ask a person")
        if verdict["asymmetry"] < SLACK_ASYMMETRY:
            return dict(outcome="slack_reached", unwound_deg=turned)
        if verdict["winding_sign"] == sign:                # the way it was unwinding is now the resisted one: slack was passed
            return dict(outcome="passed_slack", unwound_deg=turned)
    return dict(outcome="max_turn_reached", unwound_deg=turned)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("judge", "unwind"))
    ap.add_argument("--robot", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--probe-deg", type=float, default=PROBE_DEG)
    ap.add_argument("--twist-deg", type=float, help="known signed twist (+ = wound counter-clockwise)")
    ap.add_argument("--max-deg", type=float, default=360.0)
    ap.add_argument("--lidar-forward-deg", type=float)
    args = ap.parse_args(argv)
    if not 5 <= args.probe_deg <= 90 or not 0 < args.max_deg <= 720 or (args.twist_deg is not None and abs(args.twist_deg) > 720):
        sys.exit("limits: 5 <= probe-deg <= 90, 0 < max-deg <= 720, |twist-deg| <= 720")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fh = (out / "steps.jsonl").open("a", encoding="utf-8")

    def log(row):
        row["t"] = round(_now(), 2)
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        print(json.dumps(row), flush=True)

    core, code = _core(args), 0
    try:
        from edge_drive import lidar_forward_deg
        deg, _ = lidar_forward_deg(None, args.lidar_forward_deg)
        if abs(deg - 180.0) > 20.0:
            raise Abort(f"LiDAR forward {deg} is not the Pinky Pro 180 deg; refusing to drive")
        s, st = core.call("GET", "/robot/state")
        st = st if isinstance(st, dict) else {}
        if s != 200 or st.get("mode") != "IDLE" or (st.get("safety") or {}).get("estop"):
            raise Abort(f"state not drivable: {s} mode={st.get('mode')}")
        s, b = core.call("POST", "/mode", {"mode": "MANUAL"})
        if s != 200:
            raise Abort(f"MANUAL refused {s} {b}")
        result = run_judge(core, args, log, deg) if args.command == "judge" else run_unwind(core, args, log, deg)
        log({"event": "done", **result})
    except Abort as exc:
        log({"event": "abort", "why": str(exc)})
        code = 2
    except Exception as exc:
        log({"event": "abort", "why": f"unexpected {type(exc).__name__}: {exc}"})
        code = 2
    finally:
        core.call("POST", "/teleop", {"linear": 0.0, "angular": 0.0})
        for _ in range(3):
            if core.call("POST", "/mode", {"mode": "IDLE"})[0] == 200:
                break
            _sleep(0.5)
        s, st = core.call("GET", "/robot/state")
        mode = st.get("mode") if isinstance(st, dict) else None
        log({"event": "end", "mode": mode})
        fh.close()
        if mode != "IDLE":
            code = 3
    return code


if __name__ == "__main__":
    sys.exit(main())
