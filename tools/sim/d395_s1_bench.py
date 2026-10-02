#!/usr/bin/env python3
"""D-395 S1 Gazebo bench driver: 2 robots, CORE + loc_assist + Fleet, zero human input.

Runs inside WSL with ROS 2 Jazzy and the bench workspace sourced. One call is one
power-on: it launches `gz_multi.launch.py` (own GZ_PARTITION / ROS_DOMAIN_ID, its own
process group) and the Fleet console (localization service on, overhead cue off),
waits for both robots to be LOCALIZED, then optionally runs

  d  pickup during a drive: Nav2 goal to r1, teleport r1 mid-drive with
     `safety/pickup` true, set down, expect SUSPECT then re-localization;
  c  forced mirror: inject r2's 180-degree twin straight into its AMCL (test fault),
     watch for detection; then a pickup pulse on r1 (no motion) so r1 re-reports
     candidates and the Fleet monitor gets a peer observation of r2.

Everything is judged against Gazebo ground truth (`gz model -p`, d395_truth.judge).
Only processes this script started are stopped (its process groups, then anything
left carrying its GZ_PARTITION). Output: <out>/run.json, launch.log, fleet.log.

  python3 tools/sim/d395_s1_bench.py --scenario a --out /mnt/x/DevTemp/rosy-d395-s1/a1 --phases d,c
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d395_truth import judge, mirror, parse_gz_model_pose  # noqa: E402

TOKEN = "rosy-dev-operator"          # gz_multi SIM_OPERATOR_TOKEN (ROSY_DEV_AUTH=1 sim cores)
WORLD = "map_v2_fleet"
R1, R2 = "rosy_01", "rosy_02"
HALF_PI = math.pi / 2

#: Spawn (x, y, yaw) per scenario; squares from lane_rules.yaml (A (-1.26, 0.49) axis 90,
#: B (0.86, -0.52) axis 0). The Nav2 map of map_v2_fleet is the outer wall rectangle only.
SCENARIOS = {
    # (a) r1 on square A facing along its axis (down the left lane), r2 off-slot 0.66 m away.
    "a": {"spawn": [(-1.26, 0.49, -HALF_PI), (-0.70, 0.15, math.pi)],
          "goal": (-1.26, 0.05, -HALF_PI), "drop": (-0.20, -0.20, HALF_PI)},
    # (b) r1 on square B facing the other way (-x), r2 on square A.
    "b": {"spawn": [(0.86, -0.52, math.pi), (-1.26, 0.49, HALF_PI)],
          "goal": (0.40, -0.52, math.pi), "drop": (-0.75, 0.30, 0.0)},
    # (d) pickup during a drive that moves: both squares hug the outer wall, where RPP's padded
    # sim footprint reports a collision ahead and never moves (S1 finding 5, re-run a1-a3), so
    # r1 starts off-slot in the open middle and drives 0.4 m south; r2 on square A anchors it.
    "d": {"spawn": [(-0.70, 0.15, math.pi), (-1.26, 0.49, HALF_PI)],
          "goal": (-0.70, -0.25, -HALF_PI), "drop": (-0.75, 0.30, 0.0)},
    # (l) one robot off-slot with no asymmetric cue: only the P2-7 ladder can help.
    "l": {"spawn": [(-0.70, 0.15, math.pi)]},
}


class Bench:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        # Two robots with Nav2 un-composed are ~45 DDS participants. rmw_cyclonedds' localhost
        # profile caps the unicast participant index at 32, so the late joiners (loc_assist)
        # die with "failed to create domain". Raise the cap; the domain stays loopback-only.
        dds = self.out / "cyclonedds_bench.xml"
        dds.write_text('<CycloneDDS xmlns="https://cdds.io/config"><Domain><Discovery>'
                       '<MaxAutoParticipantIndex>120</MaxAutoParticipantIndex></Discovery></Domain>'
                       '</CycloneDDS>\n', encoding="utf-8")
        self.env = dict(os.environ, GZ_PARTITION=args.partition, ROS_DOMAIN_ID=str(args.domain),
                        RMW_IMPLEMENTATION="rmw_cyclonedds_cpp", ROS_AUTOMATIC_DISCOVERY_RANGE="LOCALHOST",
                        CYCLONEDDS_URI=f"file://{dds}")
        self.robots = [f"rosy_{i + 1:02d}" for i in range(len(SCENARIOS[args.scenario]["spawn"]))]
        self.base = {rid: f"http://127.0.0.1:{args.api_port + i}" for i, rid in enumerate(self.robots)}
        self.t0 = time.monotonic()
        self.procs = []
        self.seq = dict.fromkeys(self.robots)
        self.events = []
        self.scores = []
        self.states = dict.fromkeys(self.robots)
        self.missions = dict.fromkeys(self.robots)
        #: (wall t, robot, x, y, yaw) Gazebo truth every ~2 s: mission motion and drift.
        self.trail = []
        self.timeline = []
        self.record = {"scenario": args.scenario, "args": vars(args), "phases": {}}
        #: (wall t, sim s, rtf) every ~2 s: the host may run Gazebo far below real time, so
        #: wall timings are converted to sim seconds afterwards.
        self.clock_samples = []
        self.stopping = threading.Event()
        threading.Thread(target=self.sample_clock, daemon=True).start()

    # --- plumbing -------------------------------------------------------------------
    def t(self):
        return round(time.monotonic() - self.t0, 2)

    def note(self, what, **data):
        row = {"t": self.t(), "what": what, **data}
        self.timeline.append(row)
        print(json.dumps(row), flush=True)

    def spawn(self, cmd, log_name):
        log = open(self.out / log_name, "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, env=self.env, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        self.procs.append(proc)
        self.note("spawned", cmd=cmd[:3], pid=proc.pid, pgid=os.getpgid(proc.pid))
        return proc

    def http(self, rid, method, path, body=None, timeout=2.0):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base[rid] + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {TOKEN}",
                                              "Content-Type": "application/json"})
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

    def run_quiet(self, cmd, timeout=10.0):
        try:
            return subprocess.run(cmd, env=self.env, capture_output=True, text=True, timeout=timeout).stdout
        except subprocess.TimeoutExpired:
            return ""

    def truth(self, rid):
        return parse_gz_model_pose(self.run_quiet(["gz", "model", "-m", rid, "-p"]))

    def rtf(self):
        text = self.run_quiet(["gz", "topic", "-e", "-n", "1", "-t", f"/world/{WORLD}/stats"], 8.0)
        m = re.search(r"real_time_factor:\s*([0-9.eE+-]+)", text)
        return float(m.group(1)) if m else None

    def sample_clock(self):
        while not self.stopping.is_set():
            t = self.t()
            text = self.run_quiet(["gz", "topic", "-e", "-n", "1", "-t", f"/world/{WORLD}/stats"], 8.0)
            sim = re.search(r"sim_time\s*\{\s*sec:\s*(\d+)(?:\s*nsec:\s*(\d+))?", text)
            rtf = re.search(r"real_time_factor:\s*([0-9.eE+-]+)", text)
            if sim:
                self.clock_samples.append((t, int(sim.group(1)) + int(sim.group(2) or 0) * 1e-9,
                                           float(rtf.group(1)) if rtf else None))
            for rid in self.robots:
                pose = self.truth(rid)
                if pose is not None:
                    self.trail.append((t, rid, *pose))
            self.stopping.wait(2.0)

    def load(self):
        return Path("/proc/loadavg").read_text().split()[:3]

    def teleport(self, rid, pose):
        x, y, yaw = pose
        req = (f'name: "{rid}", position: {{x: {x}, y: {y}, z: 0.1}}, '
               f'orientation: {{x: 0, y: 0, z: {math.sin(yaw / 2)}, w: {math.cos(yaw / 2)}}}')
        out = self.run_quiet(["gz", "service", "-s", f"/world/{WORLD}/set_pose", "--reqtype", "gz.msgs.Pose",
                              "--reptype", "gz.msgs.Boolean", "--timeout", "3000", "--req", req])
        self.note("teleport", robot=rid, pose=pose, reply=out.strip())

    def ros_pub(self, topic, msg_type, payload):
        out = self.run_quiet(["ros2", "topic", "pub", "--once", "-w", "1", topic, msg_type, payload], 20.0)
        self.note("ros_pub", topic=topic, payload=payload[:120], ok="publishing" in out)

    def pickup(self, rid, active):
        self.ros_pub(f"/{rid}/safety/pickup", "std_msgs/msg/Bool", "{data: %s}" % ("true" if active else "false"))

    # --- observation ----------------------------------------------------------------
    def poll(self):
        """One poll: state of both robots, new localization events, scores for CANDIDATES."""
        snaps = {}
        for rid in self.robots:
            code, state = self.http(rid, "GET", "/api/v1/robot/state")
            snaps[rid] = state if code == 200 else None
            loc = (state or {}).get("localization") if code == 200 else None
            key = None if loc is None else (loc.get("state"), loc.get("reason"), loc.get("pose_frame"))
            if key != self.states[rid]:
                self.note("state", robot=rid, loc=loc, pose=(state or {}).get("pose"))
                self.states[rid] = key
            self.pull_events(rid)
            code, mission = self.http(rid, "GET", "/api/v1/localization/mission")
            mission = mission if code == 200 else None
            if mission != self.missions[rid]:      # P2-7 ladder missions (rotate, lane_to_stopline)
                self.note("mission", robot=rid, code=code, mission=mission, truth=self.truth(rid))
                self.missions[rid] = mission
        for rid in self.robots:
            loc = (snaps[rid] or {}).get("localization") or {}
            if loc.get("state") == "CANDIDATES":
                self.score(rid, snaps)
        return snaps

    def pull_events(self, rid):
        since = self.seq[rid]
        path = "/api/v1/events?limit=200" + ("" if since is None else f"&since_seq={since}")
        code, body = self.http(rid, "GET", path)
        if code != 200 or not body:
            return
        for ev in body.get("events", []):
            if str(ev.get("type", ev.get("name", ""))).startswith("localization") or "localization" in json.dumps(
                    ev.get("source", "")):
                row = {"t": self.t(), "robot": rid, "event": ev}
                self.events.append(row)
                if since is not None:
                    print(json.dumps({"t": row["t"], "robot": rid, "type": ev.get("type"),
                                      "data": ev.get("data")}), flush=True)
        self.seq[rid] = body.get("last_seq", since)

    def score(self, rid, snaps):
        """What the arbiter sees: the same `score()` with the service's context (no overhead)."""
        from core_common.protocol.localization import CandidateReport
        from fleet.localization import arbiter, service_logic, trust
        code, body = self.http(rid, "GET", "/api/v1/localization/candidates")
        if code != 200:
            return
        report = CandidateReport.model_validate(body)
        peers = []
        for other, snap in snaps.items():
            if other != rid and snap and trust.classify(snap) == trust.TRUSTED and snap.get("pose"):
                peers.append((float(snap["pose"]["x"]), float(snap["pose"]["y"])))
        rules = self.lane_rules()
        slots, squares = service_logic.parse_reference_squares(rules)
        rows = arbiter.score(report, arbiter.Context(peers=peers, slots=slots, squares=squares),
                             time.monotonic())
        totals = sorted((r["total"] for r in rows), reverse=True)
        self.scores.append({"t": self.t(), "robot": rid, "request_id": report.request_id,
                            "stamp": report.stamp, "pickup": report.pickup,
                            "candidates": [c.model_dump() for c in report.candidates],
                            "objects": [o.model_dump() for o in report.unmapped_objects],
                            "rows": [{k: round(v, 3) for k, v in r.items()} for r in rows],
                            "gap": round(totals[0] - totals[1], 3) if len(totals) > 1 else None})

    _rules = None

    def lane_rules(self):
        if self._rules is None:
            import yaml
            path = Path(self.args.ws) / "src/runtime/sensing/map/map_v2_fleet/lane_rules.yaml"
            self._rules = yaml.safe_load(path.read_text(encoding="utf-8"))
        return self._rules

    def loc_state(self, snaps, rid):
        return ((snaps.get(rid) or {}).get("localization") or {}).get("state")

    def wait(self, until, timeout_s, period=0.5):
        end = time.monotonic() + timeout_s
        snaps = {}
        while time.monotonic() < end:
            dead = [p.pid for p in self.procs if p.poll() is not None]
            if dead:
                raise RuntimeError(f"launched process exited: {dead}")
            snaps = self.poll()
            if until(snaps):
                return snaps, True
            time.sleep(period)
        return snaps, False

    def verdict(self, rid, snaps):
        pose = (snaps.get(rid) or {}).get("pose")
        truth = self.truth(rid)
        if not pose or truth is None:
            return {"state": self.loc_state(snaps, rid), "pose": pose, "truth": truth, "ok": False,
                    "mirror": None}
        reported = (float(pose["x"]), float(pose["y"]), float(pose.get("yaw", 0.0)))
        return {"state": self.loc_state(snaps, rid), "pose": reported, "truth": truth,
                **judge(reported, truth)}

    def both_localized(self, snaps):
        return all(self.loc_state(snaps, rid) == "LOCALIZED" for rid in self.robots)

    def first_time(self, rid, state, after=0.0):
        for row in self.timeline:
            if (row["what"] == "state" and row.get("robot") == rid and row["t"] >= after
                    and (row.get("loc") or {}).get("state") == state):
                return row["t"]
        return None

    # --- phases ---------------------------------------------------------------------
    def power_on(self):
        sc = SCENARIOS[self.args.scenario]
        poses = ";".join(f"{x},{y},{yaw}" for x, y, yaw in sc["spawn"])
        self.record["load_before"] = self.load()
        self.spawn(["ros2", "launch", "gz_sim", "gz_multi.launch.py", f"robots:={len(self.robots)}",
                    f"world_name:={WORLD}.world", "mode:=nav", "core:=true", "headless:=true",
                    "loc_assist:=true", "seed_initialpose:=false", f"api_port_base:={self.args.api_port}",
                    f"spawn_poses:={poses}"], "launch.log")
        manifest = None
        for _ in range(240):
            m = re.search(r"fleet robots\.yaml: (\S+)", (self.out / "launch.log").read_text(errors="replace"))
            if m:
                manifest = m.group(1)
                break
            time.sleep(1)
        if manifest is None:
            raise RuntimeError("no robots.yaml in launch.log")
        boot = ("import logging, sys; logging.basicConfig(level=logging.INFO, "
                "format='%(asctime)s %(name)s %(levelname)s %(message)s'); "
                "from fleet.cli import main; main(sys.argv[1:])")
        self.spawn([sys.executable, "-c", boot, "console", "--robots", manifest, "--port",
                    str(self.args.fleet_port), "--localization-lane-rules",
                    str(Path(self.args.ws) / "src/runtime/sensing/map/map_v2_fleet/lane_rules.yaml")],
                   "fleet.log")
        self.note("power_on", spawn=sc["spawn"], load=self.load())
        for item in self.args.loc_param:     # tuning runs: loc_assist parameters read per call
            threading.Thread(target=self.set_loc_param, args=tuple(item.split("=", 1)), daemon=True).start()
        snaps, done = self.wait(self.both_localized, self.args.localize_timeout)
        if done:   # settle: hold LOCALIZED 5 s, then judge
            snaps, _ = self.wait(lambda s: not self.both_localized(s), 5.0)
        phase = {"done": done, "rtf": self.rtf(), "load": self.load()}
        for rid in self.robots:
            phase[rid] = {"t_state": self.first_any_state(rid), "t_candidates": self.first_time(rid, "CANDIDATES"),
                          "t_localized": self.first_time(rid, "LOCALIZED"), **self.verdict(rid, snaps)}
        self.record["phases"]["power_on"] = phase
        self.note("power_on_done", **{k: v for k, v in phase.items() if k in (*self.robots, "done")})
        return done

    def set_loc_param(self, name, value):
        """`ros2 param set` on every loc_assist node as soon as it exists (races the first search)."""
        for rid in self.robots:
            while not self.stopping.is_set():
                out = self.run_quiet(["ros2", "param", "set", f"/{rid}/loc_assist", name, value], 30.0)
                if "Set parameter successful" in out:
                    self.note("loc_param", robot=rid, name=name, value=value)
                    break
                self.stopping.wait(2.0)

    def first_any_state(self, rid):
        for row in self.timeline:
            if row["what"] == "state" and row.get("robot") == rid and row.get("loc"):
                return row["t"]
        return None

    def pickup_during_drive(self):
        sc = SCENARIOS[self.args.scenario]
        start = self.t()
        before = self.truth(R1)
        x, y, yaw = sc["goal"]
        moved, codes, sent_at = False, [], -math.inf
        end = time.monotonic() + self.args.drive_timeout
        while time.monotonic() < end:
            self.poll()
            now = self.truth(R1)
            if before and now and math.dist(before[:2], now[:2]) >= 0.04:
                moved = True
                break
            # A goal is refused (409 NOT_LOCALIZED) or cancelled whenever CORE's state reads
            # stale; resend every 5 s until the robot moves.
            if time.monotonic() - sent_at >= 5.0:
                code, body = self.http(R1, "POST", "/api/v1/navigation/goal", {"x": x, "y": y, "yaw": yaw})
                codes.append(code)
                sent_at = time.monotonic()
                self.note("goal", code=code, body=body)
            time.sleep(0.5)
        code = codes
        self.note("drive", moved=moved, truth=self.truth(R1))
        self.pickup(R1, True)
        time.sleep(0.5)
        self.teleport(R1, sc["drop"])
        held_a = self.truth(R1)
        snaps, _ = self.wait(lambda s: False, 3.0)
        held_b = self.truth(R1)
        halt = None if not (held_a and held_b) else round(math.dist(held_a[:2], held_b[:2]), 4)
        state_held = self.loc_state(snaps, R1)
        self.pickup(R1, False)
        t_down = self.t()
        snaps, done = self.wait(lambda s: self.loc_state(s, R1) == "LOCALIZED", self.args.localize_timeout)
        if done:
            snaps, _ = self.wait(lambda s: self.loc_state(s, R1) != "LOCALIZED", 5.0)
        phase = {"done": done, "goal_code": code, "moved": moved, "drift_while_held_m": halt,
                 "state_while_held": state_held, "t_suspect": self.first_time(R1, "SUSPECT", start),
                 "t_set_down": t_down, "t_localized": self.first_time(R1, "LOCALIZED", t_down),
                 "rtf": self.rtf(), "load": self.load(), R1: self.verdict(R1, snaps), R2: self.verdict(R2, snaps)}
        self.record["phases"]["pickup"] = phase
        self.note("pickup_done", **{k: v for k, v in phase.items() if k not in ("load",)})
        return done

    def forced_mirror(self):
        start = self.t()
        truth = self.truth(R2)
        if truth is None:
            self.record["phases"]["mirror"] = {"error": "no truth for r2"}
            return False
        x, y, yaw = mirror(truth)
        cov = [0.0] * 36
        cov[0] = cov[7] = 0.05 ** 2
        cov[35] = math.radians(5) ** 2
        payload = ("{header: {frame_id: map}, pose: {pose: {position: {x: %f, y: %f}, orientation: "
                   "{z: %f, w: %f}}, covariance: %s}}" % (x, y, math.sin(yaw / 2), math.cos(yaw / 2), cov))
        self.ros_pub(f"/{R2}/initialpose", "geometry_msgs/msg/PoseWithCovarianceStamped", payload)
        snaps, detected = self.wait(lambda s: self.loc_state(s, R2) == "SUSPECT", 60.0)
        locked = self.verdict(R2, snaps)
        self.note("mirror_injected", detected_alone=detected, r2=locked)
        # Step 2: a pickup pulse on r1 (no motion) makes r1 report candidates, so the
        # Fleet monitor gets a peer observation of r2 (D-395 rev. 4 §5).
        pulse = self.t()
        self.pickup(R1, True)
        time.sleep(1.0)
        self.pickup(R1, False)
        snaps, done = self.wait(lambda s: self.both_localized(s) and self.r2_left_localized(start),
                                self.args.localize_timeout)
        if done:
            snaps, _ = self.wait(lambda s: not self.both_localized(s), 5.0)
        phase = {"detected_without_peer_report": detected, "r2_after_injection": locked,
                 "t_pulse": pulse, "t_r2_suspect": self.first_time(R2, "SUSPECT", start),
                 "t_r1_localized": self.first_time(R1, "LOCALIZED", pulse),
                 "t_r2_localized": self.first_time(R2, "LOCALIZED", pulse), "done": done,
                 "rtf": self.rtf(), "load": self.load(),
                 R1: self.verdict(R1, snaps), R2: self.verdict(R2, snaps)}
        self.record["phases"]["mirror"] = phase
        self.note("mirror_done", **{k: v for k, v in phase.items() if k not in ("load",)})
        return done

    def r2_left_localized(self, after):
        return self.first_time(R2, "SUSPECT", after) is not None

    # --- teardown -------------------------------------------------------------------
    def stop(self):
        self.stopping.set()
        for proc in reversed(self.procs):
            for sig, grace in ((signal.SIGINT, 15), (signal.SIGTERM, 5), (signal.SIGKILL, 2)):
                try:
                    os.killpg(proc.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    proc.wait(grace)
                    break
                except subprocess.TimeoutExpired:
                    continue
        # gz sim server and its children keep our GZ_PARTITION; nothing else does.
        mine = f"GZ_PARTITION={self.args.partition}".encode()
        left = []
        for env in Path("/proc").glob("[0-9]*/environ"):
            try:
                if mine in env.read_bytes().split(b"\0") and int(env.parent.name) != os.getpid():
                    left.append(int(env.parent.name))
            except (OSError, ValueError):
                continue
        for pid in left:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.note("stopped", leftover_killed=left)

    def save(self):
        self.record.update(timeline=self.timeline, events=self.events, scores=self.scores,
                           search_s=self.search_times(), clock=self.clock_samples, trail=self.trail)
        (self.out / "run.json").write_text(json.dumps(self.record, indent=1, default=str), encoding="utf-8")

    def search_times(self):
        text = (self.out / "launch.log").read_text(errors="replace") if (self.out / "launch.log").exists() else ""
        return [{"robot": m.group(1), "s": float(m.group(2)), "n": int(m.group(3))}
                for m in re.finditer(r"\[(rosy_0\d)\.loc_assist\]: candidate search ([0-9.]+) s .*?: (\d+) candidates",
                                     text)]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--phases", default="", help="comma list after power-on: d (pickup), c (mirror)")
    p.add_argument("--ws", default=str(Path(__file__).resolve().parents[2]))
    p.add_argument("--partition", default="rosy_d395")
    p.add_argument("--domain", type=int, default=93)
    p.add_argument("--api-port", type=int, default=18930)
    p.add_argument("--fleet-port", type=int, default=18990)
    p.add_argument("--localize-timeout", type=float, default=240.0)
    p.add_argument("--drive-timeout", type=float, default=180.0)
    p.add_argument("--loc-param", action="append", default=[], metavar="NAME=VALUE",
                   help="tuning: set a loc_assist parameter on both robots after launch")
    args = p.parse_args(argv)
    bench = Bench(args)
    try:
        ok = bench.power_on()
        for phase in filter(None, args.phases.split(",")):
            if not ok:
                break
            ok = bench.pickup_during_drive() if phase == "d" else bench.forced_mirror()
    except KeyboardInterrupt:
        bench.note("interrupted")
    finally:
        bench.stop()
        bench.save()


if __name__ == "__main__":
    main()
