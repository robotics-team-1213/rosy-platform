"""D-655: relative odometry grows a survey draft without granting a map pose."""

import asyncio
import math

import pytest

from fleet.server.map_pose_service import MapPoseService
from fleet.server.site_map_store import SiteMapError, SiteMapStore
from fleet.server.teach_service import TeachError, TeachService
from fleet.site_map import SiteMap


class Clock:
    now = 1_800_000_000.0

    def __call__(self):
        return self.now


def survey_start():
    clock = Clock()
    poses = MapPoseService(lambda: ['r1'], wall=clock)
    store = SiteMapStore(clock=clock)
    draft = store.save_draft(SiteMap.model_validate({'schema': 'rosy.site_map/1', 'map_id': 'survey-yard',
        'places': [], 'edges': [], 'survey': {'revision': 'reference-1', 'origin': [10, 20],
        'heading_rad': math.pi / 2, 'scale_source': 'odometry', 'description': 'Start at the marked origin'}}),
        expected_revision=None, principal_id='bob')
    service = TeachService(poses=poses, site_maps=store, roster=lambda: ['r1'], clock=clock)
    poses.observe_state('r1', {'odom_pose': {'x': 2, 'y': 3, 'yaw': 0.4, 'stamp': clock.now}})
    return service, poses, store, clock, draft


def start(service, draft, **changes):
    return service.start('r1', 'bob', mode='survey', **{'map_id': 'survey-yard',
        'reference_revision': 'reference-1', 'expected_revision': draft['revision'], **changes})


def confirm(service, result, revision):
    return service.confirm(result['teach_id'], start={'name': 'Origin'}, end={'name': 'End'},
        direction='two_way', drive_mode='lane', speed_cap_mps=0.2, width_m=None,
        expected_revision=revision, principal_id='bob')


async def advance(service, poses, clock, distance, seconds=0.5):
    clock.now += seconds
    poses.observe_state('r1', {'odom_pose': {'x': 2 + distance * math.cos(0.4),
        'y': 3 + distance * math.sin(0.4), 'yaw': 0.4, 'stamp': clock.now}})
    await service.sample()


def test_relative_recording_projects_to_the_declared_origin_and_saves_only_observed_draft():
    service, poses, store, clock, draft = survey_start()

    async def run():
        view = await start(service, draft)
        assert view['recording']['mode'] == 'survey'
        assert view['recording']['reference_revision'] == 'reference-1'
        await advance(service, poses, clock, 0.2)
        await advance(service, poses, clock, 0.4)
        return await service.stop('bob')

    result = asyncio.run(run())
    assert result['polyline'] == [[10, 20], [10, 20.4]]
    assert result['mode'] == 'survey' and result['map_id'] == 'survey-yard'
    assert poses.arbitrated_pose('r1').state == 'UNKNOWN'
    assert poses.odom_to_map('r1') is None and store.active_view() is None
    assert store.draft_view() == draft
    saved = confirm(service, result, draft['revision'])['draft']['map']
    assert saved['survey']['reviewed'] is False
    assert saved['edges'][0]['evidence'] == {'source': 'odometry', 'status': 'observed',
        'reference_revision': 'reference-1', 'note': ''}
    assert store.active_view() is None


@pytest.mark.parametrize('changes,code', [({'expected_revision': None}, 'SITE_MAP_DRAFT_CHANGED'),
    ({'map_id': 'other'}, 'TEACH_SURVEY_CHANGED'),
    ({'reference_revision': 'other'}, 'TEACH_SURVEY_CHANGED')])
def test_survey_start_requires_the_saved_basis(changes, code):
    service, _poses, _store, _clock, draft = survey_start()
    with pytest.raises((TeachError, SiteMapError)) as error:
        asyncio.run(start(service, draft, **changes))
    assert error.value.code == code
    assert service.view()['recording'] is None


@pytest.mark.parametrize('loss,reason', [('gap', 'odom_lost'), ('reset', 'odom_reset'),
    ('draft', 'survey_changed')])
def test_recording_stops_before_a_gap_reset_or_draft_change(loss, reason):
    service, poses, store, clock, draft = survey_start()

    async def run():
        await start(service, draft)
        await advance(service, poses, clock, 0.2)
        if loss == 'gap':
            clock.now += 3.1
        elif loss == 'reset':
            clock.now += 0.5
            poses.observe_state('r1', {'odom_pose': {'x': 0, 'y': 0, 'yaw': 0, 'stamp': clock.now}})
        else:
            body = store.draft_view()['map']
            body['survey']['origin'] = [30, 40]
            store.save_draft(SiteMap.model_validate(body), expected_revision=draft['revision'], principal_id='eve')
        await service.sample()
        await advance(service, poses, clock, 0.4)

    asyncio.run(run())
    view = service.view()
    assert view['recording'] is None
    assert view['pending'][0]['polyline'] == [[10, 20], [10, 20.2]]
    assert view['pending'][0]['reason'] == reason
    assert poses.arbitrated_pose('r1').state == 'UNKNOWN' and store.active_view() is None


def test_confirm_rejects_changed_reference_and_keeps_the_record_for_review():
    service, poses, store, clock, draft = survey_start()

    async def run():
        await start(service, draft)
        await advance(service, poses, clock, 0.2)
        return await service.stop('bob')

    result = asyncio.run(run())
    body = draft['map']
    body['survey']['origin'] = [30, 40]
    changed = store.save_draft(SiteMap.model_validate(body), expected_revision=draft['revision'], principal_id='eve')
    with pytest.raises(TeachError) as error:
        confirm(service, result, changed['revision'])
    assert error.value.code == 'TEACH_SURVEY_CHANGED'
    assert store.draft_view() == changed and service.view()['pending'] == [result]


def test_survey_start_refuses_stale_odometry_without_creating_a_record():
    service, _poses, store, clock, draft = survey_start()
    clock.now += 3.01
    with pytest.raises(TeachError) as error:
        asyncio.run(start(service, draft))
    assert error.value.code == 'TEACH_ODOM_UNAVAILABLE'
    assert service.view()['recording'] is None and store.draft_view() == draft


def test_survey_confirm_preserves_the_expected_revision_rule_and_invalidates_review():
    service, poses, store, clock, draft = survey_start()

    async def run():
        await start(service, draft)
        await advance(service, poses, clock, 0.2)
        return await service.stop('bob')

    result = asyncio.run(run())
    body = draft['map']
    body['survey'].update(reviewed=True, review_note='Checked origin')
    changed = store.save_draft(SiteMap.model_validate(body), expected_revision=draft['revision'], principal_id='eve')
    with pytest.raises(SiteMapError) as error:
        confirm(service, result, draft['revision'])
    assert error.value.code == 'SITE_MAP_DRAFT_CHANGED'
    saved = confirm(service, result, changed['revision'])['draft']['map']
    assert saved['survey']['reviewed'] is False and saved['survey']['review_note'] == ''


def test_survey_http_start_stop_confirm_are_named_operator_actions_without_motion(tmp_path):
    from fastapi.testclient import TestClient
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import RobotEndpoint
    from hashlib import sha256
    from test_teach import OPERATOR, VIEWER

    _service, poses, store, clock, draft = survey_start()
    robot = FakeRobot('r1')
    console = FleetConsole([RobotEndpoint('r1', 'http://127.0.0.1:8080', 't')], [robot])
    users = {sha256(b'operator-token').hexdigest(): {'principal_id': 'bob', 'role': 'operator'},
        sha256(b'viewer-token').hexdigest(): {'principal_id': 'vic', 'role': 'viewer'}}
    tasks = FleetTaskService(FleetTaskStore(tmp_path / 'tasks.sqlite'), robot_ids={'r1'})
    app = create_app(console, task_service=tasks, site_users=users, site_maps=store, map_pose_port=poses)
    request = {'robot_id': 'r1', 'mode': 'survey', 'map_id': 'survey-yard',
        'reference_revision': 'reference-1', 'expected_revision': draft['revision']}
    with TestClient(app) as client:
        assert client.post('/api/fleet/teach/start', json=request, headers=VIEWER).status_code == 403
        assert client.post('/api/fleet/teach/start', json=request).status_code == 401
        assert client.post('/api/fleet/teach/start', json={**request, 'mode': 'other'}, headers=OPERATOR).status_code == 422
        started = client.post('/api/fleet/teach/start', json=request, headers=OPERATOR)
        assert started.status_code == 200
        recording = started.json()['recording']
        assert recording['mode'] == 'survey' and recording['points'] == [[10, 20]]
        assert not {'reference', 'odom_anchor', 'odom_epoch'} & recording.keys()
        client.portal.call(advance, app.state.teach, poses, clock, 0.2)
        stopped = client.post('/api/fleet/teach/stop', headers=OPERATOR)
        assert stopped.status_code == 200
        saved = client.post('/api/fleet/teach/confirm', headers=OPERATOR, json={
            'teach_id': stopped.json()['teach_id'], 'from': {'name': 'Origin'}, 'to': {'name': 'End'},
            'speed_cap_mps': 0.2, 'expected_revision': draft['revision']})
        assert saved.status_code == 200 and saved.json()['draft']['map']['edges'][0]['evidence']['source'] == 'odometry'
    assert store.active_view() is None and poses.arbitrated_pose('r1').state == 'UNKNOWN'
    assert {call[0] for call in robot.calls} <= {'state', 'power_health', 'motor_health', 'map', 'swarm_state', 'navigation_path', 'events'}
    assert {('POST', f'/api/fleet/teach/{action}', 200) for action in ('start', 'stop', 'confirm')} <= {
        (row['method'], row['path'], row['status_code']) for row in tasks.store.api_audit()}


@pytest.mark.parametrize("stamp_delta", [-0.1, 0.0])
def test_rejected_odom_breaks_survey_without_resuming_across_it(stamp_delta):
    service, poses, store, clock, draft = survey_start()

    async def run():
        await start(service, draft)
        await advance(service, poses, clock, 0.2)
        poses.observe_state('r1', {'odom_pose': {'x': 9, 'y': 9, 'yaw': 0.4,
            'stamp': clock.now + stamp_delta}})
        await service.sample()
        await advance(service, poses, clock, 0.4)

    asyncio.run(run())
    assert service.view()['recording'] is None
    assert service.view()['pending'][0]['reason'] == 'odom_reset'
    assert service.view()['pending'][0]['polyline'] == [[10, 20], [10, 20.2]]
    assert store.draft_view() == draft


@pytest.mark.parametrize('action', ['start', 'place', 'confirm'])
def test_normal_teach_cannot_write_operational_coordinates_into_survey_draft(action):
    from test_teach import _service, _drive
    service, poses, store, _clock = _service()
    result = None
    if action == 'confirm':
        async def run():
            await service.start('rosy_60', 'bob')
            await _drive(service, poses, [(0.2, 0)])
            return await service.stop('bob')
        result = asyncio.run(run())
    survey = survey_start()[4]['map']
    draft = store.save_draft(SiteMap.model_validate(survey), expected_revision=None, principal_id='bob')
    with pytest.raises(TeachError) as error:
        if action == 'start':
            asyncio.run(service.start('rosy_60', 'bob'))
        elif action == 'place':
            asyncio.run(service.place('rosy_60', name='Wrong frame', kind='park',
                expected_revision=draft['revision'], principal_id='bob'))
        else:
            confirm(service, result, draft['revision'])
    assert error.value.code == 'TEACH_MAP_CHANGED'
    assert store.draft_view() == draft


@pytest.mark.parametrize('action', ['confirm', 'place', 'marker_add', 'marker_move'])
def test_operational_teach_preserves_active_survey_and_invalidates_draft_review(action):
    from copy import deepcopy
    from test_teach import MAP, Poses, _drive
    body = deepcopy(MAP)
    body['survey'] = {**survey_start()[4]['map']['survey'], 'reviewed': True, 'review_note': 'Measured'}
    body['edges'][0]['evidence'] = {'source': 'operator', 'status': 'reviewed',
        'reference_revision': 'reference-1', 'note': 'Measured'}
    store = SiteMapStore()
    store.import_if_empty(SiteMap.model_validate(body), source='test')
    active = store.active_view()
    poses = Poses()
    poses.at(0.3, 0)
    service = TeachService(poses=poses, site_maps=store, roster=lambda: ['r1'],
        place_markers=lambda _: {'map_id': 'site', 'source_id': 'floor', 'x': 0.1, 'y': 0, 'yaw': 0})
    if action == 'confirm':
        async def run():
            await service.start('r1', 'bob')
            await _drive(service, poses, [(0.5, 0)])
            return await service.stop('bob')
        result = asyncio.run(run())
        assert result['map_id'] == 'site'
        assert result['survey_reference']['origin'] == body['survey']['origin']
        saved = confirm(service, result, None)['draft']['map']
        assert saved['edges'][-1]['evidence']['source'] == 'odometry'
        assert saved['edges'][-1]['evidence']['status'] == 'observed'
        assert service.view()['pending'] == []
    elif action == 'place':
        saved = asyncio.run(service.place('r1', name='Spot', kind='park', expected_revision=None,
            principal_id='bob'))['draft']['map']
    else:
        saved = service.place_from_marker(34, name='Spot', kind='park',
            place_id='A' if action == 'marker_move' else None, expected_revision=None,
            principal_id='bob')['draft']['map']
        if action == 'marker_move':
            assert saved['edges'][0]['evidence']['status'] == 'observed'
            assert saved['edges'][0]['polyline'][0] == [0.1, 0]
    assert saved['survey']['reviewed'] is False
    assert saved['survey']['review_note'] == ''
    assert store.active_view() == active


@pytest.mark.parametrize('phase', ['sample', 'confirm'])
def test_new_active_version_cannot_extend_or_confirm_old_recording(phase):
    from test_teach import _service, _drive, MAP
    service, poses, store, _clock = _service()
    async def run():
        await service.start('rosy_60', 'bob')
        await _drive(service, poses, [(0.2, 0)])
        result = await service.stop('bob') if phase == 'confirm' else None
        draft = store.save_draft(SiteMap.model_validate(MAP), expected_revision=None, principal_id='bob')
        store.activate(expected_revision=draft['revision'], principal_id='bob', route_active=False)
        if phase == 'sample':
            await _drive(service, poses, [(0.4, 0)])
            assert service.view()['recording'] is None
            assert service.view()['pending'][0]['reason'] == 'map_changed'
        else:
            with pytest.raises(TeachError) as error:
                confirm(service, result, draft['revision'])
            assert error.value.code == 'TEACH_MAP_CHANGED'
            assert service.view()['pending']
    asyncio.run(run())


def test_marker_move_invalidates_camera_road_review_without_a_survey():
    from copy import deepcopy
    from test_teach import MAP, Poses
    body = deepcopy(MAP)
    body['edges'][0]['evidence'] = {'source': 'camera', 'status': 'reviewed',
        'reference_revision': 'cal_123', 'note': 'frame sha256 abc; checked'}
    store = SiteMapStore()
    store.import_if_empty(SiteMap.model_validate(body), source='test')
    active = store.active_view()
    service = TeachService(poses=Poses(), site_maps=store, roster=lambda: ['r1'],
        place_markers=lambda _: {'map_id': 'site', 'source_id': 'floor', 'x': .1, 'y': 0, 'yaw': 0})
    saved = service.place_from_marker(34, name=None, kind=None, place_id='A', expected_revision=None,
        principal_id='bob')['draft']
    assert saved['map']['edges'][0]['evidence']['status'] == 'observed'
    assert saved['map']['edges'][0]['evidence']['source'] == 'operator'
    assert 'frame sha256 abc' in saved['map']['edges'][0]['evidence']['note']
    with pytest.raises(SiteMapError) as error:
        store.activate(expected_revision=saved['revision'], principal_id='bob', route_active=False)
    assert error.value.code == 'SITE_MAP_ROAD_UNREVIEWED'
    assert store.active_view() == active
