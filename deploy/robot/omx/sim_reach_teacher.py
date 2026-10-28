"""Scripted teacher for the ``rosy.omx-sim-reach-task.v1`` reach task over Pilot SIM HTTP.

Runs against an already running, isolated Pilot Gazebo container (``compose.pilot-sim.yaml``). No
ROS import; prints no pairing code or token. Per episode ``k`` (seed = start_sampling.seed + k):

  1. unrecorded reset: bounded round-robin jogs to the sampled start pose (no recording active);
  2. POST /recordings;
  3. greedy jogs (``sim_reach_task.next_jog``): one joint, |delta| <= jog_step_rad, the task's single
     jog_duration_s, until every checked joint is within tolerance or max_steps; each goal must end
     SUCCEEDED with the readback moved by delta (0.01 rad), otherwise the episode ends there;
  4. a short tail of frames, then stop with task_outcome decided from the final joint readback
     against the target (judge ``sim_joint_readback``), never from the teacher's own plan.

A failed goal is never retried: the episode is stopped as ``failure`` and the run ends (exit 2),
since the owner may be holding. The only resend is Probe._post's single pre-acceptance resend for a
stale state sequence, counted per episode as ``resends``. The seat lease is renewed in a background
thread; a renewal error ends the run before any outcome is sent. The results file is rewritten after
every episode and doubles as the teacher baseline for the closed-loop evaluator.

Usage: sim_reach_teacher.py --task TASK.json --episodes N --out RESULTS.json [container|--inside]
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_pilot_sim_http import BASE, Probe, pairing_code, request  # noqa: E402
import sim_reach_task  # noqa: E402

RESULTS_SCHEMA = "rosy.omx-sim-reach-teacher-results.v1"
READBACK_TOLERANCE_RAD = 0.01   # same per-jog readback check as probe_pilot_sim_http.run_jog
RESET_TOLERANCE_RAD = 0.005
RESET_MAX_JOGS = 400
TAIL_FRAMES = 10                # 1 s at the recorder's 10 fps, holding the last target


class RunAborted(RuntimeError):
    """The run cannot continue (failed goal, lost lease, unready owner)."""


class Teacher:
    def __init__(self, probe: Probe, task: dict, *, renewal_errors: list, log=print,
                 tail_frames: int = TAIL_FRAMES, poll_s: float = 0.1, tail_timeout_s: float = 15.0) -> None:
        self.probe, self.task, self.log = probe, task, log
        self.renewal_errors = renewal_errors
        self.tail_frames, self.poll_s, self.tail_timeout_s = tail_frames, poll_s, tail_timeout_s
        self.resends = 0
        self.current: dict | None = None
        probe.log = self._probe_log

    def _probe_log(self, line: str) -> None:
        if line.startswith("retry_after="):
            self.resends += 1
        self.log(line)

    def check_lease(self) -> None:
        if self.renewal_errors:
            raise RunAborted(f"seat renewal failed: {self.renewal_errors[0]}")

    def recording(self) -> dict:
        return self.probe.call("/recordings")

    def jog(self, joint: str, delta: float) -> tuple[bool, dict, str]:
        """One bounded jog with readback verification: (ok, positions after, reason)."""
        self.check_lease()
        before = self.probe.ready_state()["positions"][joint]
        try:
            result = self.probe.run_jog(joint, delta, duration_s=self.task["jog_duration_s"], check=False)
        except RuntimeError as exc:   # refused (HTTP 409) or no terminal state: a failed goal
            self.check_lease()
            return False, self.probe.call("/state")["positions"], f"goal_error:{exc}"
        goal, positions = result["goal"], result["state"]["positions"]
        if goal["state"] != "SUCCEEDED":
            return False, positions, f"goal_{goal['state']}:{goal.get('reason', '')}"
        moved = positions.get(joint, before) - before
        if abs(moved - delta) > READBACK_TOLERANCE_RAD:
            return False, positions, f"readback_mismatch:{joint}:sent={delta:.4f}:moved={moved:.4f}"
        return True, positions, ""

    def reset(self, start: dict[str, float]) -> dict:
        """Unrecorded reset to ``start``; refuses while a recording is active."""
        if self.recording()["status"] == "recording":
            raise RunAborted("a recording is active; the reset must not be recorded")
        step = self.task["jog_step_rad"]
        for _ in range(RESET_MAX_JOGS):
            positions = self.probe.ready_state()["positions"]
            pending = {name: value - positions[name] for name, value in start.items()
                       if abs(value - positions[name]) > RESET_TOLERANCE_RAD}
            if not pending:
                return positions
            for name, error in pending.items():
                delta = round(min(abs(error), step) * (1 if error > 0 else -1), 6)
                ok, _, reason = self.jog(name, delta)
                if not ok:
                    raise RunAborted(f"reset jog failed: {reason}")
        raise RunAborted("reset pose not reached")

    def wait_ready_capture(self, timeout_s: float = 60.0) -> None:
        until = time.monotonic() + timeout_s
        while time.monotonic() < until:
            self.check_lease()
            if self.probe.call("/state")["ready"] and self.probe.call("/camera")["fresh"]:
                return
            time.sleep(self.poll_s)
        raise RunAborted("owner or camera not ready for recording")

    def tail(self, frames_at_last_jog: int) -> dict:
        """Let the recorder take ``tail_frames`` more frames holding the last target."""
        until = time.monotonic() + self.tail_timeout_s
        current = self.recording()
        while time.monotonic() < until and current["status"] == "recording":
            if current["frame_count"] >= frames_at_last_jog + self.tail_frames:
                break
            time.sleep(self.poll_s)
            self.check_lease()
            current = self.recording()
        return current

    def episode(self, index: int) -> dict:
        task = self.task
        seed = sim_reach_task.episode_seed(task, index)
        start = sim_reach_task.sample_start(task, seed)
        record = {"index": index, "seed": seed, "start_target": start, "judge": sim_reach_task.JUDGE,
                  "success": False, "steps": 0, "reason": "", "recording": None}
        self.resends = 0
        self.current = record
        record["start_readback"] = {k: round(v, 6) for k, v in self.reset(start).items()}
        self.wait_ready_capture()
        text = f"{task['task_id']}: reach the fixed target joint pose (judge: {sim_reach_task.JUDGE})"
        started = self.probe.call("/recordings", method="POST", body={"seat_id": self.probe.seat, "task": text})
        episode_id = started["episode_id"]
        record["recording"] = {"episode_id": episode_id}
        goal_failure = ""
        positions = self.probe.ready_state()["positions"]
        while record["steps"] < task["max_steps"]:
            planned = sim_reach_task.next_jog(task, positions)
            if planned is None:
                break
            ok, positions, reason = self.jog(*planned)
            record["steps"] += 1
            if not ok:
                goal_failure = reason
                break
        current = self.recording()
        if current["status"] == "recording" and not goal_failure:
            current = self.tail(current["frame_count"])
        self.check_lease()
        final = self.probe.call("/state")["positions"]
        reached = sim_reach_task.within_tolerance(task, final)
        record["final_positions"] = {k: round(v, 6) for k, v in final.items()}
        record["errors_rad"] = {k: round(v, 6) for k, v in sim_reach_task.errors_to_target(task, final).items()}
        record["success"] = bool(reached and not goal_failure)
        record["reason"] = goal_failure or ("" if reached else "max_steps_without_reaching_tolerance")
        outcome = "success" if record["success"] else "failure"
        closed = self.probe.call(f"/recordings/{episode_id}/stop", method="POST",
                                 body={"seat_id": self.probe.seat, "outcome": outcome})
        record["recording"] = {"episode_id": episode_id, "status": closed["status"],
                               "issues": list(closed.get("issues", [])), "frame_count": closed["frame_count"],
                               "task_outcome": closed.get("task_outcome", outcome)}
        record["resends"] = self.resends
        self.log(f"episode={index} seed={seed} steps={record['steps']} success={record['success']} "
                 f"recording={closed['status']} issues={record['recording']['issues']} reason={record['reason']}")
        if goal_failure:
            record["aborts_run"] = True
        return record


def write_results(path: Path, results: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(results, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def run(probe: Probe, task: dict, *, episodes: int, first_index: int, out: Path, renewal_errors: list,
        log=print, **teacher_options) -> int:
    offered = {joint["name"]: (joint["lower"], joint["upper"]) for joint in (probe.jog or {}).get("joints", [])}
    if probe.jog is None or float(probe.jog["max_step_rad"]) < task["jog_step_rad"]:
        raise RunAborted("target offers no joint_jog control or a smaller max_step_rad than the task")
    sim_reach_task.validate_task(task, offered)
    teacher = Teacher(probe, task, renewal_errors=renewal_errors, log=log, **teacher_options)
    results = {"schema": RESULTS_SCHEMA, "task_id": task["task_id"],
               "task_sha256": sim_reach_task.task_sha256(task), "task": task, "judge": sim_reach_task.JUDGE,
               "instance_id": probe.target.get("instance_id"), "started_wall_time_ns": time.time_ns(),
               "episodes": [], "aborted": None}
    write_results(out, results)
    try:
        for index in range(first_index, first_index + episodes):
            record = teacher.episode(index)
            results["episodes"].append(record)
            write_results(out, results)
            if record.get("aborts_run"):
                results["aborted"] = f"episode {index}: {record['reason']}"
                return 2
        return 0
    except RuntimeError as exc:   # RunAborted, or an unready owner / HTTP error outside a goal
        reason = f"seat renewal failed: {renewal_errors[0]}" if renewal_errors else str(exc)
        results["aborted"] = reason
        if teacher.current is not None and teacher.current not in results["episodes"]:
            teacher.current["reason"] = teacher.current["reason"] or f"aborted: {reason}"
            results["episodes"].append(teacher.current)   # never success: no outcome was sent
        return 2
    finally:
        write_results(out, results)


def main(argv: list[str] | None = None, *, base: str = BASE, code: str | None = None,
         renew_interval_s: float = 0.8, **teacher_options) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("container", nargs="?", default="rosy-omx-pilot-sim")
    parser.add_argument("--inside", action="store_true", help="run inside the container (no docker exec)")
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--episodes", type=int, required=True)
    parser.add_argument("--first-index", type=int, default=0, help="episode index k (seed = task seed + k)")
    parser.add_argument("--out", type=Path, required=True, help="teacher results JSON (new or overwritten)")
    parser.add_argument("--port", type=int, help="Pilot HTTP port on 127.0.0.1 (OMX_PILOT_PORT; default 8088)")
    args = parser.parse_args(argv)
    if args.port is not None:
        base = f"http://127.0.0.1:{args.port}/api/v1/sim/omx"
    if not 1 <= args.episodes <= 1000 or args.first_index < 0:
        parser.error("--episodes must be 1..1000 and --first-index >= 0")
    task = sim_reach_task.load_task(args.task)
    container = "--inside" if args.inside else args.container
    deadline = time.monotonic() + 600
    code = code or pairing_code(container, deadline)
    while True:   # a freshly (re)started server writes the code before it serves HTTP
        try:
            request("/target", base=base)
            break
        except OSError:
            if time.monotonic() > deadline:
                raise RuntimeError("Pilot HTTP target did not become available") from None
            time.sleep(1)
    token = request("/pair", method="POST", body={"code": code}, base=base)["token"]
    code = None
    seat = request("/seat", method="POST", token=token, base=base)["seat_id"]
    stop, renewal_errors = threading.Event(), []

    def renew():
        while not stop.wait(renew_interval_s):
            try:
                request(f"/seat/{seat}", method="PUT", token=token, base=base)
            except Exception as exc:   # any error ends the run: the lease is not proven
                renewal_errors.append(str(exc))
                stop.set()

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        probe = Probe(token, seat, base=base, stop=stop)
        return run(probe, task, episodes=args.episodes, first_index=args.first_index, out=args.out,
                   renewal_errors=renewal_errors, **teacher_options)
    finally:
        stop.set()
        thread.join(timeout=11)
        try:
            request(f"/seat/{seat}", method="DELETE", token=token, base=base)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"teacher failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
