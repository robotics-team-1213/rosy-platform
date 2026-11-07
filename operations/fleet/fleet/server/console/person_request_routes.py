"""D-721 Amendment: 사람 부탁 routes. A request asks a person for something physical; the answer is their statement.

An answer closes the record and, for a request that reached a robot, tells that robot to stop showing it. Nothing
else is sent: the answer never starts motion, releases a stop or satisfies a check. Tools still read the evidence.
"""
from __future__ import annotations

import logging
import time
from typing import Literal, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core_common.protocol.person_request import CONTROL, DEFAULT_TTL_S, ID_PATTERN, KINDS, MAX_TTL_S
from fleet.server.person_request_store import PersonRequestStore

logger = logging.getLogger(__name__)
STATES = ("open", "done", "cannot", "expired", "withdrawn")
MAX_OPEN_PER_ROBOT = 3
RECONCILE_EVERY_S = 5.0


class PersonRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: Optional[str] = Field(default=None, min_length=1, max_length=96)
    kind: Literal["unplug_charger", "plug_charger", "move_robot", "clear_area", "other"]
    text: str = Field(min_length=1, max_length=200)
    why: str = Field(default="", max_length=200)
    expires_s: float = Field(default=DEFAULT_TTL_S, gt=0, le=MAX_TTL_S, allow_inf_nan=False)

    @field_validator("text", "why", "robot_id")
    @classmethod
    def _plain(cls, value):
        if value is not None and CONTROL.search(value):
            raise ValueError("control characters are not allowed")
        return value


class PersonRequestAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: Literal["done", "cannot"]
    note: str = Field(default="", max_length=200)

    @field_validator("note")
    @classmethod
    def _plain(cls, value):
        if CONTROL.search(value):
            raise ValueError("control characters are not allowed")
        return value


def _refuse(status: int, code: str, **detail) -> HTTPException:
    return HTTPException(status, detail={"code": code, **detail})


def install_person_request_routes(app, store: PersonRequestStore, read_guard, require_proposer,
                                  require_named_operator, known_robots, robots=None, monotonic=time.monotonic) -> None:
    """``known_robots()`` is an awaitable set of roster ids. ``robots`` holds ``put(robot_id, record)``,
    ``clear(robot_id, request_id)`` and ``read(robot_id)`` (the request CORE holds, or None); None keeps requests on the
    console only. ``app.state.person_request_reconcile`` is the periodic step that keeps a robot's screen equal to its
    newest open request and says "delivered" only for what it read back."""
    app.state.person_requests = store
    last = {"at": None}

    async def put(record: dict) -> bool:
        """Show this request on its robot; True when the robot took it and it is still open."""
        try:
            await robots.put(record["robot_id"], record)
        except Exception as exc:  # noqa: BLE001 - a robot that cannot be reached is shown as not delivered
            logger.warning("person request %s not delivered to %s: %s", record["id"], record["robot_id"],
                           type(exc).__name__)
            store.set_delivery(record["id"], "not_delivered", type(exc).__name__)
            return False
        store.set_delivery(record["id"], "delivered")
        current = store.get(record["id"])   # answered or withdrawn while the PUT was in flight: take it back
        if current["state"] != "open":
            await clear(current)
            return False
        return True

    async def clear(record: dict) -> None:
        try:
            await robots.clear(record["robot_id"], record["id"])
            store.set_delivery(record["id"], "cleared")
        except Exception as exc:  # noqa: BLE001 - CORE drops it at its expiry; the next reconcile retries
            store.set_delivery(record["id"], "clear_failed", type(exc).__name__)

    async def show_newest(robot_id: str) -> None:
        """One request per robot is on its screen: the newest open one. Older open ones wait."""
        opens = store.open_for(robot_id)
        for older in opens[1:]:
            store.set_delivery(older["id"], "waiting")
        if opens:
            await put(opens[0])

    async def after_close(record: dict) -> None:
        if robots is None or not record["robot_id"]:
            return
        await clear(record)
        await show_newest(record["robot_id"])

    async def reconcile() -> None:
        if robots is None:
            return
        now = monotonic()
        if last["at"] is not None and now - last["at"] < RECONCILE_EVERY_S:
            return
        last["at"] = now
        store.expire_due()
        stuck = [r for r in store.list() if r["delivery"]["state"] == "clear_failed" and r["robot_id"]]
        ids = {r["robot_id"] for r in store.list(state="open") if r["robot_id"]} | {r["robot_id"] for r in stuck}
        for robot_id in sorted(ids):
            opens = store.open_for(robot_id)
            try:
                held = await robots.read(robot_id)
            except Exception as exc:  # noqa: BLE001 - what the robot shows is unknown, and the console says so
                for record in opens:
                    store.set_delivery(record["id"], "not_delivered", type(exc).__name__)
                continue
            held_id = (held or {}).get("id")
            for older in opens[1:]:
                store.set_delivery(older["id"], "waiting")
            if not opens:
                if held_id:   # CORE still shows a request Fleet has closed or lost: take it away
                    try:
                        await robots.clear(robot_id, held_id)
                    except Exception as exc:  # noqa: BLE001 - tried again next round
                        logger.warning("person request %s still on %s: %s", held_id, robot_id, type(exc).__name__)
                        continue
                    held_id = None
            elif held_id == opens[0]["id"]:
                store.set_delivery(opens[0]["id"], "delivered")   # read back just now
            else:
                await put(opens[0])   # missing (a CORE restart) or an older one: show the newest
            for record in stuck:
                if record["robot_id"] == robot_id and record["id"] != held_id:
                    store.set_delivery(record["id"], "cleared")
    app.state.person_request_reconcile = reconcile
    tick = getattr(app.state, "charge_bays_tick", None)   # Fleet's existing one-second loop carries it
    if tick is not None and robots is not None:
        async def tick_and_reconcile() -> None:
            await tick()
            await reconcile()
        app.state.charge_bays_tick = tick_and_reconcile

    def known(request_id: str) -> dict:
        record = store.get(request_id) if len(request_id) <= 64 else None
        if record is None:
            raise _refuse(404, "PERSON_REQUEST_NOT_FOUND")
        return record

    @app.post("/api/fleet/person-requests", tags=["fleet"])
    async def create_person_request(body: PersonRequestCreate, principal=Depends(require_proposer)) -> dict:
        if body.robot_id is not None and body.robot_id not in await known_robots():
            raise _refuse(404, "UNKNOWN_ROBOT")
        mine = store.open_for(body.robot_id, principal.principal_id)
        if mine:   # one open request per robot per requester: a repeat is the same ask, not another beep
            return mine[0]
        if len(store.open_for(body.robot_id)) >= MAX_OPEN_PER_ROBOT:
            raise _refuse(409, "TOO_MANY_OPEN_REQUESTS", limit=MAX_OPEN_PER_ROBOT)
        record = store.create(robot_id=body.robot_id, kind=body.kind, text=body.text, why=body.why,
                              requested_by=principal.principal_id, ttl_s=body.expires_s)
        if robots is not None and record["robot_id"]:
            await show_newest(record["robot_id"])
        return store.get(record["id"])

    @app.get("/api/fleet/person-requests", dependencies=read_guard, tags=["fleet"])
    async def list_person_requests(state: Optional[str] = Query(None, pattern="^(open|done|cannot|expired|withdrawn)$"),
                                   robot_id: Optional[str] = Query(None, min_length=1, max_length=96)) -> dict:
        return {"requests": store.list(state=state, robot_id=robot_id), "motion": False}

    @app.get("/api/fleet/person-requests/{request_id}", dependencies=read_guard, tags=["fleet"])
    async def get_person_request(request_id: str) -> dict:
        return known(request_id)

    @app.post("/api/fleet/person-requests/{request_id}/answer", tags=["fleet"])
    async def answer_person_request(request_id: str, body: PersonRequestAnswer,
                                    principal=Depends(require_named_operator)) -> dict:
        known(request_id)
        record = store.close(request_id, body.answer, by=principal.principal_id, note=body.note)
        if record is None:
            raise _refuse(409, "PERSON_REQUEST_NOT_OPEN", state=known(request_id)["state"])
        await after_close(record)
        return {**store.get(request_id), "motion": False}

    @app.post("/api/fleet/person-requests/{request_id}/withdraw", tags=["fleet"])
    async def withdraw_person_request(request_id: str, principal=Depends(require_proposer)) -> dict:
        record = known(request_id)
        if record["requested_by"] != principal.principal_id:
            raise _refuse(403, "NOT_THE_REQUESTER")
        closed = store.close(request_id, "withdrawn", by=principal.principal_id)
        if closed is None:
            raise _refuse(409, "PERSON_REQUEST_NOT_OPEN", state=record["state"])
        await after_close(closed)
        return {**store.get(request_id), "motion": False}
