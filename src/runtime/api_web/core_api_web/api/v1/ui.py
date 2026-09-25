"""core_api_web.api.v1.ui — 역할별 화면 매니페스트 (D-204)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from core_api_web.api.deps import AuthContext, CoreServicesLike, ROLE_RANK, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.ui_manifest import build_manifest
from core_api_web.api.v1.common import viewer
from core_common.domain.capabilities import hardware_runtime_reason, withhold_hardware_flags
from core_common.protocol.schemas import UiSurfaceManifest

ui_router = APIRouter(prefix="/api/v1/ui", tags=["ui"])


@ui_router.get("/surfaces/{surface}", response_model=UiSurfaceManifest)
def surface_manifest(surface: str, request: Request, auth: AuthContext = Depends(viewer),
                     svc: CoreServicesLike = Depends(get_services)):
    registry = request.app.state.ui_registry
    if surface not in registry.surfaces:
        raise ApiError("NOT_FOUND", 404, "unknown surface")
    if auth.rank < ROLE_RANK[registry.surfaces[surface].min_role]:
        raise ApiError("FORBIDDEN", 403, "requires a higher role for this surface")
    # /system/capabilities 와 같은 CAP-001 본문을 읽는다 — 화면과 게이트가 다른 사실을 보면 안 된다.
    caps = svc.capability.to_dict()
    reason = hardware_runtime_reason(svc.config, svc.state)
    if reason:
        caps = withhold_hardware_flags(caps, reason)
    descriptors = svc.inventory().get("descriptors", [])
    return build_manifest(registry, surface, auth.role, caps, descriptors)
