"""A surveyed fixed camera proposes moved station coordinates without a charge session."""
import asyncio
import importlib
import json
import math
from types import SimpleNamespace

import cv2
import httpx
import numpy as np
import pytest

from rosy_vision.detect import generate_marker_image
from rosy_vision.publish import SightingPublisher


def module():
    return importlib.import_module('rosy_vision.station_map_worker')


def anchors():
    return tuple(dict(marker_id=40+i, corners=((x, y), (x+49, y), (x+49, y+49), (x, y+49)))
                 for i, (x, y) in enumerate(((5, 5), (345, 5), (345, 345), (5, 345))))


def calibration(**changes):
    return module().StationMapCalibration(**(dict(station_id='charger-1', map_id='floor', map_revision='map-1',
        source_id='fixed-camera', source_epoch='camera-boot', revision='map-cal-1', pose_revision_hint=1,
        marker_id=33, marker_side_m=.1, marker_mount=dict(x=.02, y=0., yaw=math.pi/2),
        image_to_map=(.001, 0., 1., 0., -.001, 2., 0., 0., 1.), plane='station_marker',
        lens_rectified=True, approved=True, fixed_map_anchor=True,
        image_anchors=anchors(), max_anchor_error_px=.5,
        uncertainty_m=.002, uncertainty_rad=.005, approach_offset_m=.4) | changes))


def jpeg(*, visible=True, shift=0, defect=None):
    image = np.full((400, 400), 255, dtype=np.uint8)
    for i, anchor in enumerate(anchors()):
        x, y = anchor['corners'][0]
        if defect == 'missing' and i == 0:
            continue
        marker_id = anchor['marker_id']
        if defect == 'swapped' and i < 2:
            marker_id = 41-i
        if defect == 'moved' and i == 0:
            x += 8
        image[y:y+50, x:x+50] = generate_marker_image(marker_id, 50)
    if visible:
        image[150:250, 150+shift:250+shift] = generate_marker_image(33, 100)
    if defect == 'reflected':
        image = cv2.flip(image, 1)
    ok, data = cv2.imencode('.jpg', image)
    assert ok
    return data.tobytes()


def test_fixed_map_jpeg_producer_needs_no_robot_session_and_only_posts_candidates():
    async def exercise():
        sent = []
        def receive(request):
            assert request.method == 'POST' and request.url.path == '/api/fleet/station-poses'
            assert request.headers['Authorization'] == 'Bearer source-only'
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={'accepted': True, 'station': None})
        now = [100.1]
        frame = SimpleNamespace(header=SimpleNamespace(seq=1), captured_at=100., received_at=100.05, jpeg=jpeg())
        async with SightingPublisher('http://fleet', 'source-only', transport=httpx.MockTransport(receive)) as pub:
            worker = module().create_station_map_worker(calibration=calibration(),
                ingest=SimpleNamespace(latest_frame=lambda _: frame), rectify=lambda data: data,
                publisher=pub, clock=lambda: now[0], max_age_s=.25)
            await worker.process_latest()
            await worker.process_latest()
            assert len(sent) == 1
            value = sent[0]
            assert value['pose']['x'] == pytest.approx(1.1795, abs=.003)
            assert value['pose']['y'] == pytest.approx(1.8005, abs=.003)
            assert value['approach_pose']['x'] == pytest.approx(.7795, abs=.003)
            assert value['status'] == 'CANDIDATE' and value['approach_verified'] is False
            assert value['captured_at'] == 100. and value['valid_until'] <= 100.25
            assert not {'robot_id', 'session_id', 'boot_id'} & value.keys()
            now[0] = 100.2
            frame.header.seq, frame.captured_at, frame.received_at, frame.jpeg = 2, 100.15, 100.18, jpeg(shift=40)
            await worker.process_latest()
            assert sent[1]['pose']['x']-sent[0]['pose']['x'] == pytest.approx(.04, abs=.003)
            frame.header.seq, frame.jpeg = 3, jpeg(visible=False)
            await worker.process_latest()
            assert len(sent) == 2, 'marker loss must not become a fabricated zero pose'
    asyncio.run(exercise())


@pytest.mark.parametrize('changes', [dict(fixed_map_anchor=False), dict(approved=False),
    dict(plane='robot_marker'), dict(approach_offset_m=0.), dict(image_to_map=(0.,)*9),
    dict(map_revision=''), dict(lens_rectified=False), dict(marker_id=True)])
def test_unapproved_unanchored_or_unknown_plane_cannot_create_global_producer(changes):
    with pytest.raises(ValueError):
        calibration(**changes)


def test_frame_expiring_during_measurement_cannot_publish():
    async def exercise():
        calls, now = [], [100.1]
        def rectify(data):
            now[0] = 100.3
            return data
        async def publish(candidate):
            calls.append(candidate)
        worker = module().create_station_map_worker(calibration=calibration(),
            ingest=SimpleNamespace(latest_frame=lambda _: SimpleNamespace(header=SimpleNamespace(seq=1),
                captured_at=100., received_at=100.05, jpeg=jpeg())), rectify=rectify,
            publisher=SimpleNamespace(publish_station_pose=publish), clock=lambda: now[0], max_age_s=.25)
        await worker.process_latest()
        assert calls == []
    asyncio.run(exercise())


def test_camera_translation_cannot_be_published_as_station_relocation():
    async def exercise():
        sent = []
        def receive(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={'accepted': True})
        image = cv2.imdecode(np.frombuffer(jpeg(), np.uint8), cv2.IMREAD_GRAYSCALE)
        bumped = cv2.warpAffine(image, np.float32([[1, 0, 8], [0, 1, 6]]), (400, 400), borderValue=255)
        ok, encoded = cv2.imencode('.jpg', bumped)
        assert ok
        frame = SimpleNamespace(header=SimpleNamespace(seq=1), captured_at=100., received_at=100.05,
                                jpeg=encoded.tobytes())
        async with SightingPublisher('http://fleet', 'source-only', transport=httpx.MockTransport(receive)) as pub:
            worker = module().create_station_map_worker(calibration=calibration(),
                ingest=SimpleNamespace(latest_frame=lambda _: frame), rectify=lambda data: data,
                publisher=pub, clock=lambda: 100.1, max_age_s=.25)
            await worker.process_latest()
        assert sent == [], 'a moved camera must not manufacture a moved station'
    asyncio.run(exercise())


@pytest.mark.parametrize('defect', ['missing', 'swapped', 'moved', 'reflected', 'outside'])
def test_every_frame_needs_the_same_four_independent_surveyed_landmarks(defect):
    async def exercise():
        sent = []
        async def publish(candidate):
            sent.append(candidate)
            return {'accepted': True}
        processor = module().StationMapFrameProcessor(calibration=calibration(), rectify=lambda data: data,
            publisher=SimpleNamespace(publish_station_pose=publish), clock=lambda: 100.1,
            max_age_s=.25, monotonic=lambda: 10.)
        frame = SimpleNamespace(header=SimpleNamespace(seq=1), captured_at=100., received_at=100.05,
                                jpeg=jpeg(defect=defect, shift=125 if defect == 'outside' else 0))
        assert not await processor.process(frame, source_id='fixed-camera')
        assert not sent
    asyncio.run(exercise())


@pytest.mark.parametrize('defect', ['count', 'duplicate', 'station', 'crossed', 'collinear', 'quad', 'tolerance'])
def test_anchor_registration_rejects_ambiguous_or_degenerate_profiles(defect):
    values = list(anchors())
    changes = {}
    if defect == 'count':
        values.pop()
    elif defect == 'duplicate':
        values[1]['marker_id'] = values[0]['marker_id']
    elif defect == 'station':
        values[0]['marker_id'] = 33
    elif defect == 'crossed':
        values[1], values[2] = values[2], values[1]
    elif defect == 'collinear':
        values = [dict(marker_id=40+i, corners=((x, 5), (x+49, 5), (x+49, 54), (x, 54)))
                  for i, x in enumerate((5, 105, 205, 305))]
    elif defect == 'quad':
        values[0]['corners'] = ((5, 5),)*4
    else:
        changes['max_anchor_error_px'] = 50.
    with pytest.raises(ValueError):
        calibration(image_anchors=tuple(values), **changes)


@pytest.mark.parametrize('marker_id', [33, 40])
@pytest.mark.parametrize('quad', [((float('nan'), 5.),)*4, ((float('inf'), 5.),)*4,
    ((5., 5.),)*3, ((5., 5.),)*4, ((5., 5.), (54., 54.), (54., 5.), (5., 54.))])
def test_invalid_detector_numbers_and_shapes_fail_closed(marker_id, quad, monkeypatch):
    async def exercise():
        detected = {a['marker_id']: a['corners'] for a in anchors()}
        detected[33] = ((150., 150.), (249., 150.), (249., 249.), (150., 249.))
        detected[marker_id] = quad
        monkeypatch.setattr(module(), 'detect_markers', lambda _: detected)
        sent = []
        async def publish(candidate):
            sent.append(candidate)
            return {'accepted': True}
        processor = module().StationMapFrameProcessor(calibration=calibration(), rectify=lambda data: data,
            publisher=SimpleNamespace(publish_station_pose=publish), clock=lambda: 100.1,
            max_age_s=.25, monotonic=lambda: 10.)
        frame = SimpleNamespace(header=SimpleNamespace(seq=1), captured_at=100., received_at=100.05, jpeg=b'')
        assert not await processor.process(frame, source_id='fixed-camera')
        assert not sent
    asyncio.run(exercise())


@pytest.mark.parametrize('change', [dict(approved=False), dict(fixed_map_anchor=False),
                                 dict(image_to_map=(0.,)*9)])
def test_installation_revalidates_model_copies_that_bypass_profile_validators(change):
    invalid = calibration().model_copy(update=change)
    with pytest.raises(ValueError):
        module().create_station_map_worker(calibration=invalid, ingest=None, rectify=lambda data: data,
            publisher=None, clock=lambda: 100., max_age_s=.25)


@pytest.mark.parametrize('matrix,expected', [
    ((0., .001, -2., .001, 0., 1., 0., 0., 1.), (-1.8005, 1.1795, math.pi/2)),
    ((0., -.001, 2., -.001, 0., -1., 0., 0., 1.), (1.8005, -1.1795, -math.pi/2)),
])
def test_rotated_map_plane_and_marker_mount_preserve_station_heading_and_approach(matrix, expected):
    async def exercise():
        sent = []
        async def publish(candidate):
            sent.append(candidate)
            return {'accepted': True}
        processor = module().StationMapFrameProcessor(calibration=calibration(image_to_map=matrix),
            rectify=lambda data: data, publisher=SimpleNamespace(publish_station_pose=publish),
            clock=lambda: 100.1, max_age_s=.25, monotonic=lambda: 10.)
        frame = SimpleNamespace(header=SimpleNamespace(seq=1), captured_at=100., received_at=100.05, jpeg=jpeg())
        assert await processor.process(frame, source_id='fixed-camera')
        pose = sent[0].pose
        assert (pose.x, pose.y, pose.yaw) == pytest.approx(expected, abs=.003)
        approach = sent[0].approach_pose
        assert approach.x == pytest.approx(pose.x-.4*math.cos(pose.yaw))
        assert approach.y == pytest.approx(pose.y-.4*math.sin(pose.yaw))
    asyncio.run(exercise())


def test_clock_pair_sampling_cannot_add_time_spent_reading_the_second_clock():
    async def exercise():
        sent, calls, utc = [], [], [100.1]
        async def publish(candidate):
            sent.append(candidate)
            return {'accepted': True}
        def monotonic():
            calls.append(True)
            if len(calls) == 1:
                utc[0] = 100.2  # Time advances between the two initial clock samples.
                return 10.
            return 10.06  # The actual .05 s remaining lease has elapsed.
        processor = module().StationMapFrameProcessor(calibration=calibration(), rectify=lambda data: data,
            publisher=SimpleNamespace(publish_station_pose=publish), clock=lambda: utc[0],
            max_age_s=.25, monotonic=monotonic)
        candidate = processor._measure(jpeg(), 100., 100.25)
        processor._measure = lambda *_: candidate  # Isolate clock arithmetic from detector cost.
        frame = SimpleNamespace(header=SimpleNamespace(seq=1), captured_at=100., received_at=100.05, jpeg=b'')
        assert not await processor.process(frame, source_id='fixed-camera')
        assert len(calls) == 2 and not sent
    asyncio.run(exercise())
