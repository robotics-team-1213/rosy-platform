"""D-655: relative odometry grows a survey draft without granting a map pose."""

import asyncio
import math

import pytest

from fleet.server.map_pose_service import MapPoseService
from fleet.server.site_map_store import SiteMapStore
from fleet.server.teach_service import TeachError, TeachService
from fleet.site_map import SiteMap


class Clock:
    now = 1_800_000_000.0

    def __call__(self):
        return self.now


def setup():
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
    service, poses, store, clock, draft = setup()

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
    service, _poses, _store, _clock, draft = setup()
    with pytest.raises(Exception) as error:
        asyncio.run(start(service, draft, **changes))
    assert error.value.code == code
    assert service.view()['recording'] is None


@pytest.mark.parametrize('loss,reason', [('gap', 'odom_lost'), ('reset', 'odom_reset'),
    ('draft', 'survey_changed')])
def test_recording_stops_before_a_gap_reset_or_draft_change(loss, reason):
    service, poses, store, clock, draft = setup()

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
    service, poses, store, clock, draft = setup()

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
