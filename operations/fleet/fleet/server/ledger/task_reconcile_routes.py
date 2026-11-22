"""Named-operator reconciliation of UNKNOWN navigation tasks after verified CORE quiescence (D-1071)."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import time

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

_LOG = logging.getLogger(__name__)
_QUIESCENCE_FALSE_FLAGS = ("admitting", "pending_submission", "actuating_callback", "lease_active")
_NAV_IDLE_STATES = frozenset({"IDLE", "ARRIVED", "CANCELED", "FAILED"})


class _PrefetchedClient:
    """Serve an already-fetched CORE readback once so transport errors surface before task_result."""

    def __init__(self, inner, expected_path: str, payload: object) -> None:
        self._inner = inner
        self._expected_path = expected_path
        self._payload = payload

    async def _get(self, path: str):
        if path == self._expected_path:
            return self._payload
        return await self._inner._get(path)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class TaskReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operator_confirmed: StrictBool
    expected_attempt_id: str = Field(min_length=1, max_length=128)

    @field_validator("operator_confirmed")
    @classmethod
    def _require_confirmation(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("explicit operator confirmation required")
        return value


def quiescence_proof_ok(nav_state: object, elapsed_s: float) -> bool:
    """Verify D-732 live CORE quiescence proof within its 2 s sampling window."""
    if not isinstance(nav_state, dict) or not 0.0 <= elapsed_s <= 2.0:
        return False
    owner = nav_state.get("owner")
    if not isinstance(owner, dict):
        return False
    owner_boot = owner.get("boot_id")
    if not isinstance(owner_boot, str) or not owner_boot:
        return False
    if "owner_run_id" not in owner or owner["owner_run_id"] is not None:
        return False
    owner_gen = owner.get("owner_generation")
    if type(owner_gen) is not int or owner_gen < 0:
        return False
    # Zero native runs in this CORE boot leave operation/quiescence null when idle (D-732).
    if ("operation" in nav_state and nav_state["operation"] is None
            and "quiescence" in nav_state and nav_state["quiescence"] is None):
        return nav_state.get("lookup") == "UNKNOWN" and nav_state.get("navigation") == "IDLE"
    if nav_state.get("navigation") not in _NAV_IDLE_STATES or nav_state.get("lookup") != "FOUND":
        return False
    proof = nav_state.get("quiescence")
    operation = nav_state.get("operation")
    if not isinstance(proof, dict) or not isinstance(operation, dict):
        return False
    op_run_id = operation.get("run_id")
    if (operation.get("phase") != "TERMINAL" or operation.get("boot_id") != owner_boot
            or not isinstance(op_run_id, str) or not op_run_id
            or proof.get("requested_run_id") != op_run_id):
        return False
    try:
        observed = datetime.fromisoformat(proof["observed_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    if observed.utcoffset() is None:
        return False
    if proof.get("boot_id") != owner_boot:
        return False
    if "owner_run_id" not in proof or proof["owner_run_id"] is not None:
        return False
    if proof.get("quiescent") is not True:
        return False
    if any(proof.get(key) is not False for key in _QUIESCENCE_FALSE_FLAGS):
        return False
    proof_gen = proof.get("owner_generation")
    transport_gen = proof.get("transport_generation")
    if type(proof_gen) is not int or proof_gen != owner_gen:
        return False
    if type(transport_gen) is not int or transport_gen < 0:
        return False
    return True


def install_task_reconcile_routes(
    app, *, console, task_service, require_named_operator, native_task_result=None,
) -> None:
    @app.post("/api/fleet/tasks/{task_id}/reconcile", tags=["fleet-tasks"])
    async def reconcile_task(
        task_id: str,
        body: TaskReconcileRequest,
        principal=Depends(require_named_operator),
    ) -> dict:
        task = task_service.store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
        if task["status"] != "UNKNOWN":
            raise HTTPException(status_code=409, detail={"code": "TASK_NOT_UNKNOWN"})
        if task["attempt_id"] != body.expected_attempt_id:
            raise HTTPException(status_code=409, detail={"code": "ATTEMPT_MISMATCH"})

        robot_id = task["robot_id"]
        op = (task.get("receipt") or {}).get("operation")
        if op is not None:
            if native_task_result is None:
                raise HTTPException(status_code=503, detail={"code": "CORE_QUIESCENCE_UNAVAILABLE"})
            run_id = op.get("run_id") if isinstance(op, dict) else None
            probe_path = "/api/v1/navigation/state" + (
                f"?run_id={run_id}" if isinstance(run_id, str) and run_id else ""
            )
            try:
                client = console._client(robot_id)
                prefetched = await asyncio.wait_for(client._get(probe_path), 2.0)
                await native_task_result(
                    task_service.store,
                    _PrefetchedClient(client, probe_path, prefetched),
                    task,
                    events=task_service.core_events,
                )
            except Exception as exc:
                _LOG.warning("native reconcile failed task=%s robot=%s: %s", task_id, robot_id, type(exc).__name__)
                raise HTTPException(status_code=503, detail={"code": "CORE_QUIESCENCE_UNAVAILABLE"}) from exc
            updated = task_service.store.get_task(task_id)
            if updated is not None and (updated.get("receipt") or {}).get("safe_released") is True:
                return {"task": updated, "reconciled": True, "evidence": "NATIVE_READBACK"}
            raise HTTPException(status_code=409, detail={
                "code": "ROBOT_NOT_QUIESCENT",
                "message": "CORE native readback did not prove quiescence; claim kept locked",
            })

        try:
            client = console._client(robot_id)
            await console.cancel(robot_id)
        except Exception as exc:
            _LOG.warning("reconcile cancel unreachable task=%s robot=%s: %s", task_id, robot_id, type(exc).__name__)
            raise HTTPException(status_code=503, detail={"code": "ROBOT_UNREACHABLE"}) from exc

        try:
            started = time.monotonic()
            nav_state = await asyncio.wait_for(client._get("/api/v1/navigation/state"), 2.0)
            elapsed = time.monotonic() - started
        except Exception as exc:
            _LOG.warning("reconcile navigation/state failed task=%s robot=%s: %s",
                         task_id, robot_id, type(exc).__name__)
            raise HTTPException(status_code=503, detail={"code": "CORE_QUIESCENCE_UNAVAILABLE"}) from exc

        if not quiescence_proof_ok(nav_state, elapsed):
            raise HTTPException(status_code=409, detail={
                "code": "ROBOT_NOT_QUIESCENT",
                "message": "CORE did not prove quiescence; claim kept locked",
            })

        quiescence_record = (
            nav_state["quiescence"]
            if isinstance(nav_state.get("quiescence"), dict)
            else {
                "no_native_run_in_boot": True,
                "boot_id": nav_state["owner"]["boot_id"],
                "owner_generation": nav_state["owner"]["owner_generation"],
                "owner_run_id": None,
                "navigation": "IDLE",
            }
        )
        try:
            updated = task_service.store.reconcile_unknown_task(
                task_id,
                expected_attempt_id=body.expected_attempt_id,
                actor_id=principal.principal_id,
                quiescence=quiescence_record,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={
                "code": "TASK_RECONCILE_CONFLICT", "message": str(exc),
            }) from exc
        return {
            "task": updated,
            "reconciled": True,
            "evidence": "CORE_QUIESCENCE_PROOF",
            "quiescence": quiescence_record,
        }
