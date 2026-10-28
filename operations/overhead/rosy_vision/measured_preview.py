"""D-775 session-bound measured preview, separate from tracking/sightings."""
from copy import deepcopy
from dataclasses import dataclass
import itertools
import json
import math
import time
import uuid

import cv2
import numpy as np

from core_common.protocol.measured_calibration import bundle_digest, validate_bundle
from rosy_vision.camera_calibration import plane_image


@dataclass(frozen=True)
class PreviewTicket:
    source: str
    session: str
    geometry: dict
    generation: int
    deadline: float
    record: dict


class MeasuredPreview:
    def __init__(self, *, clock=time.monotonic, boot_id=None):
        self.clock, self.boot_id = clock, boot_id or uuid.uuid4().hex
        self._entries, self._generations = {}, itertools.count(1)
        self._consumed_grants = {}
        self._geometries, self._capture_epochs = {}, {}

    def session_id(self, link, source=None):
        base = f'{self.boot_id}:{link}'
        return f'{base}:{self._capture_epochs.get(source, 0)}' if source is not None else base

    def update(self, source, config, map_id):
        config = config if isinstance(config, dict) else {}
        record, reason = deepcopy(config.get('record')), config.get('reason', 'not_approved')
        if record is not None:
            try:
                bundle = validate_bundle(record['bundle'])
                raw = {k: v for k, v in record.items() if k != 'record_digest'}
                if (record.get('record_digest') != bundle_digest(raw)
                        or record.get('use') != 'preview-only' or record.get('purpose') != 'preview'
                        or record.get('kind') != 'measured' or bundle.evidence_kind != 'measured'
                        or bundle.source_id != source or bundle.map_id != map_id
                        or bundle.map_revision != config.get('map_revision')):
                    raise ValueError('invalid approval binding')
            except (ValueError, KeyError, TypeError):
                record, reason = None, 'invalid_config'
        previous = self._entries.get(source)
        identity = (record.get('record_digest') if record else None, map_id, config.get('map_revision'), reason)
        if previous is None or previous['identity'] != identity:
            previous = {'identity': identity, 'generation': next(self._generations), 'confirmed': None,
                        'session': None, 'rendered_at': None, 'frame_seq': None}
            self._entries[source] = previous
        lease = config.get('lease_s', 0)
        if type(lease) not in (int, float) or not math.isfinite(lease) or lease <= 0:
            lease = 0
        previous.update(record=record, reason=reason, deadline=self.clock()+min(5., lease))

    def _available(self, source):
        entry = self._entries.get(source)
        if entry is None or entry['record'] is None:
            raise ValueError(entry['reason'] if entry else 'not_approved')
        if self.clock() >= entry['deadline']:
            raise ValueError('config_stale')
        return entry

    @staticmethod
    def _expected(record):
        b = record['bundle']
        return {'image_size': b['lens']['image_size'], 'rotation_deg': b['capture']['rotation_deg'],
                'lens': b['capture']['lens']}

    def select(self, source, session, geometry, claims):
        entry = self._available(source)
        self.observe(source, session, geometry)
        record = entry['record']
        if geometry != self._expected(record):
            entry['confirmed'], entry['rendered_at'] = None, None
            raise ValueError('geometry_changed')
        entry['session'] = session
        if (claims.get('calibration_revision') != record['calibration_revision']
                or claims.get('session_id') != session
                or claims.get('capture_signature') != record['bundle']['capture']['signature']):
            raise ValueError('session_or_revision_changed')
        key = (session, record['calibration_revision'], json.dumps(geometry, sort_keys=True))
        if claims.get('confirm_conditions') is True:
            grant = claims.get('_grant_id') or json.dumps(claims, sort_keys=True)
            self._consumed_grants = {g: until for g, until in self._consumed_grants.items() if until > self.clock()}
            if grant not in self._consumed_grants and len(self._consumed_grants) < 256:
                entry['confirmed'] = key
                self._consumed_grants[grant] = self.clock()+120.
        if entry['confirmed'] != key:
            raise ValueError('confirmation_required')
        return PreviewTicket(source, session, deepcopy(geometry), entry['generation'],
                             entry['deadline'], deepcopy(record))

    def observe(self, source, session, geometry):
        """Receive every accepted frame's geometry, including changes between reads."""
        entry = self._entries.get(source)
        previous = self._geometries.get(source)
        self._geometries[source] = deepcopy(geometry)
        if previous is not None and previous != geometry:
            self._capture_epochs[source] = self._capture_epochs.get(source, 0)+1
            if entry:
                entry.update(confirmed=None, rendered_at=None, frame_seq=None,
                             generation=next(self._generations))
        if entry and entry['confirmed'] is not None:
            key = (session, entry['record']['calibration_revision'], json.dumps(geometry, sort_keys=True))
            if key != entry['confirmed']:
                entry.update(confirmed=None, rendered_at=None, frame_seq=None,
                             generation=next(self._generations))

    def complete(self, ticket, session, geometry, *, frame_seq):
        try:
            entry = self._available(ticket.source)
        except ValueError:
            return False
        if (self.clock() >= ticket.deadline or entry['generation'] != ticket.generation
                or session != ticket.session or entry['session'] != session
                or geometry != ticket.geometry or geometry != self._expected(entry['record'])):
            return False
        entry['rendered_at'], entry['frame_seq'] = self.clock(), frame_seq
        return True

    def status(self, source, session, geometry, *, fresh=True):
        entry = self._entries.get(source)
        record = entry['record'] if entry else None
        result = {'source_id': source, 'session_id': session,
                  'calibration_revision': record['calibration_revision'] if record else None,
                  'state': 'waiting', 'reason': 'not_approved', 'frame_seq': None}
        try:
            entry = self._available(source)
            self.observe(source, session, geometry)
            if not fresh:
                raise ValueError('frame_stale')
            if geometry != self._expected(entry['record']):
                entry['confirmed'], entry['rendered_at'] = None, None
                raise ValueError('geometry_changed')
            key = (session, record['calibration_revision'], json.dumps(geometry, sort_keys=True))
            if entry['confirmed'] != key:
                result.update(state='confirmation_required', reason='confirmation_required')
            elif entry['rendered_at'] is not None and 0 <= self.clock()-entry['rendered_at'] < 5:
                result.update(state='applied', reason='ok', frame_seq=entry['frame_seq'],
                              render_age_s=self.clock()-entry['rendered_at'])
            else:
                result.update(reason='not_rendered')
        except ValueError as exc:
            result.update(state='invalid', reason=str(exc))
        return result


def render_plane(jpeg, record):
    bundle = validate_bundle(record['bundle'])
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None or list(image.shape[1::-1]) != bundle.lens['image_size']:
        raise ValueError('decoded JPEG geometry mismatch')
    bounds = bundle.bounds_m
    ppm = min(400, math.floor(1920/max(bounds[2]-bounds[0], bounds[3]-bounds[1])))
    plane, mask = plane_image(image, bundle.lens, bundle.floor, bounds, source_id=bundle.source_id,
                              capture_signature=bundle.capture['signature'], px_per_m=ppm)
    ok, encoded = cv2.imencode('.jpg', plane)
    if not ok:
        raise ValueError('measured plane encode failed')
    return encoded.tobytes(), mask, (plane.shape[1], plane.shape[0]), bounds, ppm


def context(ingest, source):
    src, frame = ingest._sources.get(source), ingest.latest_frame(source)
    geometry = {'image_size': [frame.header.width, frame.header.height] if frame else None,
                'rotation_deg': frame.header.rotation_deg if frame else None, 'lens': ingest.source_lens(source)}
    link = getattr(src, 'link', 0)
    ingest.measured.observe(source, ingest.measured.session_id(link, source), geometry)
    session = ingest.measured.session_id(link, source)
    fresh = frame is not None and 0 <= time.time()-frame.captured_at <= ingest.preview_max_age_s
    return session, geometry, frame, fresh


def current_status(ingest, source):
    session, geometry, _, fresh = context(ingest, source)
    return {**ingest.measured.status(source, session, geometry, fresh=fresh), 'geometry': geometry}


async def frame_response(ingest, source, frame, lease):
    import asyncio
    from rosy_vision.ingest import _http_response
    try:
        session, geometry, _, fresh = context(ingest, source)
        if not fresh:
            raise ValueError('frame_stale')
        claims = {**lease['measured'], '_grant_id': lease.get('jti')}
        ticket = ingest.measured.select(source, session, geometry, claims)
        jpeg, mask, size, bounds, ppm = await asyncio.to_thread(render_plane, frame.jpeg, ticket.record)
        current_session, current_geometry, latest, fresh = context(ingest, source)
        if (not fresh or not 0 <= time.time()-frame.captured_at <= ingest.preview_max_age_s
                or not ingest.measured.complete(
                ticket, current_session, current_geometry, frame_seq=frame.header.seq)):
            raise ValueError('preview_changed_during_render')
    except (ValueError, TypeError, KeyError, cv2.error) as exc:
        return _http_response(409, b'measured preview unavailable\n', extra={
            'X-Frame-State': 'measured-unavailable', 'X-Measured-Reason': str(exc)[:64]})
    return _http_response(200, jpeg, extra={
        'Content-Type': 'image/jpeg', 'Cache-Control': 'no-store',
        'X-Frame-Rectified': 'measured-map', 'X-Frame-Calibration': ticket.record['calibration_revision'],
        'X-Frame-Session': session, 'X-Frame-Seq': str(frame.header.seq),
        'X-Frame-Captured-At': str(frame.captured_at),
        'X-Frame-Age-Ms': str(round(max(0., time.time()-frame.captured_at)*1000)),
        'X-Frame-Width': str(size[0]), 'X-Frame-Height': str(size[1]), 'X-Frame-Rotation-Deg': '0',
        'X-Frame-Plane': ','.join(str(v) for v in (*bounds, ppm)),
        'X-Frame-Observed-Fraction': f'{float(mask.mean()):.6f}',
    })


async def synchronize_preview(worker):
    """A failed config fetch never calls this and cannot extend the preview lease."""
    if not hasattr(worker.ingest, 'report_measured_config'):
        return
    source = worker.camera.source_id
    worker.ingest.report_measured_config(source, (worker.config or {}).get('measured_preview'), worker.camera.map_id)
    status = worker.ingest.measured_status(source)
    if not status['calibration_revision'] or not hasattr(worker.client, 'publish_preview_status'):
        return
    body = {k: v for k, v in status.items() if k != 'geometry'}
    from rosy_vision.track.fleet_client import TrackPublishError
    import httpx
    try:
        await worker.client.publish_preview_status(body)
    except (TrackPublishError, httpx.HTTPError) as exc:
        worker._config_log.failed((('preview_report_error', type(exc).__name__),))
