"""Authorized Vision preview listing and short-lived read lease routes."""
from typing import Optional
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from fleet.server.site_auth import SitePrincipal


class VisionLeaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: str
    rectification: Optional[dict[str, object]] = None

    @field_validator("rectification")
    @classmethod
    def _valid_rectification(cls, value):
        if value is None:
            return None
        from core_common.protocol.vision_preview import PreviewRectification
        return PreviewRectification.from_mapping(value).as_dict()


def install_vision_preview_routes(app, *, vision_signer, vision_sources, require_camera_viewer):
    @app.get("/api/fleet/vision/sources", tags=["vision-preview"])
    def vision_preview_sources(_principal: SitePrincipal = Depends(require_camera_viewer)) -> dict:
        if vision_signer is None:
            raise HTTPException(status_code=503, detail={"code": "VISION_PREVIEW_DISABLED"})
        return {"sources": list(vision_sources)}

    @app.post("/api/fleet/vision/lease", tags=["vision-preview"])
    def vision_preview_lease(body: VisionLeaseRequest,
                             principal: SitePrincipal = Depends(require_camera_viewer)) -> dict:
        if vision_signer is None:
            raise HTTPException(status_code=503, detail={"code": "VISION_PREVIEW_DISABLED"})
        if body.source_id not in vision_sources:
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_VISION_SOURCE"})
        token = vision_signer.issue(principal_id=principal.principal_id,
                                    source_id=body.source_id, ttl_s=60,
                                    rectification=body.rectification)
        return {"source_id": body.source_id, "lease": token,
                "frame_path": f"/api/vision/sources/{body.source_id}/frame",
                "expires_in_s": 60}
