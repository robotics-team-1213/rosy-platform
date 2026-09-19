"""core_api_web.api.v1.observability — EVT-003 이벤트, LOG-001 감사 로그, OBS-101 metrics."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core_api_web.api.v1.common import admin, viewer
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_features.diagnostics.collector import worst


events_router = APIRouter(prefix="/api/v1/events", tags=["events"])
logs_router = APIRouter(prefix="/api/v1/logs", tags=["logs"])


@events_router.get("")
def list_events(since_seq: int | None = None, limit: int = 100,
                _: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    events = svc.events.history(since_seq=since_seq, limit=limit)
    return {"events": [e.model_dump() for e in events], "last_seq": svc.events.last_seq}


@logs_router.get("/audit")
def list_audit_logs(
    since_seq: int | None = None,
    limit: int = 500,
    _: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    events = svc.audit.history(since_seq=since_seq, limit=min(limit, 2000))
    return {"events": [e.model_dump() for e in events]}

diagnostics_router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])


def _components(svc: CoreServicesLike) -> dict:
    """DIAG-001. `/metrics` 와 같은 출처를 읽는다 — 두 화면이 다른 값을 보이면
    운영자는 어느 쪽을 믿을지 알 수 없다."""
    return svc.state.snapshot().diagnostics_summary


@diagnostics_router.get("")
def list_diagnostics(_: AuthContext = Depends(viewer),
                     svc: CoreServicesLike = Depends(get_services)):
    components = _components(svc)
    return {
        "health": worst(list(components.values())).value,
        "components": {name: health.value for name, health in components.items()},
    }


@diagnostics_router.get("/control-adapter")
def control_adapter_diagnostic(_: AuthContext = Depends(admin),
                               svc: CoreServicesLike = Depends(get_services)):
    """Return calibration binding metadata without exposing parameters or secrets."""
    adapter = svc.control_adapter
    if adapter is None:
        return {
            "enabled": False,
            "policy_revision": None,
            "calibration_revision": None,
            "calibration_digest": None,
        }
    return {
        "enabled": bool(getattr(adapter, "enabled", False)),
        "policy_revision": getattr(adapter, "revision", None),
        "calibration_revision": getattr(adapter, "calibration_revision", None),
        "calibration_digest": getattr(adapter, "calibration_digest", None),
    }


@diagnostics_router.get("/{component}")
def diagnostic_detail(component: str, _: AuthContext = Depends(viewer),
                      svc: CoreServicesLike = Depends(get_services)):
    components = _components(svc)
    if component not in components:
        raise ApiError("NOT_FOUND", 404, f"unknown diagnostics component: {component}")
    return {"component": component, "health": components[component].value}


metrics_router = APIRouter(tags=["metrics"])

_HEALTH_VALUE = {"OK": 0, "UNKNOWN": 1, "WARNING": 2, "ERROR": 3}


@metrics_router.get("/metrics")
def metrics(svc: CoreServicesLike = Depends(get_services)):
    import time as _time

    snap = svc.state.snapshot()
    lines = [
        "# HELP rosy_uptime_seconds core process uptime",
        "# TYPE rosy_uptime_seconds gauge",
        f"rosy_uptime_seconds {(_time.time() - svc.started_at):.1f}",
        "# HELP rosy_state_seq state snapshot sequence",
        "# TYPE rosy_state_seq counter",
        f"rosy_state_seq {snap.seq}",
        "# HELP rosy_events_published_total events published",
        "# TYPE rosy_events_published_total counter",
        f"rosy_events_published_total {svc.events.last_seq}",
        "# HELP rosy_battery_percent battery percent estimate",
        "# TYPE rosy_battery_percent gauge",
        f"rosy_battery_percent {snap.battery.percent if snap.battery.percent is not None else -1}",
        "# HELP rosy_diagnostics_health component health (0=OK,1=UNKNOWN,2=WARNING,3=ERROR)",
        "# TYPE rosy_diagnostics_health gauge",
    ]
    for component, health in snap.diagnostics_summary.items():
        lines.append(f'rosy_diagnostics_health{{component="{component}"}} {_HEALTH_VALUE[health.value]}')
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
