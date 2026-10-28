"""D-876 passive cache projection; no robot requests or operational gather."""

from collections.abc import Mapping
from datetime import datetime, timezone
import math

from fastapi import HTTPException, Response

from core_common.protocol.connect_reason import REASONS
from core_common.protocol.schemas import FleetLinkObservation, FleetMonitoringRead


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def cached_projection(cache, *, now, state_now):
    if cache is None:
        return FleetMonitoringRead(sampled_at=None, cache_age_s=None, robots=[])
    snapshot, captured, stamp = cache
    if (not all(_number(value) for value in (now, captured, stamp))
            or now < captured or stamp <= 0):
        raise ValueError("invalid monitoring cache time")
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("robots"), list):
        raise ValueError("invalid monitoring cache")
    rows = []
    for row in snapshot["robots"]:
        if not isinstance(row, Mapping):
            raise ValueError("invalid monitoring row")
        link = row.get("link")
        link = "unknown" if link is None else link
        error = row.get("error")
        reachable = error.get("reachable") if isinstance(error, Mapping) else None
        if type(reachable) is not bool:
            reachable = (True if link in ("up", "tls-refused") else
                         False if link in ("unreachable", "degraded", "protocol") else None)
        reason = row.get("link_reason")
        code = reason.get("code") if isinstance(reason, Mapping) else None
        code = code if isinstance(code, str) and code in REASONS else None
        observed = row.get("_state_mono")
        age = (float(state_now - observed)
               if _number(state_now) and _number(observed) and 0 <= observed <= state_now else None)
        rows.append(FleetLinkObservation(robot_id=row.get("robot_id"), link=link,
                                         reachable=reachable, reason_code=code, state_age_s=age))
    return FleetMonitoringRead(sampled_at=datetime.fromtimestamp(stamp, tz=timezone.utc),
                               cache_age_s=float(now - captured), robots=rows)


def install_monitoring_routes(app, gather, *, read_guard):
    @app.get("/api/fleet/monitoring", dependencies=read_guard, response_model=FleetMonitoringRead)
    def monitoring(response: Response):
        try:
            value = gather.cached_monitoring()
        except (ValueError, TypeError, OverflowError, OSError):
            raise HTTPException(503, detail={"code": "FLEET_MONITORING_UNAVAILABLE"},
                                headers={"Cache-Control": "no-store"}) from None
        response.headers["Cache-Control"] = "no-store"
        return value
