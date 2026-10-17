"""Bounded station evidence reaches a legacy detector only for its current docking run."""
import importlib
import importlib.util
from types import SimpleNamespace

import pytest

from core_common.protocol.station_charging import StationObservation


def observation(**changes):
    return StationObservation.model_validate(dict(
        robot_id='robot-1', station_id='charger-1', session_id='charge-1', boot_id='robot-boot',
        odom_epoch='odom-1', map_id='floor', map_revision='map-1', pose_revision=1,
        source_id='station-camera', source_epoch='camera-boot', calibration_revision='mount-1',
        sequence=1, captured_at=100.1, valid_until=100.5, frame='base_link',
        pose={'x': 0.3, 'y': 0.01, 'yaw': 0.02},
        uncertainty_m=0.002, uncertainty_rad=0.005, visible=True) | changes)


def feed(**options):
    name = 'core_features.docking.station_feed'
    assert importlib.util.find_spec(name) is not None, 'station observation adapter is not implemented'
    monotonic, utc = [10.0], [100.0]
    value = importlib.import_module(name).StationObservationFeed(
        observation(), clock=lambda: monotonic[0], source_clock=lambda: utc[0],
        max_age_s=0.5, max_uncertainty_m=0.01, max_uncertainty_rad=0.02, **options)
    value.start(SimpleNamespace(id='charger-1'))
    monotonic[0], utc[0] = 10.2, 100.2
    return value, monotonic, utc


def test_converts_capture_age_to_local_clock_and_expires_without_new_frames():
    value, now, utc = feed()
    assert value.ingest(observation(), received_at=10.2)
    assert value.relative_pose().at == pytest.approx(10.1)
    assert value.relative_pose().x == 0.3
    now[0], utc[0] = 10.7, 100.7
    assert value.relative_pose() is None


@pytest.mark.parametrize('changes', [dict(session_id='old'), dict(boot_id='old'), dict(pose_revision=2),
                                    dict(map_revision='old'), dict(source_epoch='restarted'), dict(source_id='other'),
                                    dict(robot_id='robot-2'), dict(station_id='charger-2'),
                                    dict(odom_epoch='old'), dict(calibration_revision='old'),
                                    dict(captured_at=100.3), dict(uncertainty_m=0.1)])
def test_wrong_or_uncertain_evidence_clears_current_detection(changes):
    value, _, _ = feed()
    assert value.ingest(observation(), received_at=10.2)
    assert not value.ingest(observation(sequence=2, **changes), received_at=10.2)
    assert value.relative_pose() is None


def test_duplicate_sequence_not_visible_and_stop_do_not_replay_last_pose():
    value, _, _ = feed()
    assert value.ingest(observation(), received_at=10.2)
    assert not value.ingest(observation(), received_at=10.2)
    assert value.relative_pose() is None
    assert not value.ingest(observation(sequence=2, visible=False, pose=None), received_at=10.2)
    value.stop()
    assert not value.ingest(observation(sequence=3), received_at=10.2)
    assert value.relative_pose() is None


def test_seating_origin_adapts_to_parking_marker_without_changing_the_goal():
    import math
    from core_features.docking.parking import robot_in_dock_frame

    value, _, _ = feed(marker_offset_m=0.15)
    assert value.ingest(observation(pose={'x': 0.0, 'y': 0.0, 'yaw': 0.3}), received_at=10.2)
    marker = value.relative_pose()
    assert marker.x == pytest.approx(0.15 * math.cos(0.3))
    assert marker.y == pytest.approx(0.15 * math.sin(0.3))
    assert robot_in_dock_frame(marker.x, marker.y, marker.yaw, 0.15) == pytest.approx((0, 0, -0.3))


@pytest.mark.parametrize('offset', [-0.1, float('nan'), True])
def test_invalid_marker_offset_refuses_adapter(offset):
    with pytest.raises(ValueError, match='OFFSET'):
        feed(marker_offset_m=offset)


@pytest.mark.parametrize('source_now', [100.6, 100.0])
def test_source_clock_jump_cannot_extend_or_future_date_a_camera_sample(source_now):
    value, now, utc = feed()
    assert value.ingest(observation(), received_at=now[0])
    utc[0] = source_now  # Local monotonic time intentionally does not advance.
    assert value.relative_pose() is None
    assert value.relative_pose_nowait() is None
    utc[0] = 100.2
    assert value.relative_pose_nowait() is None  # A clock correction cannot resurrect old evidence.
