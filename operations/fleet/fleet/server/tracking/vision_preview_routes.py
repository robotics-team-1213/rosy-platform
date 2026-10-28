"""Signed direct Vision preview grants; measured confirmation is operator-only."""
from typing import Optional
import hmac
from hashlib import sha256

from core_common.protocol.vision_preview import VisionLeaseSigner
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from core_common.protocol.vision_preview import PreviewRectification, validate_measured_request
from fleet.server.site_auth import SitePrincipal


def configure_vision_previews(console, *, console_token, vision_lease_secret, vision_sources,
                              discovery_token, sightings, site_users, workcell_observations=None):
    if workcell_observations is not None:
        preview_sources = workcell_observations.camera_source_ids()
        if set(preview_sources).intersection(vision_sources):
            raise ValueError("Workcell preview source collision with an existing Vision source")
        vision_sources = (*vision_sources, *preview_sources)
    signer = VisionLeaseSigner(vision_lease_secret) if vision_lease_secret else None
    if signer is not None:
        if console_token is not None and hmac.compare_digest(vision_lease_secret, console_token):
            raise ValueError("vision preview secret must differ from Fleet credentials")
        if (console.uses_rest_token(vision_lease_secret)
                or console.uses_agent_pairing_token(vision_lease_secret)):
            raise ValueError("vision preview secret must differ from robot credentials")
        if discovery_token is not None and hmac.compare_digest(vision_lease_secret, discovery_token):
            raise ValueError("vision preview secret must differ from discovery credentials")
        if sightings is not None and sightings.uses_token(vision_lease_secret):
            raise ValueError("vision preview secret must differ from sighting credentials")
        digest = sha256(vision_lease_secret.encode("utf-8")).hexdigest()
        if site_users is not None and any(hmac.compare_digest(digest, item) for item in site_users):
            raise ValueError("vision preview secret must differ from site user credentials")
        if len(set(vision_sources)) != len(vision_sources) or any(
                not isinstance(source, str) or not source for source in vision_sources):
            raise ValueError("vision preview sources must be unique non-empty ids")
    return signer, vision_sources


class VisionLeaseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    source_id: str
    rectification: Optional[dict[str, object]] = None
    measured: Optional[dict[str, object]] = None

    @field_validator('rectification')
    @classmethod
    def valid_rectification(cls, value):
        return PreviewRectification.from_mapping(value).as_dict() if value is not None else None

    @field_validator('measured')
    @classmethod
    def valid_measured(cls, value):
        return validate_measured_request(value) if value is not None else None

    @model_validator(mode='after')
    def separate_transform(self):
        if self.measured is not None and self.rectification is not None:
            raise ValueError('measured and legacy transforms cannot be mixed')
        return self


def install_vision_preview_routes(app, *, signer, sources, require_camera_viewer, require_named_operator):
    from fleet.server.robot_media_routes import install_robot_media_routes   # D-801, off without its config
    install_robot_media_routes(app, require_camera_viewer=require_camera_viewer)

    @app.get('/api/fleet/vision/sources', tags=['vision-preview'])
    def vision_preview_sources(_principal: SitePrincipal = Depends(require_camera_viewer)):
        if signer is None:
            raise HTTPException(503, detail={'code': 'VISION_PREVIEW_DISABLED'})
        return {'sources': list(sources)}

    @app.post('/api/fleet/vision/lease', tags=['vision-preview'])
    def vision_preview_lease(body: VisionLeaseRequest,
                             principal: SitePrincipal = Depends(require_camera_viewer)):
        if signer is None:
            raise HTTPException(503, detail={'code': 'VISION_PREVIEW_DISABLED'})
        if body.source_id not in sources:
            raise HTTPException(404, detail={'code': 'UNKNOWN_VISION_SOURCE'})
        if body.measured is not None:
            grant = body.measured
            if grant['confirm_conditions']:
                if not principal.permits_site('fleet.operate', {'operator'}):
                    raise HTTPException(403, detail={'code': 'FORBIDDEN'})
                require_named_operator(principal=principal)
            service = getattr(app.state, 'measured_calibration', None)
            source = service.tracking._by_id.get(body.source_id) if service else None
            row = service.config(source)['record'] if source else None
            if (row is None or row['calibration_revision'] != grant['calibration_revision']
                    or row['bundle']['capture']['signature'] != grant['capture_signature']):
                raise HTTPException(409, detail={'code': 'PREVIEW_CALIBRATION_CHANGED'})
        token = signer.issue(principal_id=principal.principal_id, source_id=body.source_id, ttl_s=60,
                             rectification=body.rectification, measured=body.measured)
        return {'source_id': body.source_id, 'lease': token,
                'frame_path': f'/api/vision/sources/{body.source_id}/frame', 'expires_in_s': 60}
