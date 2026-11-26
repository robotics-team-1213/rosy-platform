"""Road route dispatch and scoped speed updates sharing the console goal lease table."""
from typing import Optional

from fleet.swarm.navigation_transport import goal_lease_supported


class RoadSpeedRefused(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class RoadRouteLeases:
    async def send_route(self, robot_id: str, client, caps: Optional[dict], points: list[dict],
                         correlation_id: Optional[str] = None, source: Optional[str] = None,
                         task_id: Optional[str] = None, *, expected_map_grid_id: str | None = None,
                         recheck=None, road_speed_controlled=False) -> dict:
        """Send one D-1009 pass/stop route under the goal lease."""
        if road_speed_controlled and not (goal_lease_supported(caps) and
                ((caps or {}).get("navigation") or {}).get("route_speed_authority") is True):
            raise RoadSpeedRefused("ROAD_SPEED_AUTHORITY_UNAVAILABLE")

        async def send(options):
            if road_speed_controlled:
                options["road_speed_controlled"] = True
            if recheck is not None:
                await recheck()
            return await client.navigation_route(points, **options)

        return await self._dispatch(robot_id, client, caps, send, correlation_id, source, task_id,
                                    expected_map_grid_id=expected_map_grid_id, road_speed_controlled=road_speed_controlled)

    async def update_road_speed(self, robot_id, correlation_id, grant):
        lease = self.get(robot_id)
        if (not lease or lease.get("source") != "trip" or lease.get("correlation_id") != correlation_id
                or not lease.get("road_speed_controlled")):
            raise RoadSpeedRefused("ROAD_SPEED_OWNER_CHANGED")
        return await self._clients[robot_id].navigation_goal_lease(correlation_id, lease["ttl_s"], speed_grant=grant)
