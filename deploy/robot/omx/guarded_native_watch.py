"""Off-loop watch for a declared record-loop pause (guarded_native_watch.py).

lerobot saves and encodes an episode between two record loops, so for tens of seconds nothing calls the guard: the arm holds its last command with
torque ON and nobody samples it (MotorHealth only samples from inside the control loop). ONE BoundaryWatch per session (one or both arms, read in
sequence by one thread, which also performs any cut: the watch and the cut never overlap on a bus) runs for exactly that pause: started when a record
loop returns, stopped and verified ended before the next one runs. About 2 Hz it reads hardware error, temperature against the motor's limit and
Present_PWM against 90 % of the cap.
The ONLY torque cuts are conditions true in a single sample read from the motor: the hardware error bit, or temperature at/over its limit (through the
guard's fault path; bimanual: both arms, as the running loop's send() does). Everything else is fail closed (guard failed = no new motion, torque kept
on every arm, on_expire asks the session to end the way a user stop does, the reason reported): a pause past BOUNDARY_MAX_S, a status read that failed
after its retries (read_failure), and PWM at the cap for HOLD_S of this watch's own samples (pause_saturated). A thread that can be delayed must never
decide by timing that a healthy extended arm loses its torque. The running loop keeps its own HOLD_S saturation rule unchanged while it runs; the pause
neither extends nor shortens it, and on resume the loop's saturation clock starts fresh (restart_after_pause).
"""
from __future__ import annotations

import threading
import time

from guarded_device import HOLD_S, READ_RETRY, boundary_over, torque_off


class WatchReadFailed(RuntimeError):
    """A watch read failed after its retries: unknown, not a fault."""


class BoundaryWatch:
    def __init__(self, motions, on_fault=None, on_expire=None, period_s=0.5, clock=time.monotonic):
        self.motions = list(motions) if isinstance(motions, (list, tuple)) else [motions]
        self.motion = self.motions[0]
        self.on_fault, self.on_expire, self.period_s, self.clock = on_fault, on_expire, period_s, clock
        self.began, self.saturated, self.temperature_limits, self.expired = clock(), {}, {}, False
        self.read_failure = None  # a status read that failed (after retries): the session ends with torque kept, nothing is cut for it
        self.pause_saturated = None  # PWM at the cap for HOLD_S of this watch's samples: the same fail-closed ending, nothing is cut for it
        self.fault_exc = None  # what the thread's last read found: a fault is never dropped, and control is not handed back over it
        starts = [m.last_time for m in self.motions if getattr(m, "last_time", None) is not None]
        self.start_time = min(starts) if starts else None  # the boundary's ONE start: the last committed command, the same value the guard judges
        self.motion_clock = getattr(self.motion, "clock", clock)  # and the guard's clock, so a hand-back is judged exactly as its first command
        self._halt, self._thread = threading.Event(), None
        self._cut = set()  # motions this watch already cut (bimanual: only the arm the fault was read from); the others stay watched

    def start(self):
        self._thread = threading.Thread(target=self._run, name="boundary-watch", daemon=True)
        self._thread.start()

    def stop(self) -> bool:
        """True once the thread has really ended AND the bound was judged for this pause (the same expire() the tick uses, from the pause's own
        start time): control handed back after an over-bound pause meets a failed guard, never the stale guard's torque cut. False: the thread is
        still running, so the caller must neither resume control nor touch the bus. A fault the thread found (even in a read that was in flight when
        this was called) is already applied (failed flag, cut) and stays in fault_exc: control resumes only when that is None."""
        self._halt.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(2.0)
            if thread.is_alive():
                return False
        if not self.expired and self._over(self.motion_clock()):
            self.expire()
        return True

    def _over(self, now):
        return boundary_over(self.began if self.start_time is None else self.start_time, now)

    def _run(self):
        while not self._halt.wait(self.period_s):
            try:
                self.check(self.clock())
            except BaseException as exc:  # noqa: BLE001  a failed watch is a fault: nothing watched the arm
                self.fault_exc = exc  # also when stop() was called while this read was in flight: stop() joins the thread, so the cut is done
                motion = getattr(exc, "motion", None)  # the arm the confirmed condition was read from
                self.fault(exc, motion)  # and the verdict recorded before it returns, and the loop sees fault_exc
                if motion is None or len(self.motions) < 2:
                    return
                self._cut.add(id(motion))  # in the pause only THAT arm is cut; the other one is held (failed, torque kept) and stays watched
                if not self.expired:
                    self.expire()

    def fault(self, exc, motion=None):
        try:
            if self.on_fault is not None:
                self.on_fault(exc) if motion is None else self.on_fault(exc, motion)
                return
            for motion in self.motions:
                motion.failed = True
                try:
                    torque_off(motion.follower)
                finally:
                    motion.report_fault(exc)
        except BaseException:  # noqa: BLE001  the cut was tried; the next command finds the failed flag
            pass

    def expire(self):
        self.expired = True
        for motion in self.motions:
            motion.failed = True  # no new motion is accepted; torque stays ON and the watch goes on
        if self.on_expire is not None:
            try:
                self.on_expire()
            except BaseException:  # noqa: BLE001  the failed flag already refuses motion
                pass

    @staticmethod
    def _confirmed(motion, message):
        exc = ValueError(message)
        exc.motion = motion
        return exc

    def _fail_closed(self, exc):
        """Report once and end the session without touching torque."""
        if not self.expired:
            self.expire()
        for each in self.motions:
            each.report_fault(exc)

    def _temperature_limit(self, motion, name):
        key = (id(motion), name)
        if key not in self.temperature_limits:
            try:
                self.temperature_limits[key] = motion.monitor.motions[motion.monitor.key(motion)]["limits"][name]["temperature_limit_c"]
            except (AttributeError, KeyError, TypeError):
                self.temperature_limits[key] = self._read(motion.follower, "Temperature_Limit", name)
        return self.temperature_limits[key]

    def _read(self, bus, register, name):
        try:
            return bus.read(register, name, num_retry=READ_RETRY)  # the same retries as the control loop
        except Exception as exc:  # noqa: BLE001  not a condition read from the motor: nothing is known about the arm
            raise WatchReadFailed(f"{register} {name}: {type(exc).__name__}: {exc}") from exc

    def check(self, now):
        if not self.expired and self._over(now):
            self.expire()
        for motion in self.motions:
            if id(motion) in self._cut:
                continue
            try:
                self._check_motion(motion, now)
            except WatchReadFailed as exc:  # says nothing about the motor: fail closed, keep watching what can be read
                first = self.read_failure is None
                self.read_failure = self.read_failure or exc
                for key in [key for key in self.saturated if key[0] == id(motion)]:
                    self.saturated.pop(key)
                if first:
                    self._fail_closed(exc)
                elif not self.expired:
                    self.expire()

    def _check_motion(self, motion, now):
        bus, label = motion.follower, getattr(motion, "label", "arm")
        for name in motion.active:
            if self._read(bus, "Hardware_Error_Status", name):  # the two CUTS: a single sample with the error bit, or at the temperature limit
                raise self._confirmed(motion, f"{label} {name}: hardware error during the record loop pause")
            if self._read(bus, "Present_Temperature", name) >= self._temperature_limit(motion, name):
                raise self._confirmed(motion, f"{label} {name}: temperature at its limit during the record loop pause")
            pwm = self._read(bus, "Present_PWM", name)
            cap = motion.pwm_limits.get(name) or self._read(bus, "PWM_Limit", name)
            key = (id(motion), name)
            if abs(pwm) < 0.9 * cap:
                self.saturated.pop(key, None)
            elif now - self.saturated.setdefault(key, now) >= HOLD_S - 1e-9 and self.pause_saturated is None:
                self.pause_saturated = f"pause_saturated: {label} {name} PWM at the cap for {HOLD_S:g} s during the record loop pause"
                self._fail_closed(ValueError(self.pause_saturated))  # never a cut: whatever delayed this thread, the arm keeps its torque
