"""Actual Fleet persistence -> source client -> Vision render -> readback -> revoke.

The camera image and operator evidence claim are simulated, never FIELD evidence.
"""
import asyncio
import json
from pathlib import Path
import time

import httpx

from core_common.protocol.measured_calibration import bundle_digest
from fleet.server.site_map_store import SiteMapStore
from fleet.site_map import from_lane_graph
from site_map_fixture import LANE_GRAPH
from test_measured_calibration_api import approval
from test_overhead_tracking_api import _client, _auth, OPERATOR_TOKEN, VIEWER_TOKEN, SOURCE_TOKEN


def test_restart_source_sync_actual_render_readback_and_revocation(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/'overhead'))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3]/'operations/apps/games'))
    import cv2
    import numpy as np
    from core_common.protocol.vision_preview import VisionLeaseSigner
    from rosy_vision.ingest import IngestServer, _Source
    from rosy_vision.protocol import FrameHeader, pack_header
    from rosy_vision.project import CameraMap
    from rosy_vision.track.fleet_client import TrackClient
    from rosy_vision.track.worker import TrackWorker

    map_path, calibration_path = tmp_path/'map.db', tmp_path/'calibration.db'
    maps = SiteMapStore(map_path)
    maps.import_if_empty(from_lane_graph(LANE_GRAPH, map_id='map_v2_fleet'), source='simulated-integration')
    request = approval()
    request['bundle']['map_revision'] = maps.active_view()['sha256']
    request['bundle']['digest'] = bundle_digest(request['bundle'])
    options = {'site_maps': maps, 'vision_lease_secret': 'v'*32, 'vision_sources': ('ceiling_north',)}
    with _client(tmp_path, app_options=options, calibration_path=calibration_path) as client:
        response = client.post('/api/fleet/calibrations', json=request, headers=_auth(OPERATOR_TOKEN))
        assert response.status_code == 200, response.text
        row = response.json()
        assert row['persistent'] is True
    maps.close()

    maps = SiteMapStore(map_path)
    options['site_maps'] = maps
    with _client(tmp_path, app_options=options, calibration_path=calibration_path) as client:
        source = 'ceiling_north'
        ingest = IngestServer({source: 'camera-token'}, preview_signer=VisionLeaseSigner('v'*32),
                              preview_max_age_s=5.)
        src = _Source(source, None, lens=row['bundle']['capture']['lens'], link=1)
        ingest._sources[source] = src
        ok, encoded = cv2.imencode('.jpg', np.full((360, 640, 3), 120, np.uint8))
        assert ok
        raw = encoded.tobytes()
        camera = CameraMap(source, row['map_id'], 'cal-v3', 'processor-test', (30, 31, 32, 33),
                           ((0., 0.), (1., 0.), (1., 1.), (0., 1.)), {})
        legacy = client.get('/api/fleet/calibrations', headers=_auth(VIEWER_TOKEN)).json()
        async def run():
            async with TrackClient('http://testserver', SOURCE_TOKEN, transport=httpx.ASGITransport(app=client.app)) as track:
                worker = TrackWorker(camera=camera, ingest=ingest, client=track, auto_tune=False)
                ingest._handle_frame(src, pack_header(FrameHeader(1, 0, 640, 360, 0))+raw)
                await worker.refresh_config()
                assert worker.config['calibration'] is None
                assert worker.config['measured_preview']['record']['calibration_revision'] == row['calibration_revision']
                status = ingest.measured_status(source)
                assert status['state'] == 'confirmation_required'
                body = {'source_id': source, 'measured': {
                    'calibration_revision': row['calibration_revision'], 'session_id': status['session_id'],
                    'capture_signature': row['bundle']['capture']['signature'], 'confirm_conditions': True}}
                signed = client.post('/api/fleet/vision/lease', json=body, headers=_auth(OPERATOR_TOKEN))
                assert signed.status_code == 200, signed.text
                lease = signed.json()
                src.latest.captured_at = time.time()
                frame = await ingest._preview_response(lease['frame_path'], f"Bearer {lease['lease']}")
                assert frame.status_code == 200, frame.headers
                assert frame.headers['X-Frame-Calibration'] == row['calibration_revision']
                assert src.latest.jpeg == raw
                await worker.refresh_config()
                listed = client.get('/api/fleet/calibrations?purpose=preview', headers=_auth(VIEWER_TOKEN)).json()
                assert listed['calibrations'][0]['readback']['state'] == 'applied'
                assert client.get('/api/fleet/calibrations', headers=_auth(VIEWER_TOKEN)).json() == legacy
                revoked = client.delete(f'/api/fleet/calibrations/{source}', headers=_auth(OPERATOR_TOKEN),
                                        params={'purpose': 'preview', 'expected_revision': row['calibration_revision']})
                assert revoked.status_code == 200, revoked.text
                await worker.refresh_config()
                ingest._preview_last_sent.clear()
                src.latest.captured_at = time.time()  # stale (>5 s) wins over revoked: a loaded host got 404
                frame = await ingest._preview_response(lease['frame_path'], f"Bearer {lease['lease']}")
                assert frame.status_code == 409 and frame.body != raw
                worker.close()
        asyncio.run(run())
    maps.close()
