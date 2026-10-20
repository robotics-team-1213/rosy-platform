"""Station images flow through the real latest-frame worker and source-only publisher."""
import asyncio
import importlib
import importlib.util
import json
import secrets
from types import SimpleNamespace

import cv2
import httpx
import numpy as np
import pytest

from core_common.protocol.station_charging import Pose2D
from rosy_vision.detect import generate_marker_image
from rosy_vision.publish import SightingPublisher
from rosy_vision.station_observation import StationCameraCalibration
from rosy_vision.worker import VisionWorker
from test_station_observation import template
from test_vision_worker import _camera


def processor_module():
    name = 'rosy_vision.station_worker'
    assert importlib.util.find_spec(name) is not None, 'live station image processor is missing'
    return importlib.import_module(name)


def calibration():
    return StationCameraCalibration(station_id='charger-1', source_id='station-camera', source_epoch='camera-boot',
        revision='mount-1', marker_id=7, marker_side_m=0.1, marker_mount=Pose2D(x=0.02, y=0., yaw=np.pi/2),
        image_to_station=(0.001, 0., 0., 0., -0.001, 0., 0., 0., 1.), plane='robot_marker',
        lens_rectified=True, approved=True, uncertainty_m=0.002, uncertainty_rad=0.005)


def jpeg(visible=True):
    image = np.full((300, 300), 255, dtype=np.uint8)
    if visible:
        image[100:200, 100:200] = generate_marker_image(7, 100)
    ok, encoded = cv2.imencode('.jpg', image)
    assert ok
    return encoded.tobytes()


def test_real_image_worker_publishes_relative_pose_then_explicit_marker_loss_once_each():
    module = processor_module()

    async def run():
        received = []
        token = secrets.token_urlsafe(32)
        def handler(request):
            assert request.headers['Authorization'] == 'Bearer '+token
            assert request.url.path == '/api/fleet/station-observations'
            received.append(json.loads(request.content))
            return httpx.Response(200, json={'accepted': True})
        now = [100.1]
        frame = SimpleNamespace(header=SimpleNamespace(seq=1), captured_at=100., received_at=100.05, jpeg=jpeg())
        ingest = SimpleNamespace(latest_frame=lambda source: frame, report_markers=lambda *args: None)
        async with SightingPublisher('http://fleet', token, transport=httpx.MockTransport(handler)) as publisher:
            processor = module.StationFrameProcessor(calibration=calibration(), scope=lambda: template(),
                rectify=lambda data: data, publisher=publisher, clock=lambda: now[0], max_age_s=0.25)
            worker = VisionWorker(source_id='station-camera', camera=_camera(source_id='station-camera'),
                ingest=ingest, publisher=publisher, clock=lambda: now[0], station=processor)
            await worker.process_latest()
            await worker.process_latest()
            assert len(received) == 1 and received[0]['visible']
            assert received[0]['pose']['x'] == pytest.approx(-0.1295, abs=0.003)
            assert received[0]['captured_at'] == frame.captured_at
            assert received[0]['valid_until'] <= frame.captured_at+0.25
            now[0] = 100.2
            frame.header.seq, frame.captured_at, frame.received_at, frame.jpeg = 2, 100.15, 100.18, jpeg(False)
            await worker.process_latest()
            assert len(received) == 2 and not received[1]['visible'] and received[1]['pose'] is None
            assert received[1]['sequence'] == 2
    asyncio.run(run())


def test_missing_expired_or_wrong_source_scope_never_publishes_a_position():
    module = processor_module()

    async def run():
        calls = []
        publisher = SimpleNamespace(publish_station_observation=lambda body: calls.append(body))
        for scope in (None, template(valid_until=100.05), template(source_epoch='old')):
            processor = module.StationFrameProcessor(calibration=calibration(), scope=lambda: scope,
                rectify=lambda data: data, publisher=publisher, clock=lambda: 100.1, max_age_s=0.25)
            frame = SimpleNamespace(header=SimpleNamespace(seq=1), captured_at=100., received_at=100.05, jpeg=jpeg())
            assert not await processor.process(frame, source_id='station-camera')
        assert calls == []
    asyncio.run(run())


def test_station_processing_is_not_called_for_expired_frames():
    processor_module()
    calls = []
    async def process(frame):
        calls.append(frame)
    frame = SimpleNamespace(header=SimpleNamespace(seq=1), captured_at=100., received_at=100.05, jpeg=jpeg())
    worker = VisionWorker(source_id='station-camera', camera=_camera(source_id='station-camera'),
        ingest=SimpleNamespace(latest_frame=lambda source: frame), publisher=None,
        clock=lambda: 101., station=SimpleNamespace(process=process, source_id='station-camera'))
    asyncio.run(worker.process_latest())
    assert calls == []


def test_processor_for_one_camera_cannot_consume_another_cameras_images():
    module = processor_module()
    processor = module.StationFrameProcessor(calibration=calibration(), scope=lambda: template(),
        rectify=lambda data: data, publisher=None, clock=lambda: 100.1, max_age_s=0.25)
    with pytest.raises(ValueError, match='SOURCE'):
        VisionWorker(source_id='other-camera', camera=_camera(source_id='other-camera'),
                     ingest=None, publisher=None, station=processor)


def test_session_change_while_image_is_processed_discards_old_scope():
    module = processor_module()
    scopes, sent = iter((template(), template(session_id='next-session'))), []
    processor = module.StationFrameProcessor(calibration=calibration(), scope=lambda: next(scopes),
        rectify=lambda data: data, publisher=SimpleNamespace(publish_station_observation=lambda body: sent.append(body)),
        clock=lambda: 100.1, max_age_s=0.25)
    frame = SimpleNamespace(header=SimpleNamespace(seq=1), captured_at=100., received_at=100.05, jpeg=jpeg())
    assert not asyncio.run(processor.process(frame, source_id='station-camera'))
    assert sent == []


def test_station_only_factory_fetches_scope_and_publishes_without_global_camera_map():
    module = processor_module()
    assert hasattr(module, 'create_station_worker'), 'station-only runtime composition is missing'

    async def run():
        requests = []
        token = secrets.token_urlsafe(32)
        def handler(request):
            assert request.headers['Authorization'] == 'Bearer '+token
            requests.append((request.method, request.url.path))
            if request.method == 'GET':
                assert request.url.path == '/api/fleet/station-observation-scope/robot-1'
                return httpx.Response(200, json={'scope': template(sequence=0).model_dump()})
            assert request.url.path == '/api/fleet/station-observations'
            body = json.loads(request.content)
            assert body['visible'] and body['pose'] is not None
            return httpx.Response(200, json={'accepted': True})
        frame = SimpleNamespace(header=SimpleNamespace(seq=1), captured_at=100., received_at=100.05, jpeg=jpeg())
        ingest = SimpleNamespace(latest_frame=lambda source: frame)
        async with SightingPublisher('http://fleet', token, transport=httpx.MockTransport(handler)) as publisher:
            worker = module.create_station_worker(calibration=calibration(), robot_id='robot-1',
                ingest=ingest, rectify=lambda data: data, publisher=publisher,
                clock=lambda: 100.1, max_age_s=0.25)
            assert worker.camera is None
            assert await worker.process_latest() == ()
            assert await worker.process_latest() == ()
        assert [method for method, path in requests] == ['GET', 'GET', 'POST']
    asyncio.run(run())


def test_worker_without_either_measurement_profile_is_rejected():
    with pytest.raises(ValueError, match='PROFILE'):
        VisionWorker(source_id='station-camera', camera=None, ingest=None, publisher=None)
