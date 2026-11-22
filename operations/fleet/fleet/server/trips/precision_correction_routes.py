"""A named operator's current clearance can authorize one scoped correction."""

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core_common.protocol.evidence import STALE_POSE_S
from core_common.stop_pose import REPARK_MAX_FORWARD_M
from fleet.hub.hub import HubError
from fleet.server.channel.execution.outcomes.evidence import safe_proof
from fleet.server.goal_lease import NavigationStopped
from fleet.swarm.api.ports import RobotApiError


class CorrectionClearance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nav_run_id: str = Field(min_length=36, max_length=36)
    map_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    forward_m: float = Field(strict=True, ge=-REPARK_MAX_FORWARD_M, le=REPARK_MAX_FORWARD_M, allow_inf_nan=False)
    site_end: tuple[float, float]
    cable_and_path_clear: bool = Field(strict=True)


def _refuse(reason):
    raise HTTPException(409, detail={"code": reason})


async def dispatch_correction(console, runner, trip_id, clearance, *, cable_inhibited, actor):
    live = runner._find(trip_id)
    if live is None or not live.open or live.view.get("hold") is not None or not clearance.cable_and_path_clear:
        _refuse("NAMED_STOP_CORRECTION_CLEARANCE_REQUIRED")
    detail = live.view["detail"]
    nav = dict(detail.get("named_stop_operation") or {})
    evidence = dict(detail.get("named_stop_dispatch") or {})
    if nav.get("run_id") != clearance.nav_run_id or evidence.get("map_sha256") != clearance.map_sha256:
        _refuse("NAMED_STOP_CORRECTION_SCOPE_CHANGED")
    robot = live.view["robot_id"]
    client = console.clients().get(robot)
    if client is None or cable_inhibited(robot):
        _refuse("NAMED_STOP_CORRECTION_CABLE_OR_ROBOT_UNVERIFIED")
    maps = console._named_stop_site_maps
    active = maps.active_view() or {}
    place = next((row for row in active.get("map", {}).get("places", []) if row["id"] == evidence.get("place")), None)
    if active.get("sha256") != clearance.map_sha256 or place is None or place.get("precision_stop") is None:
        _refuse("NAMED_STOP_DISPATCH_FRAME_CHANGED")
    stop = console.goal_leases.stop_token(robot)
    before = console._clock()

    def ready():
        current = maps.active_view() or {}
        binding = maps.map_bindings.active(robot) or {}
        return (live.open and live.view.get("hold") is None and detail.get("named_stop_operation") == nav
                and detail.get("named_stop_dispatch") == evidence and console.clients().get(robot) is client
                and current.get("sha256") == clearance.map_sha256 and binding.get("binding_id") == evidence["binding_id"]
                and console.goal_leases.stop_token(robot) == stop and not cable_inhibited(robot)
                and console._clock() - before <= STALE_POSE_S)

    try:
        first = await runner.check_named_correction(live, evidence, place)
        if (first["forward_m"] != clearance.forward_m or tuple(first["site_end"]) != clearance.site_end
                or not ready()):
            _refuse("NAMED_STOP_CORRECTION_SCOPE_CHANGED")
        view = await client._get(f"/api/v1/navigation/state?run_id={clearance.nav_run_id}")
        operation = view.get("operation") or {}
        if (any(operation.get(k) != nav.get(k) for k in ("kind", "boot_id", "run_id", "correlation_id"))
                or operation.get("result") != "SUCCEEDED" or not safe_proof(view, operation) or not ready()):
            _refuse("NAMED_STOP_CORRECTION_NAV_UNVERIFIED")
        owner = view["owner"]["owner_generation"]
        handover = await client.navigation_handover(expected_boot_id=nav["boot_id"], run_id=nav["run_id"],
                          expected_owner_generation=owner, correlation_id=nav["correlation_id"],
                          expected_map_grid_id=evidence["map_grid_id"])
        preview = await runner.check_named_correction(live, evidence, place)
        if preview != first or not ready():
            _refuse("NAMED_STOP_CORRECTION_SCOPE_CHANGED")
        repark_owner = (await client._get("/api/v1/motion/repark/run")).get("owner") or {}
        if repark_owner.get("boot_id") != nav["boot_id"] or type(repark_owner.get("owner_generation")) is not int:
            _refuse("NAMED_STOP_CORRECTION_OWNER_UNVERIFIED")
        body = dict(forward_m=preview["forward_m"], left_m=0., expected_boot_id=nav["boot_id"],
                    expected_owner_generation=repark_owner["owner_generation"],
                    expected_idle_epoch=handover["idle_mode_epoch"], expected_map_grid_id=evidence["map_grid_id"],
                    expected_nav_run_id=nav["run_id"], expected_nav_generation=owner,
                    expected_nav_correlation_id=nav["correlation_id"], operator_name=actor)
        maps.record_event("named_stop.correction_clearance", actor, {"trip_id": trip_id, "robot_id": robot,
                          "nav_run_id": nav["run_id"], "map_sha256": clearance.map_sha256, "forward_m": clearance.forward_m})
        return await console.goal_leases.send_named_repark(robot, client, body, ready=ready)
    except (HubError, NavigationStopped, RobotApiError, ValueError) as exc:
        _refuse(getattr(exc, "code", "NAMED_STOP_CORRECTION_REFUSED"))
    except (OSError, httpx.HTTPError) as exc:
        raise HTTPException(503, detail={"code": "NAMED_STOP_CORRECTION_OUTCOME_UNAVAILABLE"}) from exc


def install_precision_correction_routes(app, *, console, runner, require_named_operator, cable_inhibited):
    @app.post("/api/fleet/trips/{trip_id}/correction-clearance", status_code=202, tags=["fleet"])
    async def correction_clearance(trip_id: str, body: CorrectionClearance, principal=Depends(require_named_operator)):
        actor = principal.principal_id
        if not 1 <= len(actor) <= 64:
            _refuse("NAMED_STOP_CORRECTION_OPERATOR_UNVERIFIED")
        return await dispatch_correction(console, runner, trip_id, body, cable_inhibited=cable_inhibited, actor=actor)
