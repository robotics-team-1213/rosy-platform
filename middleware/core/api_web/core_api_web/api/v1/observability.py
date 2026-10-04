"""core_api_web.api.v1.observability — EVT-003 이벤트, LOG-001 감사 로그, OBS-101 metrics."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core_api_web.api.v1.common import admin, viewer
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_api_web.api.deps import worst


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
    # 기록이 멈춰 있으면 목록이 짧은 것과 구분되지 않는다. 감사 로그를 묻는
    # 자리가 "이 로그를 믿어도 되는가"를 함께 답할 유일한 자리다.
    return {"events": [e.model_dump() for e in events], "log": svc.audit.health()}


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
    ]
    audit = svc.audit.health()
    audit_lines = [
        # 이름이 `rosy_audit_write_failures` 였다면 아래 `_total` 카운터와 같은
        # 계열(family)이 되어, OpenMetrics 로 읽는 쪽에서 gauge 와 counter 가
        # 한 이름으로 충돌한다.
        "# HELP rosy_audit_write_failures_consecutive consecutive audit log write failures (LOG-001)",
        "# TYPE rosy_audit_write_failures_consecutive gauge",
        f"rosy_audit_write_failures_consecutive {audit['write_failures']}",
        # 게이지만 있으면 스크레이프 사이에서 실패했다 복구한 로봇은 늘 0 이다.
        # 누적 카운터는 되돌아가지 않으므로 `increase()` 로 그것이 보인다.
        "# HELP rosy_audit_write_failures_total audit log write failures since boot (LOG-001)",
        "# TYPE rosy_audit_write_failures_total counter",
        f"rosy_audit_write_failures_total {audit['write_failures_total']}",
        # 정리 실패는 기록 실패가 아니다. 감사 기록은 남고 있는데 파일이 30 일보다
        # 길게 자라는 중이라는 뜻이라, 경보 기준이 다르다.
        "# HELP rosy_audit_prune_failures_total audit log prune failures since boot",
        "# TYPE rosy_audit_prune_failures_total counter",
        f"rosy_audit_prune_failures_total {audit['prune_failures']}",
        # 실패가 아니라 "전제가 깨졌다"이다. 오르고 있으면 이 파일을 우리 말고
        # 누가 자르거나 갈아 끼우고 있다는 뜻이고, 그동안 정리는 무동작이다.
        "# HELP rosy_audit_prune_skipped_total prunes skipped because the file changed underneath",
        "# TYPE rosy_audit_prune_skipped_total counter",
        f"rosy_audit_prune_skipped_total {audit['prune_skipped']}",
        # 디스크가 아니라 발행한 쪽의 결함이다. 기록은 `repr` 로 바꿔 남았지만,
        # 오르고 있으면 어떤 이벤트의 `data` 가 JSON 이 될 수 없는 값을 싣고 있다.
        "# HELP rosy_audit_serialize_failures_total audit events whose data had to be repr()-ed",
        "# TYPE rosy_audit_serialize_failures_total counter",
        f"rosy_audit_serialize_failures_total {audit['serialize_failures']}",
        # 정리 실패가 아니다. 바꿔 끼우기는 끝났고, 정전이 그것을 되돌릴 수 있을 뿐이다.
        "# HELP rosy_audit_dir_sync_failures_total directory fsyncs that failed after an audit prune replace",
        "# TYPE rosy_audit_dir_sync_failures_total counter",
        f"rosy_audit_dir_sync_failures_total {audit['dir_sync_failures']}",
    ]
    diagnostics_lines = [
        "# HELP rosy_diagnostics_health component health (0=OK,1=UNKNOWN,2=WARNING,3=ERROR)",
        "# TYPE rosy_diagnostics_health gauge",
    ]
    lines += audit_lines + diagnostics_lines
    for component, health in snap.diagnostics_summary.items():
        lines.append(f'rosy_diagnostics_health{{component="{component}"}} {_HEALTH_VALUE[health.value]}')
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
