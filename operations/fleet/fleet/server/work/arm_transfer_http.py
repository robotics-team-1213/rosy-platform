"""Shared HTTP origin guard and domain error mapping for ARM transfer owner and relay routes."""

import inspect
import sqlite3

import httpx
from fastapi import HTTPException, Request

from core_common.protocol.account_access import same_origin
from fleet.swarm.transport import RobotApiError
from .local_action_transport import LocalActionUnavailable
from .mission_store import MissionConflict


def require_write_origin(request: Request) -> None:
    if request.headers.get("origin") is not None and not same_origin(request):
        raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"})


def unavailable_arm_transfer_error(row=None) -> HTTPException:
    detail = {"code": "ARM_TRANSFER_JOB_UNAVAILABLE"}
    if row is not None:  # what this unit last saw, for operators; never a current job state
        detail["last_projection"] = {
            "status": row["status"],
            "updated_at": row["updated_at"],
            "job_status": row["result"].get("job", {}).get("status"),
        }
    return HTTPException(503, detail=detail)


async def call_arm_transfer_domain(fn, *, value_error_is_conflict: bool = False):
    try:
        result = fn() if callable(fn) else fn
        if inspect.isawaitable(result):
            return await result
        return result
    except KeyError:
        raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"}) from None
    except PermissionError:
        raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"}) from None
    except MissionConflict:
        raise HTTPException(409, detail={"code": "ARM_TRANSFER_JOB_CONFLICT"}) from None
    except ValueError:
        if value_error_is_conflict:
            raise HTTPException(409, detail={"code": "ARM_TRANSFER_JOB_CONFLICT"}) from None
        raise unavailable_arm_transfer_error() from None
    except (ConnectionError, LocalActionUnavailable, OSError, sqlite3.Error, RobotApiError, httpx.HTTPError):
        raise unavailable_arm_transfer_error() from None
