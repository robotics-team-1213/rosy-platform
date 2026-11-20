"""SLAM -> site wall map fallback supervisor (ROS-free policy; user decision 2026-11-18: the switch is always automatic).

What it does, in this order, and nothing else:
  1. while the backend is slam, feed slam_health (never otherwise: a localization-backend robot gets an inert supervisor);
  2. on LOST: halt autonomy, wait until odometry has been zero for ZERO_S with no goal (CORE's own evidence file, which the
     privileged host half re-checks), keep that evidence fresh until the host answers, then call navigation_fallback.switch;
  3. after the restart: goals stay refused (hold_reason, which beats any LOCALIZED reading) until a localization report
     received AFTER the restart says LOCALIZED on the map frame; Fleet picks the start pose from loc_assist candidates.
     The wait is written to a marker file, so a CORE restart on the localization backend resumes it (host status confirms);
     no decision in DECISION_TIMEOUT_S: stay stopped and raise an alert;
  4. never switch back to SLAM, never switch twice in a boot (a failed or rolled-back attempt counts), never weaken a guard limit.
DEGRADED (a bad map but a good pose) only reports. All timings below are unmeasured proposals (see slam_health.py).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from core_features.localization.slam_health import LOST, OK, Sample, SlamHealth

_log = logging.getLogger(__name__)

SPOOL_NAME = "wall-map-spool"            # the host half reads it from the same directory
SPOOL_IMAGE = "wall-map.pgm"
SPOOL_META = "meta.json"
STOP_EVIDENCE_NAME = "slam-fallback-stop.json"
STATE_NAME = "slam-fallback-state.json"  # the wait for a pose, so a CORE restart keeps refusing goals
SOURCE = "slam_fallback"

MONITORING, STOPPING, SWITCHING, WAITING, ACTIVE, FAILED = (
    "MONITORING", "STOPPING", "SWITCHING", "WAITING_LOCALIZATION", "ACTIVE", "FAILED")
ZERO_S = 2.0               # odometry zero this long before the switch (the host half re-checks the same number)
ZERO_MARGIN_S = 0.2        # our own margin so the evidence we write already shows >= ZERO_S
SPEED_EPS = (0.01, 0.02)   # m/s, rad/s counted as zero
STOP_ALERT_S = 60.0        # a robot that cannot be brought to zero velocity this long needs a person
SWITCH_TIMEOUT_S = 90.0    # the host unit must report a result within this
DECISION_TIMEOUT_S = 180.0  # no LOCALIZED after the restart: stay stopped, alert
SEARCH_EVERY_S = 10.0
HOST_RETRIES = 3
REASON_CODE = "slam_lost"   # the identifier-form reason the Host Agent accepts
_UNREACHABLE = {"HOST_AGENT_UNAVAILABLE", "HOST_AGENT_TIMEOUT", "HOST_AGENT_UNREADABLE_RESPONSE"}


def state_dir() -> Path:
    return Path(os.environ.get("STATE_DIRECTORY", "/var/lib/rosy/core"))


@dataclass(frozen=True)
class HostReply:
    ok: bool
    code: str = ""
    data: Optional[dict] = None
    detail: str = ""


@dataclass
class Ports:
    """Everything the policy touches, injected: the wiring binds the real CORE objects, a test binds fakes."""

    sample: Callable[[float], Optional[Sample]]
    speed: Callable[[], Optional[tuple[float, float]]]   # None: unknown, which is never zero
    goal_active: Callable[[], bool]
    halt: Callable[[], None]                             # autonomy halt + manual input cleared (CommandManager zero)
    write_evidence: Callable[[dict], None]
    request: Callable[..., HostReply]                    # request(command, **params): Host Agent, machine grade
    localization: Callable[[], Any]                      # LocalizationAssist.raw_status(): .state/.pose_frame or None
    reports: Callable[[], int]                           # how many localization reports CORE has received
    request_search: Callable[[], None]
    after_switch: Callable[[], None]                     # readiness profile swap
    events: Any                                          # EventBus: publish(type, severity=, source=, data=)
    read_marker: Callable[[], Optional[dict]]
    write_marker: Callable[[Optional[dict]], None]       # None removes it


class SlamFallback:
    def __init__(self, ports: Ports, backend: str, *, clock=time.monotonic, wall=time.time) -> None:
        slam = str(backend).strip().lower() == "slam"
        self._p, self._clock, self._wall = ports, clock, wall
        self._health = SlamHealth()
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.reason, self.alert, self.wall_map = "", None, None
        self.since: Optional[float] = None
        self._attempted = False       # one switch per boot, success or not
        self._switched = False        # never back to slam, even after a reset
        self._recovering = False      # a CORE restart after the switch: the host status confirms it
        self._zero_since: Optional[float] = None
        self._entered = self._clock()
        self._retries = 0
        self._seq0 = 0                # localization reports seen when WAITING began
        self._last_search = -SEARCH_EVERY_S
        self._last_health = OK
        self._last_wall_map_poll = -30.0
        self._slam_config = slam
        marker = self._marker()
        self.phase: Optional[str] = MONITORING if slam else None
        if marker:  # F1/R1: CORE restarted at or after the switch request, whichever backend it now reads: the host decides
            self._recovering = self._attempted = True
            self.phase, self.reason, self.since = WAITING, str(marker.get("reason", ""))[:200], marker.get("since")
            self._seq0 = self._p.reports()
        self.enabled = self.phase is not None

    def _marker(self) -> Optional[dict]:
        try:
            data = self._p.read_marker()
        except Exception:  # noqa: BLE001 - an unreadable marker counts as present: hold, never open
            _log.exception("slam fallback marker unreadable")
            return {"reason": "marker_unreadable"}
        return data if isinstance(data, dict) else None

    def _write_marker(self, data: Optional[dict]) -> bool:
        """False when it could not be stored: the robot then stays stopped (R6) and a person is told."""
        try:
            self._p.write_marker(data)
            return True
        except OSError as exc:
            _log.warning("slam fallback marker not written: %s", exc)
            if data is not None and self.alert is None:
                self._alert("the restart marker cannot be written; the robot stays stopped and no switch is started")
            return False

    # --- read side (plain attribute reads: called under LocalizationAssist's lock) ---------

    def hold_reason(self) -> Optional[str]:
        """While not None, goals and docking are refused whatever loc_assist reports (a LOCALIZED reading reads UNKNOWN)."""
        return {STOPPING: "slam_fallback_stopping", SWITCHING: "slam_fallback_switching",
                WAITING: "slam_fallback_waiting_pose", FAILED: "slam_fallback_failed"}.get(self.phase)

    def status(self) -> Optional[dict]:
        if not self.enabled:
            return None
        return {"phase": self.phase, "fallback_active": self.phase in (WAITING, ACTIVE), "reason": self.reason,
                "since": self.since, "health": self._last_health, "wall_map": self.wall_map, "alert": self.alert}

    # --- wall map ---------------------------------------------------------------------------

    def spool(self, image: bytes, meta: bytes) -> bool:
        """Put the map CORE just verified where the host half reads it (atomic per file). False: a switch is running."""
        if self.phase in (STOPPING, SWITCHING):
            return False
        folder = state_dir() / SPOOL_NAME
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in ((SPOOL_IMAGE, image), (SPOOL_META, meta)):
            temp = folder / (name + ".tmp")
            temp.write_bytes(data)
            os.replace(temp, folder / name)
        return True

    def stage(self) -> HostReply:
        """Ask the host to install the map CORE just spooled (after its own sha256 check); never while a switch runs."""
        if self.phase in (STOPPING, SWITCHING):
            return HostReply(False, "SWITCH_RUNNING", None, "a fallback switch is running: the wall map is not replaced now")
        reply = self._p.request("navigation_fallback.stage")
        data = {"staged": reply.ok, "code": reply.code, "detail": reply.detail[:120]}
        if reply.ok:
            self._p.events.publish("slam_fallback.wall_map", severity="info", source=SOURCE, data=data)
            self._poll_wall_map()
        else:
            self._p.events.publish("slam_fallback.wall_map", severity="warning", source=SOURCE, data=data)
        return reply

    def _poll_wall_map(self) -> Optional[dict]:
        reply = self._p.request("navigation_fallback.status")
        if reply.ok and isinstance(reply.data, dict):
            staged = reply.data.get("wall_map")
            self.wall_map = None if not staged else {k: staged.get(k) for k in ("map_id", "version", "sha256")}
            return reply.data
        return None

    # --- the loop ---------------------------------------------------------------------------

    def tick(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            now = self._clock()
            {MONITORING: self._monitor, STOPPING: self._stopping, SWITCHING: self._switching,
             WAITING: self._waiting, FAILED: self._failed}.get(self.phase, lambda _now: None)(now)

    def _go(self, phase: str, reason: str = "") -> None:
        self.phase, self._entered, self.since = phase, self._clock(), self._wall()
        if reason:
            self.reason = reason

    def _monitor(self, now: float) -> None:
        if now - self._last_wall_map_poll >= 30.0:
            self._last_wall_map_poll = now
            self._poll_wall_map()
        sample = self._p.sample(now)
        if sample is None:
            return
        health = self._health.update(sample)
        if health.state != self._last_health:
            self._last_health = health.state
            data = {"state": health.state, "reasons": list(health.reasons)}
            if health.state == OK:
                self._p.events.publish("slam_fallback.health", severity="info", source=SOURCE, data=data)
            else:
                self._p.events.publish("slam_fallback.health", severity="warning", source=SOURCE, data=data)
        if health.state == LOST:
            self._begin(",".join(health.reasons) or "lost")

    def _begin(self, reason: str) -> None:
        if self._attempted:  # a second attempt in one boot is a person's decision, not an automatic one
            self._fail("a fallback switch was already attempted in this boot")
            return
        self._go(STOPPING, reason)
        self._zero_since = None
        self._p.events.publish("slam_fallback.stopping", severity="critical", source=SOURCE, data={"reason": reason})
        self._p.halt()

    def _track_stop(self, now: float) -> float:
        """One look at the stop: cancel what moves, write the evidence the host re-checks. Returns seconds held at zero.

        Runs in STOPPING and again in SWITCHING (the host unit re-checks the evidence when it starts, and the robot
        must stay stopped through the restart): teleop is cleared on every tick, a goal that appears is cancelled."""
        speed, goal = self._p.speed(), self._p.goal_active()
        zero = (not goal and speed is not None and abs(speed[0]) < SPEED_EPS[0] and abs(speed[1]) < SPEED_EPS[1])
        if not zero:
            self._zero_since = None
        elif self._zero_since is None:
            self._zero_since = now
        if goal or not zero:
            self._p.halt()
        held = 0.0 if self._zero_since is None else now - self._zero_since
        try:  # the clock is monotonic: the host reads the same CLOCK_MONOTONIC and the boot id the wiring adds
            self._p.write_evidence({"written_at": now, "zero_since": self._zero_since, "goal_active": bool(goal)})
        except OSError as exc:
            _log.warning("slam fallback stop evidence not written: %s", exc)
            return 0.0
        return held

    def _stopping(self, now: float) -> None:
        if self._track_stop(now) >= ZERO_S + ZERO_MARGIN_S:
            self._switch()
        elif now - self._entered > STOP_ALERT_S and self.alert is None:
            self._alert("the robot could not be brought to zero velocity; the switch is waiting")

    def _switch(self) -> None:
        if not self._write_marker({"phase": SWITCHING, "reason": self.reason, "since": self._wall()}):
            return  # R1/R6: no request without the marker that keeps the hold through a CORE restart
        reply = self._p.request("navigation_fallback.switch", reason=REASON_CODE)
        if reply.ok:
            self._attempted = True
            self._retries = 0
            self._go(SWITCHING)
            self._p.events.publish("slam_fallback.switching", severity="critical", source=SOURCE, data={"reason": self.reason})
        elif reply.code in _UNREACHABLE:
            self._retries += 1
            if reply.code == "HOST_AGENT_TIMEOUT":  # the request may have been taken: the status poll decides
                self._attempted = True
                self._go(SWITCHING)
            elif self._retries >= HOST_RETRIES:
                self._attempted = True
                self._write_marker(None)
                self._fail(f"the host agent is unreachable: {reply.code}")
        else:
            self._attempted = True
            self._write_marker(None)  # nothing was committed: no switch is owed
            self._fail(f"the host refused the switch: {reply.code} {reply.detail[:120]}")

    def _switching(self, now: float) -> None:
        data = self._poll_wall_map()  # first: a slow status call must not age the evidence we write next (R5)
        phase = (data or {}).get("phase")
        if phase not in ("SWITCHED", "ROLLED_BACK", "REFUSED", "FAILED"):
            self._track_stop(now)  # F4: the evidence stays fresh (and the robot stopped) until the host has answered
        if phase == "SWITCHED":
            self._switched = True
            self._enter_waiting()
            self._p.after_switch()
            self._p.events.publish("slam_fallback.switched", severity="critical", source=SOURCE, data={"reason": self.reason})
        elif phase in ("ROLLED_BACK", "REFUSED"):
            self._write_marker(None)  # the runtime is back on slam
            self._fail(f"the host switch ended {phase}: {(data or {}).get('reason', '')[:120]}")
        elif phase == "FAILED":  # the rollback itself failed: runtime.env is uncertain, the marker stays
            self._fail(f"the host switch ended {phase}: {(data or {}).get('reason', '')[:120]}")
        elif now - self._entered > SWITCH_TIMEOUT_S:
            self._fail("the host switch reported no result")  # the marker stays; a late SWITCHED is picked up in FAILED

    def _enter_waiting(self) -> None:
        self._go(WAITING)
        self._seq0 = self._p.reports()  # a LOCALIZED reading must be newer than this: nothing from before the restart
        self._last_search = -SEARCH_EVERY_S
        self._write_marker({"phase": WAITING, "reason": self.reason, "since": self.since})

    def _confirm_restart(self) -> bool:
        """After a CORE restart (R2): True only when the host says SWITCHED. The hold ends early only for a confirmed
        terminal state with the runtime back on slam; SWITCHING, FAILED, unknown or unreadable keep it."""
        reply = self._p.request("navigation_fallback.status")
        data = reply.data if reply.ok and isinstance(reply.data, dict) else None
        if data is None:
            return False
        phase, backend = data.get("phase"), data.get("backend")
        if phase == "SWITCHED":
            self._recovering, self._switched = False, True
            self._seq0 = self._p.reports()  # only reports after this confirmation come from the new navigation
            if self._slam_config:  # CORE started before the unit committed: the profile follows the runtime now
                self._p.after_switch()
            return True
        if phase in ("ROLLED_BACK", "REFUSED", "FAILED", "IDLE") and backend == "slam":
            self._recovering = False   # the robot is on SLAM again: nothing was switched
            self._write_marker(None)
            if self._slam_config:
                self._go(MONITORING, "")
            else:
                self.phase, self.enabled = None, False
            return False
        if phase == "FAILED" and self.alert is None:
            self._alert("the switch failed and the runtime is not confirmed back on slam; the robot stays stopped")
        return False

    def _waiting(self, now: float) -> None:
        if self._recovering and not self._confirm_restart():
            if self.phase == WAITING and now - self._entered > DECISION_TIMEOUT_S and self.alert is None:
                self._alert("CORE restarted around the switch and the host did not confirm it; the robot stays stopped")
            return
        status = self._p.localization()
        if (status is not None and status.state.value == "LOCALIZED" and status.pose_frame.value == "map"
                and self._p.reports() > self._seq0):
            self._go(ACTIVE)
            self._p.events.publish("slam_fallback.active", severity="info", source=SOURCE, data={"reason": self.reason})
            return
        if status is not None and status.state.value in ("UNKNOWN", "SUSPECT") and now - self._last_search >= SEARCH_EVERY_S:
            self._last_search = now
            self._p.request_search()
        if now - self._entered > DECISION_TIMEOUT_S and self.alert is None:
            self._alert("no start pose was decided on the wall map; the robot stays stopped")

    def _failed(self, now: float) -> None:
        """R3b: a timed-out switch may still finish. A late SWITCHED puts the robot in WAITING; the hold never drops."""
        if not self._attempted or now - self._last_wall_map_poll < 5.0:
            return
        self._last_wall_map_poll = now
        data = self._poll_wall_map()
        if (data or {}).get("phase") == "SWITCHED":
            self._switched = True
            self._enter_waiting()
            self._p.after_switch()
            self._p.events.publish("slam_fallback.switched", severity="critical", source=SOURCE, data={"reason": self.reason})

    def _fail(self, why: str) -> None:
        self._go(FAILED, why)
        self._alert(why)

    def _alert(self, why: str) -> None:
        self.alert = why[:200]
        self._p.events.publish("slam_fallback.alert", severity="critical", source=SOURCE,
                               data={"alert": self.alert, "phase": self.phase})

    def reset(self) -> bool:
        """An operator's reset after a FAILED fallback: monitoring resumes (only while still on SLAM)."""
        with self._lock:
            if self.phase != FAILED or self._switched:
                return False
            data = self._poll_wall_map()  # R3b: only while the runtime is really still slam
            # N1: the same rule as _confirm_restart — a terminal host phase with the runtime on slam; a SWITCHING
            # unit may still commit after the 90 s timeout, so it keeps the hold
            if (data is None or data.get("backend") != "slam"
                    or data.get("phase") not in ("ROLLED_BACK", "REFUSED", "FAILED", "IDLE")):
                return False
            self._write_marker(None)
            self._health, self._attempted, self.alert, self._last_health = SlamHealth(), False, None, OK
            self._go(MONITORING, "")
            self._p.events.publish("slam_fallback.reset", severity="warning", source=SOURCE, data={})
            return True

    # --- thread (its own: a host call may block for seconds, which a ROS timer must not) -------

    def start(self, period_s: float = 1.0) -> None:
        if not self.enabled or self._thread is not None:
            return

        def loop() -> None:
            while not self._stop.wait(period_s):
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 - the supervisor must outlive one bad tick
                    _log.exception("slam fallback tick failed")
        self._thread = threading.Thread(target=loop, name="slam-fallback", daemon=True)
        self._thread.start()

    def stop(self, join_s: float = 2.0) -> None:
        """Called from CORE's shutdown: end the loop and wait a bounded time (a host call may still be in flight)."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(join_s)
