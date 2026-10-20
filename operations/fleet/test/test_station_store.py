"""A moved charger cannot revive an old target or bypass installation confirmation."""
import importlib
import importlib.util
from concurrent.futures import ThreadPoolExecutor

import pytest

from core_common.protocol.station_charging import StationPoseRecord


def registry(path):
    name = 'fleet.server.station_store'
    assert importlib.util.find_spec(name) is not None, 'station registry is not implemented'
    return importlib.import_module(name).StationStore(path)


def candidate(**changes):
    return StationPoseRecord.model_validate(dict(
        station_id='charger-1', map_id='floor', map_revision='map-1', pose_revision=99,
        pose={'x': 2.0, 'y': 1.0, 'yaw': 0.0}, approach_pose={'x': 1.5, 'y': 1.0, 'yaw': 0.0},
        approach_verified=True, source_id='camera-1', source_epoch='camera-boot',
        calibration_revision='cal-1', captured_at=100.0, valid_until=110.0,
        uncertainty_m=0.005, uncertainty_rad=0.01, status='CANDIDATE') | changes)


def test_candidate_cannot_choose_its_own_revision_or_be_used_before_confirmation(tmp_path):
    store = registry(tmp_path / 'site.sqlite')
    proposed = store.propose(candidate())
    assert proposed.pose_revision == 1
    assert store.get('charger-1').status == 'CANDIDATE'
    active = store.confirm('charger-1', expected_revision=1)
    assert active.status == 'VALID'
    assert active.pose_revision == 1
    with pytest.raises(ValueError, match='VERSION_CONFLICT'):
        store.confirm('charger-1', expected_revision=1)


def test_two_writers_cannot_confirm_the_same_installation(tmp_path):
    path = tmp_path / 'site.sqlite'
    left, right = registry(path), registry(path)
    left.propose(candidate())

    def confirm(store):
        try:
            return store.confirm('charger-1', expected_revision=1).status
        except ValueError:
            return 'CONFLICT'

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm, (left, right))) == ['CONFLICT', 'VALID']


def test_movement_invalidates_the_old_version_and_survives_restart(tmp_path):
    path = tmp_path / 'site.sqlite'
    store = registry(path)
    store.propose(candidate())
    store.confirm('charger-1', expected_revision=1)
    moved = store.propose(candidate(pose={'x': 4.0, 'y': 1.0, 'yaw': 1.57}))
    assert moved.pose_revision == 2
    assert store.get('charger-1').status == 'CANDIDATE'
    with pytest.raises(ValueError, match='VERSION_CONFLICT'):
        store.confirm('charger-1', expected_revision=1)
    fresh = registry(path)
    assert fresh.get('charger-1').pose.x == 4.0
    assert fresh.get('charger-1').pose_revision == 2
    assert fresh.history('charger-1')[0].status == 'INVALID'


def test_invalidated_installation_cannot_be_reconfirmed(tmp_path):
    store = registry(tmp_path / 'site.sqlite')
    store.propose(candidate())
    store.confirm('charger-1', expected_revision=1)
    store.invalidate('charger-1', expected_revision=1, reason='STATION_MOVED')
    assert store.get('charger-1').status == 'INVALID'
    with pytest.raises(ValueError, match='VERSION_CONFLICT'):
        store.confirm('charger-1', expected_revision=1)


def test_station_identity_does_not_follow_coordinates(tmp_path):
    store = registry(tmp_path / 'site.sqlite')
    one = store.propose(candidate())
    two = store.propose(candidate(station_id='charger-2'))
    assert one.station_id != two.station_id
    assert one.pose == two.pose
    assert len(store.list()) == 2


def test_rejects_already_confirmed_payload_without_replacing_current(tmp_path):
    store = registry(tmp_path / 'site.sqlite')
    store.propose(candidate())
    with pytest.raises(ValueError, match='CANDIDATE_REQUIRED'):
        store.propose(candidate(status='VALID'))
    assert store.get('charger-1').pose_revision == 1
