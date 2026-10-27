"""Liveness registry for the lifespan-owned background loops (계획 2026-10-27).

사망 감시는 모든 루프에 둔다. 주기 계측은 루프 몸체를 이미 여는 변경에만 붙인다
(지금은 작업 디스패치 루프). ``/readyz`` 가 이 표를 읽고, ``/healthz`` 는 프로세스
생존만 말한다 — compose healthcheck·mdns 광고 검증·autoupdate 게이트가 ``/healthz``
를 그대로 쓰므로 그 의미를 바꾸지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from functools import partial
from typing import Awaitable, Callable, Optional

from fleet.server.background_workers import (
    _mission_model_turn_worker_loop, _task_dispatch_loop, goal_evidence_expiry_loop,
    goal_lease_renew_loop, lane_compliance_loop, proposal_expiry_loop, start_notification_worker)
from fleet.server.control_unit_observation_runtime import start_control_unit_tasks
from fleet.server.dispatch_workers import mission_dispatch_loop, mission_feedback_schedule_loop

_LOG = logging.getLogger(__name__)

FAILURE_LOG_INTERVAL_S = 30.0

RUNNING = "running"
NOT_CONFIGURED = "not_configured"
DEAD = "dead"


@dataclass
class LoopState:
    state: str = NOT_CONFIGURED
    deaths: int = 0
    consecutive_failures: int = 0
    last_failure_type: Optional[str] = None


class LoopSupervisor:
    """Track background-loop liveness without touching loop bodies.

    ``supervised()`` starts a coroutine as a watched task; ``attach()`` watches a task
    a helper already started (notification worker, control units, tether watch). Loop
    bodies stay untouched — per-cycle visibility is opt-in via ``note_failure``/``note_ok``.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 log: Optional[logging.Logger] = None,
                 failure_log_interval_s: float = FAILURE_LOG_INTERVAL_S) -> None:
        self._clock = clock
        self._log = log or _LOG
        self._failure_log_interval_s = failure_log_interval_s
        self._loops: dict[str, LoopState] = {}
        self._last_failure_log: dict[str, float] = {}
        self._stopping = False

    def declare(self, *names: str) -> None:
        """Pre-enumerate optional loops so /readyz tells not_configured from dead."""
        for name in names:
            self._loops.setdefault(name, LoopState())

    def supervised(self, name: str, loop: Awaitable) -> asyncio.Task:
        self.declare(name)
        return self._watch(name, asyncio.create_task(loop))

    def attach(self, name: str, task: asyncio.Task) -> asyncio.Task:
        self.declare(name)
        return self._watch(name, task)

    def stopping(self) -> None:
        """Call before cancelling loops at shutdown: their deaths are expected."""
        self._stopping = True

    def note_failure(self, name: str, error: BaseException) -> None:
        state = self._loops.setdefault(name, LoopState())
        if state.state == NOT_CONFIGURED:
            state.state = RUNNING
        state.consecutive_failures += 1
        state.last_failure_type = type(error).__name__
        now = self._clock()
        last = self._last_failure_log.get(name)
        if last is None or now - last >= self._failure_log_interval_s:
            self._last_failure_log[name] = now
            self._log.error("Fleet background loop '%s' cycle failed (%d consecutive)",
                            name, state.consecutive_failures, exc_info=error)

    def note_ok(self, name: str) -> None:
        state = self._loops.setdefault(name, LoopState())
        if state.state == NOT_CONFIGURED:
            state.state = RUNNING
        state.consecutive_failures = 0

    def status(self) -> dict:
        return {name: {"state": state.state, "deaths": state.deaths,
                       "consecutive_failures": state.consecutive_failures,
                       "last_failure_type": state.last_failure_type}
                for name, state in sorted(self._loops.items())}

    def ready(self) -> tuple[bool, dict]:
        """Ready means: at least one declared loop and none dead. A loop that keeps
        failing but keeps cycling degrades (``consecutive_failures``) without failing
        readiness; readiness fails when a loop task actually ended."""
        loops = self.status()
        if not loops:
            return False, loops
        return all(row["state"] != DEAD for row in loops.values()), loops

    def _watch(self, name: str, task: asyncio.Task) -> asyncio.Task:
        self._loops[name].state = RUNNING

        def ended(finished: asyncio.Task) -> None:
            if self._stopping or finished.cancelled():
                return
            error = finished.exception()
            state = self._loops[name]
            state.state = DEAD
            state.deaths += 1
            if error is None:
                self._log.error("Fleet background loop '%s' ended without being cancelled", name)
            else:
                state.last_failure_type = type(error).__name__
                self._log.error("Fleet background loop '%s' ended: %s", name,
                                type(error).__name__, exc_info=error)

        task.add_done_callback(ended)
        return task


FLEET_LOOP_NAMES = (
    "notifications", "arm-transfer-dispatcher", "signals", "stuck-resolver",
    "localization", "calibration-drift", "trip-runner", "charge-runtime",
    "goal-lease-renew", "identity", "lane-compliance", "tether-watch", "paths",
    "job-trips", "task-dispatch", "proposal-expiry", "mission-dispatch",
    "cell-job-dispatch", "goal-evidence-expiry", "mission-feedback-schedule",
    "mission-model-turn", "control-unit-journal", "control-unit-information",
)


def start_fleet_loops(app, console, *, supervisor, task_service=None, start_task_dispatcher=True,
                      drive_cancel=None, proposal_store=None, mission_dispatcher=None,
                      cell_job_dispatcher=None, goal_evidence_service=None,
                      mission_model_turn_scheduler=None, mission_model_turn_worker=None,
                      localization_service=None, calibration_drift_watch=None,
                      notification_config=None, identity=None, log, lane_compliance_period_s):
    """Spawn every lifespan background loop under one liveness registry.

    app.py의 스폰 블록을 통째로 옮겼다(D-766 래칫: app.py는 파일 한도 초과라 늘지
    못한다). 각 태스크는 원래 자리에서 만들던 그대로 만들고 감시만 덧붙인다.
    감시자는 create_app이 만들어 넘겨준다 — /readyz는 lifespan 전에도 선언된
    이름을 볼 수 있어야 한다.
    """
    supervisor.declare(*FLEET_LOOP_NAMES)
    goal_evidence_expiry = partial(goal_evidence_expiry_loop, logger=log)
    mission_feedback = partial(mission_feedback_schedule_loop, logger=log)
    mission_dispatch = partial(mission_dispatch_loop, logger=log)

    control_tasks = [
        supervisor.attach(name, task)
        for name, task in zip(("control-unit-journal", "control-unit-information"),
                              start_control_unit_tasks(app))]
    notification_http, notification_task = start_notification_worker(app, notification_config)
    if notification_task is not None:
        notification_task = supervisor.attach("notifications", notification_task)
    physical_worker = (supervisor.supervised(
                           "arm-transfer-dispatcher", app.state.arm_transfer_dispatcher.run())
                       if app.state.arm_transfer_dispatcher is not None else None)
    signal_task = (supervisor.supervised("signals", console._signals.run())
                   if console._signals is not None else None)
    app.state.signal_supervision = signal_task
    resolver_task = (supervisor.supervised("stuck-resolver", app.state.stuck_resolver.run())
                     if getattr(app.state, "stuck_resolver", None) is not None else None)
    localization_task = (supervisor.supervised("localization", localization_service.run())
                         if localization_service is not None else None)
    calibration_drift_task = (supervisor.supervised("calibration-drift", calibration_drift_watch.run())
                              if calibration_drift_watch is not None else None)
    trip_task = supervisor.supervised("trip-runner", app.state.trip_runner.run())  # D-494 5
    charge_task = (supervisor.supervised("charge-runtime", app.state.charge_runtime.run())
                   if app.state.charge_runtime is not None else None)
    lease_task = (supervisor.supervised(  # D-550 10
                      "goal-lease-renew", goal_lease_renew_loop(console, log))
                  if getattr(getattr(console, "goal_leases", None), "ttl_s", 0) > 0 else None)
    identity_task = supervisor.supervised("identity", identity.run())  # D-596 blink answers
    lane_task = supervisor.supervised("lane-compliance", lane_compliance_loop(  # D-511 M0
        app.state.lane_compliance, log, lane_compliance_period_s))
    tether_task = supervisor.attach("tether-watch", app.state.tether_watch.start())  # D-526
    path_task = supervisor.supervised("paths", app.state.paths.run())  # D-594
    job_task = (supervisor.supervised("job-trips", app.state.job_trips.run())
                if False and getattr(app.state, "job_trips", None) else None)
    dispatcher = (supervisor.supervised(
                      "task-dispatch",
                      _task_dispatch_loop(console, task_service, drive_cancel, supervisor=supervisor))
                  if task_service is not None and start_task_dispatcher else None)
    proposal_expiry = (supervisor.supervised(
                           "proposal-expiry", proposal_expiry_loop(proposal_store, log))
                       if proposal_store is not None else None)
    mission_worker = (supervisor.supervised(
                          "mission-dispatch", mission_dispatch(mission_dispatcher))
                      if mission_dispatcher is not None else None)
    cell_job_worker = (supervisor.supervised(
                           "cell-job-dispatch", mission_dispatch(cell_job_dispatcher))
                       if cell_job_dispatcher is not None else None)
    goal_evidence_worker = (supervisor.supervised(
                                "goal-evidence-expiry", goal_evidence_expiry(goal_evidence_service))
                            if goal_evidence_service is not None else None)
    mission_feedback_scheduler = (supervisor.supervised(
                                      "mission-feedback-schedule",
                                      mission_feedback(mission_model_turn_scheduler))
                                  if mission_model_turn_scheduler is not None else None)
    mission_model_turn_task = (supervisor.supervised(
                                   "mission-model-turn",
                                   _mission_model_turn_worker_loop(mission_model_turn_worker))
                               if mission_model_turn_worker is not None else None)
    background_tasks = [task for task in (dispatcher, mission_worker, cell_job_worker,
                                          proposal_expiry, goal_evidence_worker,
                                          mission_feedback_scheduler, mission_model_turn_task,
                                          localization_task, signal_task, resolver_task,
                                          trip_task, identity_task, lane_task, tether_task,
                                          lease_task, path_task, calibration_drift_task,
                                          notification_task, job_task, charge_task,
                                          physical_worker, *control_tasks)
                        if task is not None]
    return supervisor, notification_http, background_tasks
