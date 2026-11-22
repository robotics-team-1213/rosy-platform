"""The runner's command intake and latest encoder snapshot."""
import os
import time

from chunk_policy_playback import absorb_telemetry_error
from chunk_runner_interrupt import interrupt_tick
from chunk_runner_settle import tick_or_report, wait_aligned_before_start


def run(runner, lines) -> None:
    """`lines()` returns the commands that arrived since the last call."""
    runner.target = runner.present()
    period = 1.0 / runner.fps
    if not wait_aligned_before_start(runner, lines, period):
        return
    runner.last_input = runner.clock()
    while True:
        started = runner.clock()
        try:
            arrived = lines()
        except OSError as error:
            if not absorb_telemetry_error(runner, getattr(runner, "last_present", None), "command intake failed", error):
                raise
            arrived = []
        if arrived:
            runner.last_input, runner.idle_parks = started, 0
        runner.pending += arrived
        hold_lines = [line.strip() for line in runner.pending if line.strip().split()[:1] == ["human-hold"]]
        if getattr(runner, "signals", None):  # interrupt first: it folds or holds, while a FIFO human-hold still forces HOLD
            if hold_lines:
                runner._fifo_hold_seen = hold_lines[-1]
                hold_words = hold_lines[-1].split()
                if len(hold_words) <= 2:
                    runner._human_hold_req, runner._human_hold_ack_pending, runner._human_hold_acked_req = (
                        hold_words[1] if len(hold_words) == 2 else None), True, None
            runner.pending.clear()
        if hold_lines or (getattr(runner, "_fifo_hold_seen", False) and not getattr(runner, "signals", None) and not runner.human_hold_latched):
            hold_cmd = hold_lines[-1] if hold_lines else (runner._fifo_hold_seen if isinstance(runner._fifo_hold_seen, str) else "human-hold")
            runner.pending.clear()  # preempt even a queued stop or park
            runner.command(hold_cmd)
        while (
            len(runner.pending) > 1
            and runner.pending[0].strip().split()[:1] in (["state"], ["episode"])
            and runner.pending[1].strip().split()[:1] != ["state"]
        ):
            if (
                not runner.command(runner.pending.pop(0))
                and not getattr(runner, "signals", None)
                and not runner.human_hold_latched
            ):
                return
        if runner.pending and not getattr(runner, "_stop_after_park", None) and not runner.command(runner.pending.pop(0)):
            if not getattr(runner, "signals", None) and not runner.human_hold_latched:  # interrupted: only interrupt_tick ends the run
                return
        if interrupt_tick(runner, f"run {runner.chunk}" if runner.chunk else "tick", tick_or_report):
            return
        if (
            not getattr(runner, "signals", None)
            and not runner.human_hold_latched
            and ((getattr(runner, "_stopped", False) and getattr(runner, "_park_settled", False)) or runner.idle())
        ):
            return  # interrupted: idle stop and a judge's stop fold give way to interrupt_tick's verdict
        if runner.live and (runner.chunk == "policy" or runner.ticks % max(1, runner.fps // 10) == 0):
            try:
                runner.live(
                    {
                        "t": round(time.time(), 3),
                        "state": [round(v, 2) for v in (getattr(runner, "last_present", None) or runner.present())],
                        "target": [round(v, 2) for v in runner.target],
                        "chunk": runner.chunk,
                        "policy_start": runner.policy_playback.spec["start"] if runner.chunk == "policy" and runner.policy_playback else None,
                        "lag": round(runner.lag, 2),
                        "fault": runner.fault,
                        "human_hold_latched": runner.human_hold_latched,
                        "torque_hold_commanded": runner.torque_hold_commanded,
                        **({"hold_req": runner._human_hold_acked_req} if getattr(runner, "_human_hold_acked_req", None) else {}),
                        **({"interrupt": runner._interrupt["phase"], "pid": os.getpid()} if getattr(runner, "_interrupt", None) else {}),
                        "health": runner.health,
                        **({"jitter": runner.jitter} if runner.jitter["shaking"] else {}),
                    }
                )
            except OSError as error:
                if not absorb_telemetry_error(runner, getattr(runner, "last_present", None), "live write failed", error):
                    raise
        runner.sleep(max(0.0, period - (runner.clock() - started)))
