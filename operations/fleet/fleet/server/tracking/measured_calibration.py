"""D-775 preview admission and numeric readback; no frame or motion authority."""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core_common.protocol.measured_calibration import MeasuredCalibrationBundle
from .measured_calibration_store import CalibrationChanged
from .tracking import TrackingError


class MeasuredCalibrationApproval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    purpose: Literal['preview']
    kind: Literal['measured']
    bundle: MeasuredCalibrationBundle
    expected_revision: str | None = Field(max_length=160)
    limits: dict


class PreviewStatus(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    source_id: str = Field(min_length=1, max_length=64)
    calibration_revision: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    state: Literal['waiting', 'confirmation_required', 'applied', 'invalid']
    reason: str = Field(min_length=1, max_length=64)
    frame_seq: int | None = Field(default=None, ge=0)
    render_age_s: float | None = Field(default=None, ge=0, lt=5, allow_inf_nan=False)

    @model_validator(mode='after')
    def applied_needs_frame(self):
        if self.state == 'applied' and self.frame_seq is None:
            raise ValueError('applied preview needs an actual rendered frame')
        return self


class MeasuredCalibrationService:
    def __init__(self, tracking, *, map_revision=None):
        self.tracking = tracking
        self.store = tracking.calibrations.preview
        self.map_revision = map_revision or (lambda map_id: None)
        self._reports = {}

    def _source(self, source_id):
        source = self.tracking._by_id.get(source_id)
        if source is None:
            raise TrackingError(404, 'UNKNOWN_SOURCE', 'no configured source')
        return source

    def approve(self, body, principal):
        bundle = body.bundle
        source = self._source(bundle.source_id)
        current = self.map_revision(source.map_id)
        if bundle.map_id != source.map_id or current is None or current != bundle.map_revision:
            raise TrackingError(409, 'MAP_REVISION_MISMATCH', 'current activated map revision required')
        try:
            row = self.store.approve(bundle.model_dump(mode='json', by_alias=True),
                                     expected_revision=body.expected_revision, approved_by=principal,
                                     approved_at=self.tracking._clock(), limits=body.limits)
        except CalibrationChanged as exc:
            raise TrackingError(409, 'PREVIEW_CALIBRATION_CHANGED', str(exc)) from exc
        except ValueError as exc:
            raise TrackingError(422, 'INVALID_MEASURED_CALIBRATION', str(exc)) from exc
        self._reports.pop(bundle.source_id, None)
        return row

    def revoke(self, source_id, expected_revision, principal):
        self._source(source_id)
        if not expected_revision:
            raise TrackingError(422, 'EXPECTED_REVISION_REQUIRED', 'preview revocation needs its revision')
        try:
            result = self.store.revoke(source_id, expected_revision=expected_revision,
                                       principal_id=principal, at=self.tracking._clock())
        except CalibrationChanged as exc:
            raise TrackingError(409, 'PREVIEW_CALIBRATION_CHANGED', str(exc)) from exc
        self._reports.pop(source_id, None)
        return result

    def config(self, source):
        row = self.store.get(source.source_id)
        current = self.map_revision(source.map_id)
        reason = 'not_approved' if row is None else 'ok'
        if row and (row['map_id'] != source.map_id or row['bundle']['map_revision'] != current):
            row, reason = None, 'map_changed'
        return {'record': row, 'map_revision': current, 'reason': reason, 'lease_s': 5.0}

    def report(self, authorization, body):
        source = self.tracking.authenticate(authorization)
        if body.source_id != source.source_id:
            raise TrackingError(403, 'SOURCE_MISMATCH', 'preview report source does not match token')
        row = self.config(source)['record']
        if row is None or row['calibration_revision'] != body.calibration_revision:
            raise TrackingError(409, 'PREVIEW_CALIBRATION_CHANGED', 'preview revision is not current')
        self._reports[source.source_id] = (body.model_dump(), self.tracking._clock())
        return {'accepted': True, 'source_id': source.source_id}

    def listing(self):
        rows = []
        now = self.tracking._clock()
        for row in self.store.all():
            source = self.tracking._by_id.get(row['source_id'])
            current = self.config(source)['record'] if source else None
            report = self._reports.get(row['source_id'])
            readback = {'state': 'waiting', 'reason': 'not_reported'}
            if current is None:
                readback = {'state': 'invalid', 'reason': 'map_changed'}
            elif report:
                body, stamp = report
                if (body['calibration_revision'] == row['calibration_revision']
                        and 0 <= now-stamp < 5-(body.get('render_age_s') or 0)):
                    readback = {**deepcopy(body), 'age_s': now-stamp}
                else:
                    readback = {'state': 'invalid', 'reason': 'readback_stale'}
            rows.append({**row, 'readback': readback})
        return {'calibrations': rows, 'use': 'preview-only', 'persistent': self.store.path is not None}


def active_map_revision(site_maps, map_id):
    view = site_maps.active_view()
    return view['sha256'] if view and view['map']['map_id'] == map_id else None
