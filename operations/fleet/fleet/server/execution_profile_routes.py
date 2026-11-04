"""v1.361 read-only execution profile: whether a business app may expect the arm to really move.

Nothing here sends a device command. The only owner contact is the existing identity query, cached
(10 s when accepted, 5 s when not, the dispatcher's own TTLs) so a polling app cannot load the owner.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends
from pydantic import BaseModel

IDENTITY_TTL_S, NEGATIVE_IDENTITY_TTL_S = 10.0, 5.0
DEVICE_TRIAL = "device_trial"


class ExecutionProducer(BaseModel):
    id: str
    kind: str
    authenticated: bool


class ExecutionProfileResponse(BaseModel):
    profile: str
    arm_execution: Literal["physical", "simulated", "closed"]
    revision: str | None
    observation_producers: list[ExecutionProducer]
    evidence_producers: list[ExecutionProducer]
    checked_at: datetime


def _device_identity_ok(identity, workcell_id, instance_id, expected) -> bool:
    """D-797 3, same conditions as StepJobDispatcher._device_trial_identity.
    shortcut: copied until D-977 3 extracts one shared function; fold both then."""
    return (identity.get("device") is True and identity.get("simulation") is not True
            and isinstance(expected, str) and expected != ""
            and identity.get("commissioning_revision") == expected
            and identity.get("instance_id") == instance_id and identity.get("workcell_id") == workcell_id)


def install_execution_profile_routes(app, *, deployment_profile, instances, grant_revisions, transport,
                                     workcell_observations, arm_transfer_observer, require_viewer,
                                     monotonic=time.monotonic):
    installed = dict(instances)
    revisions = grant_revisions or {}
    cache: dict[str, tuple[bool, float]] = {}

    def revision():
        if len(installed) != 1:
            return None
        row = revisions.get(next(iter(installed.values())), {})
        return row.get("commissioning_revision") or row.get("config_revision") or None

    def device_ok() -> bool:  # blocking: owner identity query over the local socket
        if len(installed) != 1 or transport is None:  # D-797: one arm only
            return False
        (workcell_id, instance_id), = installed.items()
        hit = cache.get(instance_id)
        if hit is not None and hit[1] > monotonic():
            return hit[0]
        try:
            ok = _device_identity_ok(transport.owner_identity(instance_id), workcell_id, instance_id,
                                     revisions.get(instance_id, {}).get("commissioning_revision"))
        except Exception:
            ok = False
        cache[instance_id] = (ok, monotonic() + (IDENTITY_TTL_S if ok else NEGATIVE_IDENTITY_TTL_S))
        return ok

    def evidence_producers():
        now = time.time()
        rows = []
        # the Cell registry exists only in the simulation profile and accepts only sim_model_pose (D-403 5)
        for service, fixed in ((app.state.goal_evidence_service, None),
                               (app.state.cell_goal_evidence_service, "sim_model_pose")):
            for producer in () if service is None else service.registry.producers:
                if producer.valid_until.timestamp() > now:
                    rows.append({"id": producer.producer_id, "authenticated": True,
                                 "kind": fixed or producer.evidence_source})
        return rows

    def observation_producers():
        rows = [] if workcell_observations is None else workcell_observations.producers()
        if arm_transfer_observer is not None and arm_transfer_observer.valid_until.timestamp() > time.time():
            rows.append({"id": arm_transfer_observer.producer_id, "kind": "arm_transfer_observer"})
        return [{**row, "authenticated": True} for row in rows]

    @app.get("/api/fleet/execution-profile", response_model=ExecutionProfileResponse, tags=["fleet-work"])
    async def execution_profile(principal=Depends(require_viewer)):
        if deployment_profile == "simulation":
            arm = "simulated"
        elif deployment_profile == DEVICE_TRIAL and await asyncio.to_thread(device_ok):
            arm = "physical"
        else:
            arm = "closed"  # production, an unknown profile, or a device_trial owner not proven
        return {"profile": deployment_profile, "arm_execution": arm, "revision": revision(),
                "observation_producers": observation_producers(), "evidence_producers": evidence_producers(),
                "checked_at": datetime.now(timezone.utc)}
