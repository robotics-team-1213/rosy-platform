"""Existing native navigation HTTP calls; guarded transport remains the sole sender."""
from uuid import UUID

from core_common.protocol.schemas import ScopedNavigationCancelRequest


def goal_lease_supported(caps: dict | None) -> bool:
    """The robot's rosy.controls/1 base announces ``goal_lease: true``. An older CORE would
    ignore ``lease_ttl_s``, so without it a Fleet goal is unbounded."""
    items = (((caps or {}).get("controls") or {}).get("items") or []) if isinstance(caps, dict) else []
    return any(isinstance(item, dict) and item.get("kind") == "base_velocity"
               and item.get("goal_lease") is True for item in items)


class NavigationTransport:
    async def navigation_cancel(self, *, advance_generation: bool = False) -> dict:
        return await self._post("/api/v1/navigation/cancel",
                                {"advance_generation": True} if advance_generation else None)

    async def navigation_cancel_scoped(self, *, expected_boot_id, run_id, correlation_id) -> dict:
        body = ScopedNavigationCancelRequest(expected_boot_id=expected_boot_id, run_id=run_id,
                                              correlation_id=correlation_id).model_dump(mode="json")
        # A missing scoped endpoint must never fall back to cancelling today's unrelated goal.
        response = await self._post("/api/v1/navigation/cancel-scoped", body)
        operation = response.get("operation") if isinstance(response, dict) else None
        if (not isinstance(operation, dict) or not isinstance(response.get("navigation"), str)
                or operation.get("boot_id") != body["expected_boot_id"]
                or operation.get("run_id") != body["run_id"]
                or operation.get("correlation_id") != body["correlation_id"]
                or operation.get("phase") != "TERMINAL" or operation.get("result") != "CANCELED"):
            raise ValueError("SCOPED_CANCEL_RESPONSE_UNVERIFIED")
        return response

    async def navigation_path(self) -> dict:
        """현재 계획 경로(map 프레임 폴리라인). Fleet 이 교행을 미리 보는 유일한 재료다."""
        return await self._get("/api/v1/navigation/path")

    async def navigation_plan(self, x: float, y: float, yaw: float, *, correlation_id: str,
                              expected_map_grid_id: str, line_handoff: dict | None = None) -> dict:
        body = {"x": x, "y": y, "yaw": yaw, "correlation_id": correlation_id,
                "expected_map_grid_id": expected_map_grid_id}
        if line_handoff is not None:
            body["line_stop"] = {key: line_handoff.get(key) for key in
                                 ("lease_id", "trip_id", "job_id", "junction_seq", "stop_place_id")}
        return await self._post("/api/v1/navigation/bound-plan", body)

    async def navigation_goal(self, x: float, y: float, yaw: float, *,
                              correlation_id: str | None = None,
                              lease_ttl_s: float | None = None,
                              expected_boot_id: str | None = None,
                              expected_owner_generation: int | None = None,
                              expected_map_grid_id: str | None = None,
                              line_handoff: dict | None = None, plan_id: str | None = None) -> dict:
        body = {"x": x, "y": y, "yaw": yaw}
        if expected_map_grid_id is not None:
            if not plan_id or not correlation_id:
                raise ValueError("BOUND_GOAL_PLAN_REQUIRED")
            body["plan_id"] = str(UUID(plan_id))
        if correlation_id is not None:
            body["correlation_id"] = correlation_id
        if lease_ttl_s is not None:  # D-550 10: only to a robot that advertises goal_lease
            body["lease_ttl_s"] = lease_ttl_s
        if expected_boot_id is not None or expected_owner_generation is not None:
            if expected_boot_id is None or expected_owner_generation is None:
                raise ValueError('NATIVE_OWNER_EPOCH_PAIR_REQUIRED')
            body.update(expected_boot_id=expected_boot_id, expected_owner_generation=expected_owner_generation)
        if line_handoff is not None:
            if (not correlation_id or not expected_map_grid_id
                    or expected_boot_id is None or expected_owner_generation is None):
                raise ValueError("LINE_HANDOFF_GOAL_SCOPE_REQUIRED")
            body.update(expected_map_grid_id=expected_map_grid_id,
                        lease_id=line_handoff["lease_id"], trip_id=line_handoff["trip_id"],
                        junction_seq=line_handoff["junction_seq"], stop_place_id=line_handoff["stop_place_id"],
                        job_id=line_handoff.get("job_id"))
            return await self._post("/api/v1/navigation/line-handoff-goal", body)
        if expected_map_grid_id is not None:
            body["expected_map_grid_id"] = expected_map_grid_id
            return await self._post("/api/v1/navigation/bound-goal", body)
        return await self._post("/api/v1/navigation/goal", body)

    async def navigation_goal_lease(self, correlation_id: str, ttl_s: float, *, speed_grant=None) -> dict:
        """D-550 10: renew a leased goal; 409 GOAL_LEASE_NOT_ACTIVE once it is not active."""
        return await self._post("/api/v1/navigation/goal/lease",
                                {"correlation_id": correlation_id, "ttl_s": ttl_s,
                                 **({"speed_grant": speed_grant} if speed_grant is not None else {})})

    async def navigation_route(self, points: list[dict], *, road_speed_controlled=False,
                               expected_map_grid_id: str | None = None,
                               correlation_id: str | None = None,
                               lease_ttl_s: float | None = None,
                               expected_boot_id: str | None = None,
                               expected_owner_generation: int | None = None) -> dict:
        """D-1009: drive ordered pass/stop points in one native run (`POST /api/v1/navigation/route`)."""
        if not points:
            raise ValueError("ROUTE_POINTS_REQUIRED")
        body: dict = {"points": points}
        if road_speed_controlled:
            body["road_speed_controlled"] = True
        if correlation_id is not None:
            body["correlation_id"] = correlation_id
        if lease_ttl_s is not None:
            body["lease_ttl_s"] = lease_ttl_s
        if expected_boot_id is not None or expected_owner_generation is not None:
            if expected_boot_id is None or expected_owner_generation is None:
                raise ValueError("NATIVE_OWNER_EPOCH_PAIR_REQUIRED")
            body.update(expected_boot_id=expected_boot_id, expected_owner_generation=expected_owner_generation)
        if expected_map_grid_id is not None:
            body["expected_map_grid_id"] = expected_map_grid_id
            return await self._post("/api/v1/navigation/bound-route", body)
        return await self._post("/api/v1/navigation/route", body)

    async def navigation_handover(self, *, expected_boot_id, run_id, expected_owner_generation, correlation_id,
                                  expected_map_grid_id: str | None = None):
        if (type(expected_owner_generation) is not int or expected_owner_generation < 0
                or not isinstance(correlation_id, str) or not 1 <= len(correlation_id) <= 128):
            raise ValueError('NATIVE_HANDOVER_SCOPE_INVALID')
        boot, run = str(UUID(str(expected_boot_id))), str(UUID(str(run_id)))
        request = dict(expected_boot_id=boot, run_id=run, expected_owner_generation=expected_owner_generation,
                       correlation_id=correlation_id)
        if expected_map_grid_id is not None:
            request["expected_map_grid_id"] = expected_map_grid_id
        body = await self._post('/api/v1/navigation/handover', request)
        if (body.get('accepted') is not True or body.get('mode') != 'IDLE'
                or body.get('run_id') != run or body.get('boot_id') != boot
                or type(body.get('owner_generation')) is not int
                or body['owner_generation'] != expected_owner_generation):
            raise ValueError('NATIVE_HANDOVER_RESPONSE_UNVERIFIED')
        if expected_map_grid_id is not None and (
                body.get("map_grid_id") != expected_map_grid_id
                or type(body.get("idle_mode_epoch")) is not int or body["idle_mode_epoch"] < 0):
            raise ValueError("NATIVE_HANDOVER_GRID_RESPONSE_UNVERIFIED")
        return body
