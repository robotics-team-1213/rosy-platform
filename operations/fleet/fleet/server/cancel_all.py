"""D-421 전체 주행 취소 — 래치 없는 사이트 fanout.

전체 비상 정지(`/api/fleet/estop`)는 CORE EMERGENCY 래치와 Fleet 발행 래치를 건다.
이쪽은 둘 다 걸지 않는다. 대기 Fleet 작업을 취소하고, 열린 대형을 풀고, 로봇마다
`swarm/cancel` → `navigation/cancel` → `line-follow/mode OFF` 를 내린다. 수동 조작·
e-stop·신호등·OMX 는 건드리지 않는다.

창마다 작업 저장소에 기록(`cancel_all_store`)을 남기고 그때 달리던 작업에 표시를 단다.
CORE 가 그 작업의 `nav.canceled` 를 보내면 투영이 HOLD(FLEET_CANCEL_ALL)로 옮겨 로봇
점유를 푼다. 그 사건이 없으면 작업은 UNKNOWN 그대로다.

래치가 없으므로 디스패처가 막 집은 작업이 취소 뒤에 출발하는 창이 남는다.
`DriveCancelFence` 가 그 창을 닫는다: 취소와 겹친 Fleet 발행은 목표 응답(또는 실패)
직후 다시 취소한다. 미래의 Pinky Mission Step 제출기도 같은 울타리를 지나야 한다(D-420).

CORE 의 HTTP 응답은 물리 정지가 아니다(D-298) — 결과는 응답 여부만 말한다.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping, Optional

from fleet.server import cancel_all_store
from fleet.server.cancel_all_store import CANCEL_ALL_REASON, DISPATCH_OVERLAP_REASON
from fleet.server.console_view import _error_of
from fleet.swarm.transport import RobotApiError

__all__ = ["CANCEL_ALL_REASON", "DISPATCH_OVERLAP_REASON", "DispatchCanceled",
           "DispatchWithdrawn", "DriveCancelFence", "cancel_all_driving"]

_LOG = logging.getLogger(__name__)

#: The D-361 pinned-address gate refuses locally; nothing was sent to CORE.
_LOCAL_GATE_CODES = {"ADDRESS_UNVERIFIED"}


class DispatchCanceled(RuntimeError):
    """A Fleet dispatch overlapped a cancel-all; its CORE goal may have arrived, so Fleet
    sent navigation/cancel again. The outcome stays UNKNOWN until CORE's correlated event."""

    reason = DISPATCH_OVERLAP_REASON


class DispatchWithdrawn(RuntimeError):
    """An overlapping dispatch ended in Fleet's own traffic queue with no live CORE goal."""

    reason = CANCEL_ALL_REASON


class DriveCancelFence:
    """Marks the cancel-all window so an overlapping Fleet dispatch is canceled again.

    The generation moves when a window opens and when it closes; a dispatch that saw a
    different generation, or ends while a window is open, overlapped one. A Fleet task
    submitted during the window and dispatched before it closes overlaps it too.
    """

    #: How many past windows keep their tagger for dispatches that end after the close.
    KEEP_TAGGERS = 16

    def __init__(self) -> None:
        self.generation = 0
        self.active = 0
        #: Window-open generation -> tagger of that window's record (None without a store).
        self._taggers: dict[int, Optional[Callable[[str], None]]] = {}

    @contextmanager
    def window(self, tag: Optional[Callable[[str], None]] = None) -> Iterator[None]:
        self.generation += 1
        self._taggers[self.generation] = tag
        for old in sorted(self._taggers)[:-self.KEEP_TAGGERS]:
            del self._taggers[old]
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1
            self.generation += 1

    def _tagger_for(self, seen: int) -> Optional[Callable[[str], None]]:
        """The window a dispatch that started at generation `seen` overlapped: the one open
        then, or the next one to open. Overlapping windows fall back to the latest."""
        tag = self._taggers.get(seen) or self._taggers.get(seen + 1)
        if tag is None and self._taggers:
            tag = self._taggers[max(self._taggers)]
        return tag

    def _tag(self, seen: int, task_id: str) -> None:
        tag = self._tagger_for(seen)
        if tag is None:
            return
        try:
            tag(task_id)
        except Exception:
            _LOG.exception("cancel-all tag failed task=%s", task_id)

    def _overlapped(self, seen: int) -> bool:
        return self.generation != seen or self.active > 0

    async def fenced_goal(self, console, task: Mapping[str, Any]) -> Mapping:
        seen = self.generation
        if self.active:
            # Started inside a window: tag before the CORE call, so the window's own cancel
            # (whose nav.canceled may arrive before this goal reply) already matches.
            self._tag(seen, task["task_id"])
        goal = task["request"]["goal"]
        try:
            receipt = await console.goal(
                task["robot_id"], goal["x"], goal["y"], goal["yaw"],
                task_id=task["task_id"], attempt_id=task["attempt_id"],
                attempt_seq=task["attempt_seq"],
            )
        except (Exception, asyncio.CancelledError):
            # A failed or cancelled call may still have reached CORE. Re-cancel, re-raise:
            # the caller keeps its own classification (and CancelledError stays cancellation).
            if self._overlapped(seen):
                await self._recancel(console, task, seen)
            raise
        # 판정은 목표 응답 시점의 사실이다 — 아래 await 전에 끝낸다.
        if not self._overlapped(seen):
            return receipt
        if isinstance(receipt, Mapping) and receipt.get("queued") is True and (
                receipt.get("dispatch_attempted") is not True
                or receipt.get("cancel_confirmed") is True):
            # Fleet's own traffic queue holds it and no CORE goal is live: withdraw it.
            console.discard_task_queue_entries({task["task_id"]})
            raise DispatchWithdrawn(f"{task['robot_id']}: queued dispatch withdrawn")
        if (isinstance(receipt, Mapping) and receipt.get("accepted") is False
                and receipt.get("queued") is not True):
            return receipt          # CORE refused the goal: nothing to cancel (COMMAND_REJECTED)
        await self._recancel(console, task, seen)
        raise DispatchCanceled(f"{task['robot_id']}: dispatch overlapped a cancel-all")

    async def _recancel(self, console, task: Mapping[str, Any], seen: int) -> None:
        """Best effort: tag the task first so CORE's nav.canceled lands as HOLD, then cancel
        the mover and any robot Fleet sent to a bay for it (`_make_room`)."""
        mover = task["robot_id"]
        self._tag(seen, task["task_id"])
        yielders = [rid for rid, why in list(getattr(console, "_yielding", {}).items())
                    if why.get("for") == mover]
        for robot_id in [mover, *yielders]:
            try:
                await console.cancel(robot_id)
            except Exception:
                _LOG.exception("cancel-all re-cancel after overlapping dispatch failed robot=%s",
                               robot_id)


def _step_error(exc: BaseException) -> dict:
    if isinstance(exc, RobotApiError) and exc.code in _LOCAL_GATE_CODES:
        return {"reachable": False, "sent": False, "code": exc.code, "message": str(exc)}
    return _error_of(exc)


def _verdict(steps: Mapping[str, dict]) -> str:
    if all(step["ok"] for step in steps.values()):
        return "cancelled"
    if not any(step["ok"] or step["error"]["reachable"] for step in steps.values()):
        return "unreachable"
    return "failed"


async def _cancel_robot(console, robot_id: str) -> dict:
    """세 단계를 차례로, 앞 단계가 실패해도 다음 단계를 내린다."""
    calls = (
        ("swarm", lambda: console.hub.scatter_swarm_cancel(robot_id)),
        # console.cancel 은 응답을 받은 로봇의 목표·점유·대기·양보만 지운다.
        ("navigation", lambda: console.cancel(robot_id)),
        ("line_follow", lambda: console.line_follow_mode(robot_id, "OFF")),
    )
    steps = {}
    for name, call in calls:
        try:
            await call()
            steps[name] = {"ok": True}
        except Exception as exc:
            steps[name] = {"ok": False, "error": _step_error(exc)}
    return {"robot_id": robot_id, "result": _verdict(steps), "steps": steps}


async def _stop_formation(console) -> dict:
    status = console.formation_status()
    if not status.get("active"):
        return {"stopped": False, "state": status.get("state", "IDLE")}
    try:
        after = await console.formation_stop()
    except Exception as exc:
        _LOG.exception("cancel-all formation stop failed")
        return {"stopped": False, "state": status.get("state"), "error": _error_of(exc)}
    return {"stopped": True, "state": after.get("state", "STOPPED")}


def _cancel_queued(console, task_service, actor_id: str) -> dict:
    if task_service is None:
        return {"canceled": [], "error": None}
    try:
        canceled = task_service.cancel_all_queued(actor_id=actor_id, reason=CANCEL_ALL_REASON)
    except Exception:
        _LOG.exception("cancel-all queue cleanup unavailable principal=%s", actor_id)
        return {"canceled": [], "error": "TASK_STORE_UNAVAILABLE"}
    console.discard_task_queue_entries(set(canceled))
    return {"canceled": list(canceled), "error": None}


RECORD_UNAVAILABLE = "CANCEL_ALL_RECORD_UNAVAILABLE"


def _open_record(store, actor_id: str, robots: list[str]):
    if store is None:
        return None
    try:
        return cancel_all_store.open_record(store, principal_id=actor_id,
                                            robot_ids=robots)["cancel_all_id"]
    except Exception:
        _LOG.exception("cancel-all record unavailable principal=%s", actor_id)
        return None


def _close_record(store, cancel_all_id, robots: list[str], canceled: list[str],
                  rows: list[dict]) -> tuple[dict, str | None]:
    """Close the record; without one, fall back to the plain unfinished-task readback."""
    if store is None:
        return {}, None
    answered = [row["robot_id"] for row in rows if row["steps"]["navigation"]["ok"]]
    if cancel_all_id is not None:
        try:
            return cancel_all_store.close_record(store, cancel_all_id, canceled_task_ids=canceled,
                                                 nav_answered=answered), None
        except Exception:
            _LOG.exception("cancel-all record close unavailable id=%s", cancel_all_id)
    awaiting = {}
    for robot_id in robots:
        try:
            awaiting[robot_id] = [task_id for task_id in store.unfinished_task_ids(robot_id)
                                  if task_id not in canceled]
        except Exception:
            _LOG.exception("cancel-all unfinished task readback unavailable robot=%s", robot_id)
    return awaiting, RECORD_UNAVAILABLE


async def cancel_all_driving(console, task_service, fence: DriveCancelFence, *,
                             actor_id: str) -> dict:
    """D-421 순서: 울타리·기록 → 대기 작업 취소 → 대형 해제 → 로봇별 세 단계(로봇끼리 동시)."""
    store = task_service.store if task_service is not None else None
    order = console.robot_ids
    cancel_all_id = _open_record(store, actor_id, order)
    tagger = None if cancel_all_id is None else (
        lambda task_id: cancel_all_store.tag_task(store, cancel_all_id, task_id))
    with fence.window(tagger):
        tasks = _cancel_queued(console, task_service, actor_id)
        formation = await _stop_formation(console)
        rows = list(await asyncio.gather(*(_cancel_robot(console, rid) for rid in order)))
    # 발행된 작업은 여기서 바꾸지 않는다 — CORE nav.canceled 투영만 바꾼다.
    awaiting, record_error = _close_record(store, cancel_all_id, order, tasks["canceled"], rows)
    for row in rows:
        row["tasks"] = {"awaiting_core_result": awaiting.get(row["robot_id"], [])}
    return {
        "cancel_all_id": cancel_all_id,
        "record_error": record_error,
        "cancelled": sum(1 for row in rows if row["result"] == "cancelled"),
        "total": len(rows),
        "evidence": "CORE_REPLY_ONLY",
        "robots": rows,
        "formation": formation,
        "tasks": tasks,
    }
