"""Installed station camera profiles drive existing source-only workers."""
import asyncio
import importlib
import json
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pytest

from rosy_vision.cli import parse_args
from test_station_map_worker import calibration as map_calibration, jpeg as map_jpeg
from test_station_worker import calibration as relative_calibration, jpeg as relative_jpeg
from test_station_observation import template


def module():
    return importlib.import_module('rosy_vision.station_installation')


def row(kind):
    cal = map_calibration().model_dump(mode='json') if kind == 'map' else asdict(relative_calibration())
    if kind == 'relative':
        cal['marker_mount'] = relative_calibration().marker_mount.model_dump()
    size = 400 if kind == 'map' else 300
    return dict(kind=kind, calibration=cal, robot_id='robot-1' if kind == 'relative' else None,
        phone_token_env='ROSY_PHONE_'+kind.upper(), token_env='ROSY_SOURCE_'+kind.upper(),
        fleet_base_url='http://fleet', max_age_s=.5,
        lens=dict(source_id=cal['source_id'], source_epoch=cal['source_epoch'], revision=cal['revision'],
            approved=True, model='pinhole', width=size, height=size, rotation_deg=0,
            matrix=[300., 0., size/2, 0., 300., size/2, 0., 0., 1.], distortion=[0.]*5))


def load(tmp_path, rows=None, env=None):
    path = tmp_path/'station-cameras.json'
    path.write_text(json.dumps(dict(version=1, sources=rows or [row('map'), row('relative')])), encoding='utf-8')
    secrets = {f'ROSY_{role}_{kind}': f'{role.lower()}-{kind.lower()}-secret'
               for kind in ('MAP', 'RELATIVE') for role in ('PHONE', 'SOURCE')}
    return module().load_station_installation(path, environ=secrets if env is None else env)


def test_cli_exposes_explicit_station_profile_command():
    args = parse_args(['station-vision', '--config', 'station-cameras.json'])
    assert args.config.name == 'station-cameras.json'
    assert (args.host, args.port) == ('0.0.0.0', 8095)


def test_strict_profile_keeps_credentials_out_of_representations(tmp_path):
    installed = load(tmp_path)
    assert len(installed.sources) == 2
    assert 'phone-map-secret' not in repr(installed)
    assert 'source-relative-secret' not in repr(installed)


@pytest.mark.parametrize('defect', ['unapproved', 'lens_scope', 'lens_revision', 'lens_matrix', 'rotation',
    'missing_lens', 'extra_secret', 'duplicate_source', 'credential_collision', 'missing_secret', 'url_credentials'])
def test_bad_installation_is_rejected_before_any_server_or_http_client(tmp_path, defect):
    rows, env = [row('map'), row('relative')], None
    if defect == 'unapproved':
        rows[0]['lens']['approved'] = False
    elif defect == 'lens_scope':
        rows[0]['lens']['source_id'] = 'other-camera'
    elif defect == 'lens_revision':
        rows[0]['lens']['revision'] = 'old-cal'
    elif defect == 'lens_matrix':
        rows[0]['lens']['matrix'] = [0.]*9
    elif defect == 'rotation':
        rows[0]['lens']['rotation_deg'] = 45
    elif defect == 'missing_lens':
        del rows[0]['lens']
    elif defect == 'extra_secret':
        rows[0]['token'] = 'DO-NOT-LOG-THIS-TOKEN'
    elif defect == 'duplicate_source':
        rows[1] = dict(rows[0])
    elif defect == 'credential_collision':
        env = {key: 'same-secret' for key in ('ROSY_PHONE_MAP', 'ROSY_SOURCE_MAP',
            'ROSY_PHONE_RELATIVE', 'ROSY_SOURCE_RELATIVE')}
    elif defect == 'missing_secret':
        env = {}
    else:
        rows[0]['fleet_base_url'] = 'http://user:DO-NOT-LOG-THIS-TOKEN@fleet'
    with pytest.raises(ValueError) as error:
        load(tmp_path, rows, env)
    assert 'DO-NOT-LOG-THIS-TOKEN' not in str(error.value)


@pytest.mark.parametrize('kind', ['map', 'relative'])
def test_installed_lens_and_source_worker_publish_real_jpeg_over_authenticated_http(tmp_path, kind):
    async def exercise():
        installed = load(tmp_path, [row(kind)])
        source = installed.sources[0]
        sent = []
        def receive(request):
            assert request.headers['Authorization'] == f'Bearer source-{kind}-secret'
            if request.method == 'GET':
                return httpx.Response(200, json={'scope': template(sequence=0).model_dump()})
            sent.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json={'accepted': True})
        size = 400 if kind == 'map' else 300
        frame = SimpleNamespace(header=SimpleNamespace(seq=1, width=size, height=size, rotation_deg=0),
            captured_at=100., received_at=100.05, jpeg=map_jpeg() if kind == 'map' else relative_jpeg())
        from rosy_vision.publish import SightingPublisher
        async with SightingPublisher('http://fleet', source.token.get_secret_value(),
                transport=httpx.MockTransport(receive)) as pub:
            worker = source.create_worker(ingest=SimpleNamespace(latest_frame=lambda _: frame),
                publisher=pub, clock=lambda: 100.1)
            await worker.process_latest()
            await worker.process_latest()
            assert len(sent) == 1
            assert sent[0][0] == '/api/fleet/'+('station-poses' if kind == 'map' else 'station-observations')
            assert sent[0][1]['captured_at'] == 100.
            assert sent[0][1]['pose']['x'] == pytest.approx(1.1795 if kind == 'map' else -.1295, abs=.003)
            frame.header.seq, frame.captured_at, frame.header.rotation_deg = 2, 100.02, 90
            await worker.process_latest()
            assert len(sent) == 1, 'unapproved capture rotation cannot use the installed homography'
    asyncio.run(exercise())


@pytest.mark.parametrize('value', [1, 0, 'true', 'false'])
@pytest.mark.parametrize('target', ['lens_approved', 'relative_approved', 'lens_rectified'])
def test_profile_approval_requires_json_booleans(tmp_path, value, target):
    rows = [row('relative')]
    if target == 'lens_approved':
        rows[0]['lens']['approved'] = value
    else:
        rows[0]['calibration']['approved' if target == 'relative_approved' else 'lens_rectified'] = value
    with pytest.raises(ValueError):
        load(tmp_path, rows)


def test_duplicate_json_keys_cannot_replace_an_approval_or_source(tmp_path):
    path = tmp_path/'duplicate.json'
    path.write_text('{"version":1,"sources":[],"sources":[]}', encoding='utf-8')
    with pytest.raises(ValueError):
        module().load_station_installation(path, environ={})


def test_measured_nonzero_lens_correction_moves_detected_corners_to_the_calibrated_pixel_space(tmp_path):
    import cv2
    import numpy as np
    from rosy_vision.detect import detect_markers
    values = row('map')
    values['lens']['matrix'] = [300., 0., 80., 0., 300., 80., 0., 0., 1.]
    values['lens']['distortion'] = [.35, -.03, .002, -.001, 0.]
    source = load(tmp_path, [values]).sources[0]
    raw = map_jpeg()
    before = np.asarray(detect_markers(raw)[33], dtype=np.float64)
    k = np.asarray(values['lens']['matrix']).reshape(3, 3)
    expected = cv2.undistortPoints(before.reshape(-1, 1, 2), k,
        np.asarray(values['lens']['distortion']), P=k).reshape(4, 2)
    corrected = source.profile.lens.rectifier()(raw)
    observed = np.asarray(detect_markers(corrected)[33])
    assert np.linalg.norm(expected-before, axis=1).max() > 5.
    assert np.linalg.norm(observed-expected, axis=1).max() < 2.


def test_actual_websocket_owner_requests_measurement_then_closes_all_resources(tmp_path):
    async def exercise():
        import websockets
        from rosy_vision import protocol
        from rosy_vision.publish import SightingPublisher
        from rosy_vision.station_vision import StationVisionServer
        installed = load(tmp_path, [row('map')])
        posted = asyncio.Event()
        seen, clients = [], []
        def receive(request):
            assert request.headers['Authorization'] == 'Bearer source-map-secret'
            seen.append(json.loads(request.content))
            posted.set()
            return httpx.Response(200, json={'accepted': True})
        def publisher(url, token):
            value = SightingPublisher(url, token, transport=httpx.MockTransport(receive))
            clients.append(value)
            return value
        owner = StationVisionServer(installed, host='127.0.0.1', port=0, publisher_factory=publisher)
        async with owner:
            listener = owner.server
            port = listener.sockets[0].getsockname()[1]
            socket = await websockets.connect(f'ws://127.0.0.1:{port}{protocol.WS_PATH}',
                additional_headers={'Authorization': 'Bearer phone-map-secret'})
            try:
                await socket.send(json.dumps(dict(type='hello', proto=protocol.PROTO, source='fixed-camera',
                    app_version='SIM', device='SIM', sensor=dict(width=400, height=400, rotation_deg=0))))
                config = json.loads(await socket.recv())
                demand = json.loads(await socket.recv())
                assert config['type'] == 'config' and config['width'] == 400
                assert demand == dict(type='demand', wanted=True), 'no viewer lease is needed for installed measurement'
                await socket.send(protocol.pack_header(protocol.FrameHeader(1, 0, 400, 400, 0))+map_jpeg())
                await asyncio.wait_for(posted.wait(), 3.)
                assert len(seen) == 1 and seen[0]['status'] == 'CANDIDATE'
                tasks = tuple(owner._tasks)
                # Exit while the real phone connection is still open.
                await owner.__aexit__(None, None, None)
                messages = []
                async for message in socket:
                    messages.append(json.loads(message))
                assert dict(type='demand', wanted=False) in messages
                assert all(task.done() for task in tasks) and not listener.is_serving()
                assert all(client._client.is_closed for client in clients)
            finally:
                await socket.close()
    asyncio.run(exercise())


def test_fatal_worker_exit_is_supervised_and_releases_measurement_demand(tmp_path):
    async def exercise():
        from rosy_vision.station_vision import StationVisionServer
        class FatalServer(StationVisionServer):
            async def _consume(self, worker):
                raise RuntimeError('DO-NOT-LOG-THIS-TOKEN')
        owner = FatalServer(load(tmp_path, [row('map')]), host='127.0.0.1', port=0)
        with pytest.raises(RuntimeError, match='STATION_MEASUREMENT_WORKER_STOPPED') as error:
            async with owner:
                listener = owner.server
                await owner.wait()
        assert 'DO-NOT-LOG' not in str(error.value)
        assert owner.server is None and not listener.is_serving() and not owner._tasks
        assert not owner.ingest._measurement_sources
    asyncio.run(exercise())


def test_cancellation_closes_the_live_listener_and_source_client(tmp_path):
    async def exercise():
        from rosy_vision.station_vision import StationVisionServer
        owner = StationVisionServer(load(tmp_path, [row('map')]), host='127.0.0.1', port=0)
        started = asyncio.Event()
        async def run():
            async with owner:
                started.set()
                await owner.wait()
        task = asyncio.create_task(run())
        await asyncio.wait_for(started.wait(), 3.)
        listener = owner.server
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert owner.server is None and not listener.is_serving() and not owner._tasks
        assert not owner.ingest._measurement_sources
    asyncio.run(exercise())


def test_cli_invalid_profile_fails_without_exposing_input(tmp_path, capsys):
    from rosy_vision.cli import main
    path = tmp_path/'invalid.json'
    path.write_text('{"token":"DO-NOT-LOG-THIS-TOKEN"}', encoding='utf-8')
    assert main(['station-vision', '--config', str(path), '--port', '0']) == 2
    assert 'DO-NOT-LOG' not in capsys.readouterr().err


def test_demand_off_failure_still_closes_listener_workers_and_http_clients(tmp_path):
    async def exercise():
        from rosy_vision.station_vision import StationVisionServer
        from rosy_vision.publish import SightingPublisher
        clients = []
        def publisher(url, token):
            client = SightingPublisher(url, token, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
            clients.append(client)
            return client
        owner = StationVisionServer(load(tmp_path, [row('map')]), host='127.0.0.1', port=0,
                                    publisher_factory=publisher)
        with pytest.raises(RuntimeError, match='injected demand failure'):
            async with owner:
                listener, tasks = owner.server, tuple(owner._tasks)
                async def fail():
                    raise RuntimeError('injected demand failure')
                owner.ingest.stop_measurements = fail
        assert not listener.is_serving() and all(task.done() for task in tasks)
        assert all(client._client.is_closed for client in clients)
        assert owner.server is None and owner._stack is None
    asyncio.run(exercise())
