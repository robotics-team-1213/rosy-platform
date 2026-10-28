"""Measured preview requires current geometry, human session grant and config lease."""
import asyncio
import importlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from core_common.protocol.measured_calibration import bundle_digest
from core_common.protocol.vision_preview import VisionLeaseSigner
from rosy_vision.ingest import IngestServer, LatestFrame, _Source
from rosy_vision.protocol import FrameHeader, pack_header

SOURCE = 'ceiling_north'


def row():
    bundle = json.loads((Path(__file__).resolve().parents[3]
                         / 'test/fixtures/protocol/measured-calibration.v1.json').read_text())
    bundle['evidence_kind'] = 'measured'
    bundle['digest'] = bundle_digest(bundle)
    result = {'source_id': SOURCE, 'map_id': bundle['map_id'], 'purpose': 'preview', 'kind': 'measured',
              'use': 'preview-only', 'calibration_revision': 'measured-test', 'bundle': bundle,
              'approved_by': 'operator-1', 'approved_at': 1790000000., 'limits': {'p95_m': .01, 'max_m': .02},
              'persistent': True}
    result['record_digest'] = bundle_digest(result)
    return result


def config(record):
    return {'record': record, 'map_revision': 'site-map-5', 'reason': 'ok' if record else 'not_approved', 'lease_s': 5.}


def geometry(record):
    return {'image_size': [640, 360], 'rotation_deg': 0, 'lens': record['bundle']['capture']['lens']}


def claims(record, session='boot-1:1', confirm=True):
    return {'calibration_revision': record['calibration_revision'], 'session_id': session,
            'capture_signature': record['bundle']['capture']['signature'], 'confirm_conditions': confirm}


def runtime():
    return importlib.import_module('rosy_vision.measured_preview')


def test_ticket_needs_confirmation_and_expires_at_five_seconds():
    now = [10.]
    engine = runtime().MeasuredPreview(clock=lambda: now[0], boot_id='boot-1')
    record = row()
    engine.update(SOURCE, config(record), record['map_id'])
    with pytest.raises(ValueError, match='confirmation_required'):
        engine.select(SOURCE, 'boot-1:1', geometry(record), claims(record, confirm=False))
    ticket = engine.select(SOURCE, 'boot-1:1', geometry(record), claims(record))
    assert engine.complete(ticket, 'boot-1:1', geometry(record), frame_seq=1)
    assert engine.status(SOURCE, 'boot-1:1', geometry(record))['state'] == 'applied'
    now[0] = 15.
    assert not engine.complete(ticket, 'boot-1:1', geometry(record), frame_seq=1)
    assert engine.status(SOURCE, 'boot-1:1', geometry(record))['reason'] == 'config_stale'


def test_reconnect_boot_geometry_and_revocation_invalidate_old_grants():
    record = row()
    engine = runtime().MeasuredPreview(boot_id='first')
    engine.update(SOURCE, config(record), record['map_id'])
    session = engine.session_id(1)
    ticket = engine.select(SOURCE, session, geometry(record), claims(record, session))
    with pytest.raises(ValueError, match='confirmation_required'):
        engine.select(SOURCE, engine.session_id(2), geometry(record), claims(record, engine.session_id(2), False))
    assert runtime().MeasuredPreview(boot_id='second').session_id(1) != session
    for changed in ({**geometry(record), 'image_size': [320, 180]},
                     {**geometry(record), 'rotation_deg': 90},
                     {**geometry(record), 'lens': None}):
        with pytest.raises(ValueError, match='geometry_changed'):
            engine.select(SOURCE, session, changed, claims(record, session))
    engine.update(SOURCE, config(None), record['map_id'])
    assert not engine.complete(ticket, session, geometry(record), frame_seq=1)


def jpeg():
    ok, encoded = cv2.imencode('.jpg', np.full((360, 640, 3), 130, np.uint8))
    assert ok
    return encoded.tobytes()


def server():
    record = row()
    # Availability integration tolerates loaded runners; exact expiry has its own clock test.
    obj = IngestServer({SOURCE: 'phone-token'}, preview_signer=VisionLeaseSigner('p'*32), preview_max_age_s=5.)
    raw = jpeg()
    obj._sources[SOURCE] = SimpleNamespace(link=1, lens=record['bundle']['capture']['lens'],
        latest=LatestFrame(FrameHeader(2, 0, 640, 360, 0), raw, time.time(), time.time()))
    obj.report_measured_config(SOURCE, config(record), record['map_id'])
    return obj, record, raw


def test_direct_signed_preview_uses_actual_renderer_and_keeps_raw():
    obj, record, raw = server()
    token = obj.preview_signer.issue(principal_id='viewer', source_id=SOURCE)
    status = asyncio.run(obj._preview_response(f'/api/vision/sources/{SOURCE}/measured-status', f'Bearer {token}'))
    session = json.loads(status.body)['session_id']
    token = obj.preview_signer.issue(principal_id='operator', source_id=SOURCE, measured=claims(record, session))
    result = asyncio.run(obj._preview_response(f'/api/vision/sources/{SOURCE}/frame', f'Bearer {token}'))
    assert result.status_code == 200
    assert result.headers['X-Frame-Rectified'] == 'measured-map'
    assert result.headers['X-Frame-Calibration'] == record['calibration_revision']
    assert result.headers['X-Frame-Session'] == session
    assert cv2.imdecode(np.frombuffer(result.body, np.uint8), cv2.IMREAD_COLOR) is not None
    assert obj.latest_frame(SOURCE).jpeg == raw
    obj._sources[SOURCE].link = 2
    obj._preview_last_sent.clear()
    result = asyncio.run(obj._preview_response(f'/api/vision/sources/{SOURCE}/frame', f'Bearer {token}'))
    assert result.status_code == 409 and result.body != raw


@pytest.mark.parametrize('change', ['revoke', 'replace', 'expire'])
def test_config_change_during_render_does_not_return_old_result(monkeypatch, change):
    import threading
    obj, record, raw = server()
    now = [10.]
    obj.measured.clock = lambda: now[0]
    obj.report_measured_config(SOURCE, config(record), record['map_id'])
    module = runtime()
    original = module.render_plane
    started, release = threading.Event(), threading.Event()
    def blocked(*args):
        started.set()
        assert release.wait(3.)
        return original(*args)
    monkeypatch.setattr(module, 'render_plane', blocked)
    session = obj.measured_status(SOURCE)['session_id']
    token = obj.preview_signer.issue(principal_id='operator', source_id=SOURCE, measured=claims(record, session))
    async def run():
        task = asyncio.create_task(obj._preview_response(f'/api/vision/sources/{SOURCE}/frame', f'Bearer {token}'))
        assert await asyncio.to_thread(started.wait, 3.)
        if change == 'expire':
            now[0] += 5.
        else:
            replacement = {**record, 'calibration_revision': 'measured-new'} if change == 'replace' else None
            if replacement:
                replacement['record_digest'] = bundle_digest({k: v for k, v in replacement.items() if k != 'record_digest'})
            obj.report_measured_config(SOURCE, config(replacement), record['map_id'])
        release.set()
        return await task
    response = asyncio.run(run())
    assert response.status_code == 409 and response.body != raw


def test_renderer_refuses_decoded_geometry_mismatch():
    record = row()
    ok, encoded = cv2.imencode('.jpg', np.zeros((180, 320, 3), np.uint8))
    assert ok
    with pytest.raises(ValueError, match='geometry'):
        runtime().render_plane(encoded.tobytes(), record)


def test_old_confirmation_cannot_be_replayed_after_geometry_changed():
    record = row()
    engine = runtime().MeasuredPreview()
    engine.update(SOURCE, config(record), record['map_id'])
    grant = claims(record)
    engine.select(SOURCE, 'boot-1:1', geometry(record), grant)
    with pytest.raises(ValueError, match='geometry_changed'):
        engine.select(SOURCE, 'boot-1:1', {**geometry(record), 'rotation_deg': 90}, grant)
    with pytest.raises(ValueError, match='confirmation_required'):
        engine.select(SOURCE, 'boot-1:1', geometry(record), grant)


def test_additional_confirmation_grant_is_consumed_even_when_already_confirmed():
    record = row()
    engine = runtime().MeasuredPreview()
    engine.update(SOURCE, config(record), record['map_id'])
    first = {**claims(record), '_grant_id': 'first'}
    second = {**claims(record), '_grant_id': 'second'}
    engine.select(SOURCE, 'boot-1:1', geometry(record), first)
    engine.select(SOURCE, 'boot-1:1', geometry(record), second)
    engine.observe(SOURCE, 'boot-1:1', {**geometry(record), 'rotation_deg': 90})
    with pytest.raises(ValueError, match='confirmation_required'):
        engine.select(SOURCE, 'boot-1:1', geometry(record), second)


def test_receiver_invalidates_confirmation_on_unsampled_geometry_round_trip():
    obj, record, raw = server()
    src = _Source(SOURCE, None, lens=record['bundle']['capture']['lens'], link=1)
    obj._sources[SOURCE] = src
    obj._handle_frame(src, pack_header(FrameHeader(1, 0, 640, 360, 0))+raw)
    session = obj.measured_status(SOURCE)['session_id']
    grant = claims(record, session)
    ticket = obj.measured.select(SOURCE, session, geometry(record), grant)
    obj._handle_frame(src, pack_header(FrameHeader(2, 0, 640, 360, 90))+raw)
    obj._handle_frame(src, pack_header(FrameHeader(3, 0, 640, 360, 0))+raw)
    assert not obj.measured.complete(ticket, session, geometry(record), frame_seq=1)
    with pytest.raises(ValueError, match='confirmation_required'):
        obj.measured.select(SOURCE, session, geometry(record), grant)


def test_unseen_grant_issued_before_geometry_change_cannot_confirm_after_return():
    obj, record, raw = server()
    src = _Source(SOURCE, None, lens=record['bundle']['capture']['lens'], link=1)
    obj._sources[SOURCE] = src
    obj._handle_frame(src, pack_header(FrameHeader(1, 0, 640, 360, 0))+raw)
    session = obj.measured_status(SOURCE)['session_id']
    token = obj.preview_signer.issue(principal_id='operator', source_id=SOURCE, measured=claims(record, session))
    obj._handle_frame(src, pack_header(FrameHeader(2, 0, 640, 360, 90))+raw)
    obj._handle_frame(src, pack_header(FrameHeader(3, 0, 640, 360, 0))+raw)
    result = asyncio.run(obj._preview_response(f'/api/vision/sources/{SOURCE}/frame', f'Bearer {token}'))
    assert result.status_code == 409
    renewed = obj.measured_status(SOURCE)['session_id']
    assert renewed != session
    token = obj.preview_signer.issue(principal_id='operator', source_id=SOURCE, measured=claims(record, renewed))
    obj._preview_last_sent.clear()
    result = asyncio.run(obj._preview_response(f'/api/vision/sources/{SOURCE}/frame', f'Bearer {token}'))
    assert result.status_code == 200


def test_advancing_stream_can_finish_a_fresh_frame(monkeypatch):
    obj, record, raw = server()
    original = runtime().render_plane
    def advance(*args):
        obj._sources[SOURCE].latest = LatestFrame(FrameHeader(3, 0, 640, 360, 0), raw, time.time(), time.time())
        return original(*args)
    monkeypatch.setattr(runtime(), 'render_plane', advance)
    session = obj.measured_status(SOURCE)['session_id']
    token = obj.preview_signer.issue(principal_id='operator', source_id=SOURCE, measured=claims(record, session))
    result = asyncio.run(obj._preview_response(f'/api/vision/sources/{SOURCE}/frame', f'Bearer {token}'))
    assert result.status_code == 200
    assert result.headers['X-Frame-Seq'] == '2'
    assert obj.latest_frame(SOURCE).header.seq == 3
