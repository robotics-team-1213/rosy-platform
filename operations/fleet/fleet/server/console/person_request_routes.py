"""D-721 Amendment: 사람 부탁 routes. A request asks a person for something physical; the answer is their statement.

An answer closes the record and, for a request that reached a robot, tells that robot to stop showing it. Nothing
else is sent: the answer never starts motion, releases a stop or satisfies a check. Tools still read the evidence.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core_common.protocol.person_request import CONTROL, DEFAULT_TTL_S, ID_PATTERN, KINDS, MAX_TTL_S
from fleet.server.console.person_request_store import PersonRequestStore

logger = logging.getLogger(__name__)
STATES = ("open", "done", "cannot", "expired", "withdrawn")


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
                                  require_named_operator, known_robots, robots=None) -> None:
    """``known_robots()`` is an awaitable set of roster ids; ``robots`` holds ``put(robot_id, record)`` and
    ``clear(robot_id, request_id)`` (None: requests stay on the console)."""
    app.state.person_requests = store

    async def push(record: dict) -> None:
        if robots is None or not record["robot_id"]:
            return
        try:
            await robots.put(record["robot_id"], record)
            store.set_delivery(record["id"], "delivered")
        except Exception as exc:  # noqa: BLE001 - a robot that cannot be reached is shown as not delivered
            logger.warning("person request %s not delivered to %s: %s", record["id"], record["robot_id"], type(exc).__name__)
            store.set_delivery(record["id"], "not_delivered", type(exc).__name__)

    async def pull(record: dict) -> None:
        if robots is None or not record["robot_id"] or record["delivery"]["state"] in ("not_sent", "no_robot"):
            return
        try:
            await robots.clear(record["robot_id"], record["id"])
            store.set_delivery(record["id"], "cleared")
        except Exception as exc:  # noqa: BLE001 - CORE also drops it by its own expiry
            store.set_delivery(record["id"], "clear_failed", type(exc).__name__)

    def known(request_id: str) -> dict:
        record = store.get(request_id) if len(request_id) <= 64 else None
        if record is None:
            raise _refuse(404, "PERSON_REQUEST_NOT_FOUND")
        return record

    @app.post("/api/fleet/person-requests", tags=["fleet"])
    async def create_person_request(body: PersonRequestCreate, principal=Depends(require_proposer)) -> dict:
        if body.robot_id is not None and body.robot_id not in await known_robots():
            raise _refuse(404, "UNKNOWN_ROBOT")
        record = store.create(robot_id=body.robot_id, kind=body.kind, text=body.text, why=body.why,
                              requested_by=principal.principal_id, ttl_s=body.expires_s)
        await push(record)
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
        await pull(record)
        return {**store.get(request_id), "motion": False}

    @app.post("/api/fleet/person-requests/{request_id}/withdraw", tags=["fleet"])
    async def withdraw_person_request(request_id: str, principal=Depends(require_proposer)) -> dict:
        record = known(request_id)
        if record["requested_by"] != principal.principal_id:
            raise _refuse(403, "NOT_THE_REQUESTER")
        closed = store.close(request_id, "withdrawn", by=principal.principal_id)
        if closed is None:
            raise _refuse(409, "PERSON_REQUEST_NOT_OPEN", state=record["state"])
        await pull(closed)
        return {**store.get(request_id), "motion": False}
