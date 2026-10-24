"""Existing native navigation HTTP calls; guarded transport remains the sole sender."""
from uuid import UUID

from core_common.protocol.schemas import ScopedNavigationCancelRequest


class NavigationTransport:
    async def navigation_cancel(self) -> dict:
        return await self._post("/api/v1/navigation/cancel")

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

    async def navigation_goal(self, x: float, y: float, yaw: float, *,
                              correlation_id: str | None = None,
                              lease_ttl_s: float | None = None,
                              expected_boot_id: str | None = None,
                              expected_owner_generation: int | None = None) -> dict:
        body = {"x": x, "y": y, "yaw": yaw}
        if correlation_id is not None:
            body["correlation_id"] = correlation_id
        if lease_ttl_s is not None:  # D-550 10: only to a robot that advertises goal_lease
            body["lease_ttl_s"] = lease_ttl_s
        if expected_boot_id is not None or expected_owner_generation is not None:
            if expected_boot_id is None or expected_owner_generation is None:
                raise ValueError('NATIVE_OWNER_EPOCH_PAIR_REQUIRED')
            body.update(expected_boot_id=expected_boot_id, expected_owner_generation=expected_owner_generation)
        return await self._post("/api/v1/navigation/goal", body)

    async def navigation_goal_lease(self, correlation_id: str, ttl_s: float) -> dict:
        """D-550 10: renew a leased goal; 409 GOAL_LEASE_NOT_ACTIVE once it is not active."""
        return await self._post("/api/v1/navigation/goal/lease",
                                {"correlation_id": correlation_id, "ttl_s": ttl_s})

    async def navigation_handover(self, *, expected_boot_id, run_id, expected_owner_generation, correlation_id):
        if (type(expected_owner_generation) is not int or expected_owner_generation < 0
                or not isinstance(correlation_id, str) or not 1 <= len(correlation_id) <= 128):
            raise ValueError('NATIVE_HANDOVER_SCOPE_INVALID')
        boot, run = str(UUID(str(expected_boot_id))), str(UUID(str(run_id)))
        body = await self._post('/api/v1/navigation/handover', dict(expected_boot_id=boot, run_id=run,
            expected_owner_generation=expected_owner_generation, correlation_id=correlation_id))
        if (body.get('accepted') is not True or body.get('mode') != 'IDLE'
                or body.get('run_id') != run or body.get('boot_id') != boot
                or type(body.get('owner_generation')) is not int
                or body['owner_generation'] != expected_owner_generation):
            raise ValueError('NATIVE_HANDOVER_RESPONSE_UNVERIFIED')
        return body
