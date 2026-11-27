"""The runner's command intake and latest encoder snapshot."""
import os
import time

from chunk_policy_playback import _is_holding, absorb_telemetry_error
from chunk_runner_interrupt import interrupt_tick
from chunk_runner_lease import policy_playing
from chunk_runner_settle import tick_or_report, wait_aligned_before_start


def overload_shed(runner) -> dict:
    """Joints the guard is shedding (overload-hold, torque ON), as its own field; never folded into the hold ack."""
    held = getattr(getattr(getattr(runner, "robot", None), "motion", None), "held", None)
    return {"overload_shed": sorted(held)} if held else {}


def publish_live(runner, *, state=None, best_effort: bool = False) -> None:
    """Atomically emit the latest runner snapshot for `cell_job_api` and observer handoff."""
    if not getattr(runner, "live", None) or getattr(runner, "target", None) is None:
        return
    try:
        pose = state if state is not None else (getattr(runner, "last_present", None) or runner.present())
        runner.live(
            {
                "t": round(time.time(), 3),
                "state": [round(v, 2) for v in pose],
                "target": [round(v, 2) for v in runner.target],
                "chunk": runner.chunk,
                "policy_start": runner.policy_playback.spec["start"] if runner.chunk == "policy" and runner.policy_playback else None,
                "lag": round(runner.lag, 2),
                "fault": runner.fault,
                "holding": _is_holding(runner),
                "human_hold_latched": runner.human_hold_latched,
                "torque_hold_commanded": runner.torque_hold_commanded, **overload_shed(runner),
                **({"policy_lease": runner.lease_watch.status()} if getattr(runner, "lease_watch", None) else {}),
                **({"hold_req": runner._human_hold_acked_req} if getattr(runner, "_human_hold_acked_req", None) else {}),
                "pid": os.getpid(),
                **({"interrupt": runner._interrupt["phase"]} if getattr(runner, "_interrupt", None) else {}),
                "health": runner.health,
                **({"jitter": runner.jitter} if runner.jitter["shaking"] else {}),
            }
        )
    except OSError as error:
        if not best_effort and not absorb_telemetry_error(runner, getattr(runner, "last_present", None), "live write failed", error):
            raise


def finish_recovery_stop(runner, *, state=None) -> None:
    """Clear recovery flags on clean `stop` and flush `live.json` when exiting a recovery flow."""
    flush = bool(getattr(runner, "_recovery_active", False) or getattr(runner, "_recovery_live_flush", False))
    runner._recovery_active = runner._recovery_live_flush = False
    if flush:
        publish_live(runner, state=state, best_effort=True)


def run(runner, lines) -> None:
    """`lines()` returns the commands that arrived since the last call."""
    runner.target = runner.present()
    period = 1.0 / runner.fps
    if not wait_aligned_before_start(runner, lines, period):
        return
    runner.last_input = runner.clock()
    while True:
        started, prev_chunk = runner.clock(), runner.chunk
        try:
            arrived = lines()
        except OSError as error:
            if not absorb_telemetry_error(runner, getattr(runner, "last_present", None), "command intake failed", error):
                raise
            arrived = []
        if arrived:
            runner.last_input, runner.idle_parks, runner._idle_open_at = started, 0, None
        runner.pending += arrived
        hold_lines = [line.strip() for line in runner.pending if line.strip().split()[:1] == ["human-hold"]]
        watch = getattr(runner, "lease_watch", None)  # D-1024 3: a policy runs only on a renewed lease; no renewal is a human-hold
        if watch is not None and watch.poll(policy_playing(runner.chunk)) and not runner.human_hold_latched:
            hold_lines.append("human-hold")
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
            publish_live(runner, best_effort=True)
            return  # interrupted: idle stop and a judge's stop fold give way to interrupt_tick's verdict
        if runner.chunk == "policy" or (prev_chunk == "policy" and runner.chunk is None) or runner.ticks % max(1, runner.fps // 10) == 0:
            publish_live(runner)
        runner.sleep(max(0.0, period - (runner.clock() - started)))
