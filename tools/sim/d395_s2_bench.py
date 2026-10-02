#!/usr/bin/env python3
"""D-395 S2 Gazebo bench driver: 4 robots, CORE + loc_assist + Fleet, zero human input.

Builds on the S1 driver (`d395_s1_bench.Bench`: launch, CORE polling, scores, teardown) and adds
what four robots need. One call is one power-on of layout `q`:

  r1 on square A, r2 on square B, r3 and r4 off-slot   (s2a: all reach LOCALIZED)

optionally with, in this order,

  --traffic  (s2d) homing in traffic, during the power-on: once r1 and r2 are LOCALIZED and r4
             (lone-ish, never trusted) is in CANDIDATES with its ladder rotation, r1 and r2 get
             Fleet goals that pass about 0.5 m from r4, through the console (`POST
             /api/fleet/robots/<id>/goal`), so the traffic keep-out and hold decide;
  phase c    (s2c) forced mirror on r4 with 4 robots: detected in time, nobody else accused;
  phase b    (s2b) simultaneous re-arbitration: `safety/pickup` on r1 and r4 at once, both
             teleported, set down; r4 lands on the 180-degree twin of its old pose, so a stale
             anchor at r4's old pose would hand r1's twin a `peers` cue (the "dragged" trap).

Timeouts are **sim seconds** (the host runs Gazebo far below real time), each capped in wall
time by `--max-wall`. Gazebo truth for all robots comes from one `pose/info` read (falls back
to `gz model`); the summary computes the minimum pairwise distance from that trail.
The bench polls `/api/fleet/state` every second, as the console UI does: Fleet's traffic,
trust and queue release run on that read.

  python tools/sim/d395_s2_bench.py --out /rosy_d395e_runs/q1 --traffic --phases c,b

S2 rerun (one power-on covers d, then c, then b): add `--physics-step 0.005 --gpu`.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d395_s1_bench as s1  # noqa: E402
from d395_s2_layout import (SCENARIOS, drop_layout, drop_problems, parse_pose_v,  # noqa: E402
                             scenario_problems, stale_trap)
from d395_truth import mirror  # noqa: E402

WORLD = s1.WORLD

#: CORE navigation states of a live goal (NAV_STATES); ARRIVED/IDLE/CANCELED/FAILED are not.
ACTIVE_NAV = ("PLANNING", "NAVIGATING", "BLOCKED")


class Bench(s1.Bench):
    SCENARIOS = SCENARIOS

    def __init__(self, args):
        # Set before the S1 constructor: it starts the sampling thread.
        self.fleet_rows, self.fleet_last, self.fleet_at = {}, {}, -math.inf
        self.latest_poses = (-math.inf, {})
        self.traffic = None
        super().__init__(args)
        self.sc = SCENARIOS[args.scenario]
        self.record["layout_problems"] = scenario_problems(self.sc)
        self.record["t0_epoch"] = time.time() - (time.monotonic() - self.t0)

    def rid(self, index):
        return self.robots[index]

    # --- truth and clock ------------------------------------------------------------------
    def read_poses(self):
        text = self.run_quiet(["gz", "topic", "-e", "-n", "1", "-t", f"/world/{WORLD}/pose/info"], 15.0)
        poses = parse_pose_v(text, set(self.robots))
        for rid in self.robots:
            if rid not in poses:
                pose = s1.parse_gz_model_pose(self.run_quiet(["gz", "model", "-m", rid, "-p"], 20.0))
                if pose is not None:
                    poses[rid] = pose
        self.latest_poses = (time.monotonic(), poses)
        return poses

    def truth(self, rid):
        at, poses = self.latest_poses
        if time.monotonic() - at > 1.5 or rid not in poses:
            poses = self.read_poses()
        return poses.get(rid)

    def sample_clock(self):
        while not self.stopping.is_set():
            t = self.t()
            text = self.run_quiet(["gz", "topic", "-e", "-n", "1", "-t", f"/world/{WORLD}/stats"], 8.0)
            sim = re.search(r"sim_time\s*\{\s*sec:\s*(\d+)(?:\s*nsec:\s*(\d+))?", text)
            rtf = re.search(r"real_time_factor:\s*([0-9.eE+-]+)", text)
            if sim:
                self.clock_samples.append((t, int(sim.group(1)) + int(sim.group(2) or 0) * 1e-9,
                                           float(rtf.group(1)) if rtf else None))
            for rid, pose in self.read_poses().items():
                self.trail.append((t, rid, *pose))
            self.stopping.wait(1.0)

    def sim_now(self):
        return self.clock_samples[-1][1] if self.clock_samples else None

    def wait(self, until, timeout_s, period=0.5):
        """As S1, but `timeout_s` is sim seconds, capped at timeout_s / --min-rtf and --max-wall."""
        start_wall, start_t, start_sim = time.monotonic(), self.t(), None
        cap = min(timeout_s / self.args.min_rtf, self.args.max_wall)
        snaps = {}
        while True:
            dead = [p.pid for p in self.procs if p.poll() is not None]
            if dead:
                raise RuntimeError(f"launched process exited: {dead}")
            snaps = self.poll()
            if until(snaps):
                return snaps, True
            sim = self.sim_now()
            if start_sim is None:   # the first sample taken after the wait began, not an older one
                start_sim = next((s for t, s, _ in self.clock_samples if t >= start_t), None)
            if start_sim is not None and sim is not None and sim - start_sim >= timeout_s:
                return snaps, False
            if time.monotonic() - start_wall >= cap:
                return snaps, False
            time.sleep(period)

    # --- Fleet ----------------------------------------------------------------------------
    def fleet(self, method, path, body=None, timeout=5.0):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.args.fleet_port}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"null")
            except ValueError:
                return exc.code, None
        except (OSError, ValueError):
            return None, None

    def fleet_state(self):
        """The console UI's read: it runs Fleet traffic, trust and queue release."""
        if time.monotonic() - self.fleet_at < 1.0:
            return None
        self.fleet_at = time.monotonic()
        code, body = self.fleet("GET", "/api/fleet/state", timeout=8.0)
        if code != 200 or not body:
            return None
        rows = self.fleet_rows = {row["robot_id"]: row for row in body.get("robots", ())}
        for rid, row in rows.items():
            key = json.dumps([row.get("goal"), row.get("queued"), row.get("held"), row.get("yielding")],
                             sort_keys=True, default=str)
            if key != self.fleet_last.get(rid):
                self.fleet_last[rid] = key
                self.note("fleet", robot=rid, goal=row.get("goal"), queued=row.get("queued"),
                          held=row.get("held"), yielding=row.get("yielding"),
                          badge=row.get("localization"))
        return rows

    def poll(self):
        snaps = super().poll()
        self.fleet_state()
        if self.traffic is not None:
            self.traffic_tick(snaps, self.fleet_rows)
        return snaps

    # --- s2d: homing in traffic -----------------------------------------------------------
    def arm_traffic(self):
        tr = self.sc["traffic"]
        self.traffic = {"homer": self.rid(tr["homer"]), "started": None, "done": False,
                        "drivers": {self.rid(i): {"legs": legs, "leg": 0, "posted": None, "posted_sim": None, "attempts": 0,
                                                  "navigating": False, "done": []}
                                    for i, legs in tr["drivers"].items()},
                        "posts": [], "homer_at_start": None}

    def traffic_tick(self, snaps, rows):
        tr = self.traffic
        if tr["done"]:
            return
        homer = tr["homer"]
        if tr["started"] is None:
            drivers_ok = all(self.loc_state(snaps, d) == "LOCALIZED" for d in tr["drivers"])
            mission = self.missions.get(homer) or {}
            # Start while the homer's ladder mission runs. If the homer localizes without one,
            # start anyway and record it, so the phase is never silently skipped.
            if not drivers_ok or not (mission.get("state") == "running"
                                      or self.loc_state(snaps, homer) == "LOCALIZED"):
                return
            tr["started"] = self.t()
            tr["homer_at_start"] = {"state": self.loc_state(snaps, homer), "mission": mission,
                                    "truth": self.truth(homer)}
            self.note("traffic_start", **tr["homer_at_start"])
        now = time.monotonic()
        for rid, d in tr["drivers"].items():
            if d["leg"] >= len(d["legs"]):
                continue
            nav = ((snaps.get(rid) or {}).get("navigation"))
            queued = (rows.get(rid) or {}).get("queued")
            goal = d["legs"][d["leg"]]
            if d["posted"] is not None:
                if queued:
                    # Held, queued or yielding: an ARRIVED now (a bay) is not this leg; the
                    # released goal must be seen driving again.
                    d["navigating"] = False
                elif nav in ACTIVE_NAV:
                    d["navigating"] = True
                elif d["navigating"] and nav == "ARRIVED":
                    truth = self.truth(rid)
                    off = None if truth is None else round(math.dist(truth[:2], goal[:2]), 3)
                    d["done"].append({"leg": d["leg"], "t": self.t(), "truth": truth, "off_goal_m": off})
                    self.note("traffic_leg", robot=rid, leg=d["leg"], truth=truth, off_goal_m=off)
                    d["leg"], d["posted"], d["navigating"], d["attempts"] = d["leg"] + 1, None, False, 0
                    continue
                # Re-post only when Fleet holds nothing for it and it is not driving: a goal
                # Nav2 aborted (S1: compute_path_to_pose timeouts under load) or never started.
                sim, sim_posted = self.sim_now(), d["posted_sim"]
                slow = sim is None or sim_posted is None or sim - sim_posted >= 5.0
                if queued or nav in ACTIVE_NAV or now - d["posted"] < 30.0 or not slow or d["attempts"] >= 4:
                    continue
            x, y, yaw = goal
            code, body = self.fleet("POST", f"/api/fleet/robots/{rid}/goal", {"x": x, "y": y, "yaw": yaw},
                                    timeout=45.0)     # S2 q0: 15 s timed out at load 150
            d["posted"], d["posted_sim"], d["navigating"] = now, self.sim_now(), False
            d["attempts"] += 1
            tr["posts"].append({"t": self.t(), "robot": rid, "leg": d["leg"], "code": code, "body": body})
            self.note("traffic_goal", robot=rid, leg=d["leg"], code=code, body=body)
        if all(d["leg"] >= len(d["legs"]) for d in tr["drivers"].values()):
            tr["done"] = True
            self.note("traffic_done")

    def traffic_finish(self):
        """After the power-on: let the drivers finish their legs (sim timeout), then record."""
        tr = self.traffic
        if tr is None:
            return True
        _, done = self.wait(lambda s: tr["done"], self.args.traffic_timeout)
        cancels = {}
        if not done:
            # A goal left in Fleet would be released or keep driving during phases c and b.
            for rid in tr["drivers"]:
                cancels[rid] = self.fleet("POST", f"/api/fleet/robots/{rid}/cancel", timeout=15.0)
            self.fleet_at = -math.inf
            self.fleet_state()
            cancels["left_in_fleet"] = {rid: [row.get("goal"), row.get("queued")]
                                        for rid, row in self.fleet_rows.items()
                                        if rid in tr["drivers"] and (row.get("goal") or row.get("queued"))}
            self.note("traffic_cancel", **cancels)
        tr["finished_at"] = self.t()
        self.record["phases"]["traffic"] = {
            "done": done, "homer": tr["homer"], "started": tr["started"], "finished": tr["finished_at"],
            "homer_at_start": tr["homer_at_start"], "posts": tr["posts"], "cancels": cancels,
            "legs": {rid: d["done"] for rid, d in tr["drivers"].items()},
            "planned": {rid: len(d["legs"]) for rid, d in tr["drivers"].items()},
            "homer_localized": self.first_time(tr["homer"], "LOCALIZED"),
            "rtf": self.rtf(), "load": self.load()}
        self.traffic = None
        self.note("traffic_phase_done", done=done)
        return True

    # --- s2c: forced mirror ---------------------------------------------------------------
    def forced_mirror(self):
        target = self.rid(self.sc["mirror"])
        start = self.t()
        truth = self.truth(target) or s1.last_trail_pose(self.trail, target)
        if truth is None:
            self.record["phases"]["mirror"] = {"error": f"no truth for {target}"}
            return False
        x, y, yaw = mirror(truth)
        cov = [0.0] * 36
        cov[0] = cov[7] = 0.05 ** 2
        cov[35] = math.radians(5) ** 2
        payload = ("{header: {frame_id: map}, pose: {pose: {position: {x: %f, y: %f}, orientation: "
                   "{z: %f, w: %f}}, covariance: %s}}" % (x, y, math.sin(yaw / 2), math.cos(yaw / 2), cov))
        sim_start = self.sim_now()
        self.ros_pub(f"/{target}/initialpose", "geometry_msgs/msg/PoseWithCovarianceStamped", payload)
        injected, sim_injected = self.t(), self.sim_now()
        # Any exit from LOCALIZED counts (SUSPECT can turn CANDIDATES between two polls).
        snaps, detected = self.wait(lambda s: self.loc_state(s, target) not in ("LOCALIZED", None),
                                    self.args.detect_window)
        locked = self.verdict(target, snaps)
        self.note("mirror_injected", target=target, detected=detected, locked=locked)
        snaps, done = self.wait(lambda s: self.all_localized(s) and bool(self.left_localized(start, only=target)),
                                self.args.localize_timeout)
        if done:
            snaps, _ = self.wait(lambda s: not self.all_localized(s), 5.0)
        left = self.left_localized(start, only=target)
        phase = {"target": target, "t_pub_start": start, "sim_pub_start": sim_start, "t_injected": injected,
                 "sim_injected": sim_injected, "detected": detected, "target_after_injection": locked,
                 "target_left": left[0] if left else None,
                 "accused": self.left_localized(start, exclude=target),
                 "t_target_localized": self.first_time(target, "LOCALIZED", start), "done": done,
                 "rtf": self.rtf(), "load": self.load(), **{rid: self.verdict(rid, snaps) for rid in self.robots}}
        self.record["phases"]["mirror"] = phase
        self.note("mirror_done", **{k: v for k, v in phase.items() if k != "load"})
        return done

    def all_localized(self, snaps):
        return self.both_localized(snaps)

    def left_localized(self, after, exclude=(), only=None):
        """(t, robot, state, reason) of every non-LOCALIZED state row since `after`, for the
        robots not in `exclude` (or only robot `only`). CORE's `state_stale` rows are skipped."""
        rows = []
        for row in self.timeline:
            loc = row.get("loc") or {}
            rid = row.get("robot")
            if (row["what"] == "state" and row["t"] >= after and rid not in exclude
                    and (only is None or rid == only) and loc.get("state") not in (None, "LOCALIZED")
                    and loc.get("reason") != "state_stale"):     # CORE's wall-time blip, not an accusation
                rows.append((row["t"], row["robot"], loc.get("state"), loc.get("reason")))
        return rows

    # --- s2b: simultaneous re-arbitration -------------------------------------------------
    def simultaneous_pickup(self):
        pk = self.sc["pickup"]
        lifted = [self.rid(i) for i in pk["robots"]]
        start = self.t()
        before = [self.truth(rid) or s1.last_trail_pose(self.trail, rid) or self.sc["spawn"][i]
                  for i, rid in enumerate(self.robots)]
        # Drops and the stale trap from where the robots stand now (traffic may have moved them).
        drops = [drop_layout(before, pk)[i] for i in pk["robots"]]
        problems, trap = drop_problems(before, pk), stale_trap(before, pk)
        self.note("pickup2_layout", drops=drops, problems=problems, stale_trap=trap)

        def all_at_once(active):
            threads = [threading.Thread(target=self.pickup, args=(rid, active)) for rid in lifted]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
        all_at_once(True)
        t_lifted = self.t()
        for rid, drop in zip(lifted, drops):
            self.teleport(rid, drop)
        snaps, _ = self.wait(lambda s: False, 3.0)
        held = {rid: self.loc_state(snaps, rid) for rid in lifted}
        all_at_once(False)
        t_down = self.t()
        snaps, done = self.wait(lambda s: all(self.loc_state(s, r) == "LOCALIZED" for r in lifted),
                                self.args.localize_timeout)
        if done:
            snaps, _ = self.wait(lambda s: not self.all_localized(s), 5.0)
        phase = {"lifted": lifted, "drops": drops, "layout_problems": problems, "stale_trap": trap,
                 "before": before,
                 "t_start": start, "t_lifted": t_lifted, "t_set_down": t_down, "state_while_held": held,
                 "t_localized": {rid: self.first_time(rid, "LOCALIZED", t_down) for rid in lifted},
                 "others_left_localized": self.left_localized(start, exclude=lifted), "done": done,
                 "rtf": self.rtf(), "load": self.load(), **{rid: self.verdict(rid, snaps) for rid in self.robots}}
        self.record["phases"]["pickup2"] = phase
        self.note("pickup2_done", **{k: v for k, v in phase.items() if k not in ("load", "before")})
        return done


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="q")
    p.add_argument("--out", required=True)
    p.add_argument("--traffic", action="store_true", help="s2d: homing in traffic during the power-on")
    p.add_argument("--phases", default="", help="comma list after power-on: c (mirror), b (simultaneous pickup)")
    p.add_argument("--check", action="store_true", help="print the layout checks and exit (no ROS)")
    p.add_argument("--ws", default=str(Path(__file__).resolve().parents[2]))
    p.add_argument("--partition", default="rosy_d395e")
    p.add_argument("--domain", type=int, default=99)
    p.add_argument("--api-port", type=int, default=18940)
    p.add_argument("--fleet-port", type=int, default=18995)
    p.add_argument("--localize-timeout", type=float, default=150.0, help="sim s")
    p.add_argument("--traffic-timeout", type=float, default=120.0, help="sim s after the power-on")
    p.add_argument("--detect-window", type=float, default=30.0, help="(c) sim s to wait for SUSPECT")
    p.add_argument("--min-rtf", type=float, default=0.04, help="wall cap = sim timeout / this")
    p.add_argument("--max-wall", type=float, default=1500.0, help="wall cap of any one wait")
    p.add_argument("--loc-param", action="append", default=[], metavar="NAME=VALUE")
    p.add_argument("--launch-arg", action="append", default=[], metavar="NAME:=VALUE",
                   help="extra gz_multi argument, e.g. nav_composition:=true")
    p.add_argument("--physics-step", type=float, default=None,
                   help="sim-only physics max_step_size in s (gz_multi physics_step), e.g. 0.005")
    p.add_argument("--gpu", action="store_true", help="render the lidars on the WSL GPU (gz_multi gpu:=true)")
    args = p.parse_args(argv)
    args.launch_arg += ([f"physics_step:={args.physics_step}"] if args.physics_step else []) + (
        ["gpu:=true"] if args.gpu else [])
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.check:
        sc = SCENARIOS[args.scenario]
        print(json.dumps({"problems": scenario_problems(sc), "stale_trap": stale_trap(sc["spawn"], sc["pickup"])},
                         indent=1))
        return
    bench = Bench(args)
    try:
        if args.traffic:
            bench.arm_traffic()
        ok = bench.power_on()
        bench.traffic_finish()       # recorded (and left goals cancelled) even after a failed power-on
        for phase in filter(None, args.phases.split(",")):
            if not ok:
                break
            ok = bench.forced_mirror() if phase == "c" else bench.simultaneous_pickup()
    except KeyboardInterrupt:
        bench.note("interrupted")
    finally:
        bench.stop()
        bench.save()


if __name__ == "__main__":
    main()
