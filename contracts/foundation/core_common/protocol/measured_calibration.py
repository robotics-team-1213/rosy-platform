"""D-775 measured preview bundle. Numeric evidence, never command authority."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

_HASH = re.compile(r'^[0-9a-f]{64}$')
_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$')
_LENS_KEYS = {'status', 'applied', 'model', 'K', 'D', 'image_size', 'source_id',
              'capture_signature', 'training_rms_px', 'tilt_span', 'validation', 'revision'}
_FLOOR_KEYS = {'status', 'applied', 'map_id', 'pixel_space', 'lens_revision', 'source_id',
               'undistorted_to_map', 'reference_pixel', 'inliers', 'validation', 'revision'}


def _num(value):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or abs(value) > 1e9):
        raise ValueError('a bounded finite number is required')
    return value


def _values(value, count):
    if not isinstance(value, list) or len(value) != count:
        raise ValueError('invalid numeric array size')
    return [_num(v) for v in value]


def _matrix(value):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError('a 3x3 matrix is required')
    rows = [_values(row, 3) for row in value]
    a, b, c, d, e, f, g, h, i = sum(rows, [])
    scale = max(abs(v) for row in rows for v in row)
    determinant = a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)
    if not scale or abs(determinant)/scale**3 < 1e-12:
        raise ValueError('singular or ill-conditioned transform')
    return rows


def _metrics(value, keys, p95, maximum):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('independent validation metrics required')
    if any(_num(v) < 0 for v in value.values()) or value[p95] > value[maximum]:
        raise ValueError('invalid independent validation metrics')


def candidate_revision(value: Mapping, *, digests=None) -> str:
    """Reproduce D-636 candidate identity, including its original image digests."""
    raw = {key: v for key, v in value.items() if key != 'revision'}
    if digests is not None:
        raw['digests'] = list(digests)
    return hashlib.sha256(json.dumps(raw, sort_keys=True, allow_nan=False).encode()).hexdigest()[:24]


def bundle_digest(bundle) -> str:
    raw = bundle.model_dump(mode='json', by_alias=True) if isinstance(bundle, BaseModel) else dict(bundle)
    raw.pop('digest', None)
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


class MeasuredCalibrationBundle(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True, populate_by_name=True)

    schema_version: Literal['rosy.measured-calibration/1'] = Field(alias='schema')
    source_id: str = Field(min_length=1, max_length=64)
    map_id: str = Field(min_length=1, max_length=160)
    map_revision: str = Field(min_length=1, max_length=160)
    lens: dict[str, Any]
    floor: dict[str, Any]
    training_digests: list[str] = Field(min_length=8, max_length=100)
    validation_digests: list[str] = Field(min_length=2, max_length=100)
    survey_digest: str
    capture: dict[str, Any]
    bounds_m: list[float | int]
    evidence_kind: Literal['measured', 'synthetic']
    digest: str

    @model_validator(mode='after')
    def check_binding(self):
        if any(not _ID.fullmatch(v) for v in (self.source_id, self.map_id, self.map_revision)):
            raise ValueError('invalid source or map identity')
        digests = self.training_digests + self.validation_digests
        if (len(set(digests)) != len(digests)
                or any(not _HASH.fullmatch(v) for v in [*digests, self.survey_digest, self.digest])):
            raise ValueError('independent image and survey digests required')
        lens, floor = self.lens, self.floor
        if set(lens) != _LENS_KEYS or set(floor) != _FLOOR_KEYS:
            raise ValueError('complete lens and floor candidates required')
        for candidate in (lens, floor):
            if candidate['status'] != 'candidate' or candidate['applied'] is not False:
                raise ValueError('unapplied candidates required')
            if candidate['source_id'] != self.source_id:
                raise ValueError('candidate source mismatch')
        if floor['map_id'] != self.map_id or floor['pixel_space'] != 'undistorted':
            raise ValueError('undistorted floor in the selected map required')
        if floor['lens_revision'] != lens['revision']:
            raise ValueError('floor and lens revision mismatch')
        k = _matrix(lens['K'])
        if k[0][0] <= 0 or k[1][1] <= 0 or k[0][1] != 0 or k[1][0] != 0 or k[2] != [0, 0, 1]:
            raise ValueError('invalid intrinsics')
        count = {'pinhole': 5, 'fisheye': 4}.get(lens['model']) if isinstance(lens['model'], str) else None
        if count is None:
            raise ValueError('unsupported measured lens model')
        _values(lens['D'], count)
        size = lens['image_size']
        if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or not 32 <= v <= 8192 for v in size):
            raise ValueError('invalid measured JPEG dimensions')
        if _num(lens['training_rms_px']) < 0 or _num(lens['tilt_span']) < 0:
            raise ValueError('invalid lens metrics')
        _metrics(lens['validation'], ('p95_px', 'max_px', 'rms_px'), 'p95_px', 'max_px')
        h = _matrix(floor['undistorted_to_map'])
        reference = _values(floor['reference_pixel'], 2)
        if any(not 0 <= v < side for v, side in zip(reference, size)):
            raise ValueError('floor reference outside image')
        if abs(sum(a*b for a, b in zip(h[2], [*reference, 1]))) < 1e-10:
            raise ValueError('floor reference on horizon')
        if type(floor['inliers']) is not int or not 4 <= floor['inliers'] <= 10000:
            raise ValueError('floor inlier count required')
        _metrics(floor['validation'], ('p95_m', 'max_m'), 'p95_m', 'max_m')
        if (candidate_revision(lens, digests=digests) != lens['revision']
                or candidate_revision(floor) != floor['revision']):
            raise ValueError('candidate revision does not bind its content')
        capture = self.capture
        if set(capture) != {'signature', 'lens', 'rotation_deg'}:
            raise ValueError('explicit capture geometry required')
        signature = capture['signature']
        if (not isinstance(signature, str) or not 1 <= len(signature) <= 200
                or signature != lens['capture_signature']):
            raise ValueError('capture signature mismatch')
        if type(capture['rotation_deg']) is not int or capture['rotation_deg'] not in (0, 90, 180, 270):
            raise ValueError('invalid capture rotation')
        optical = capture['lens']
        if (not isinstance(optical, dict) or set(optical) != {'kind', 'focal_mm', 'hfov_deg'}
                or optical['kind'] not in ('standard', 'wide')
                or not 0 < _num(optical['focal_mm']) <= 1000 or not 0 < _num(optical['hfov_deg']) < 180):
            raise ValueError('reported lens identity required')
        bounds = _values(self.bounds_m, 4)
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            raise ValueError('nonempty map bounds required')
        if bundle_digest(self) != self.digest:
            raise ValueError('bundle digest mismatch')
        return self


def validate_bundle(raw: Mapping) -> MeasuredCalibrationBundle:
    if len(json.dumps(raw, allow_nan=False)) > 200000:
        raise ValueError('measured bundle is too large')
    return MeasuredCalibrationBundle.model_validate(deepcopy(raw))
