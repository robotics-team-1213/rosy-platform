"""Original ROS odom source time, not receipt repetition, establishes measured motion freshness."""
import importlib
import importlib.util

import pytest


def feed():
    name = 'core_features.docking.station_motion'
    assert importlib.util.find_spec(name) is not None, 'original station motion evidence adapter is missing'
    now, utc = [10.1], [1000.1]
    value = importlib.import_module(name).StationMotionFeed(
        clock=lambda: now[0], source_clock=lambda: utc[0], max_age_s=0.25)
    return value, now, utc


def sample(**changes):
    return dict(stamp_ns=100_000_000_000, source_now_ns=100_100_000_000,
                frame_id='odom', child_frame_id='base_link', odom_epoch='0',
                measured_linear_m_s=0.03, measured_angular_rad_s=0.01) | changes


def test_original_source_age_is_preserved_and_expires():
    value, now, utc = feed()
    assert value.observe(**sample())
    assert value.snapshot()['captured_at'] == pytest.approx(1000.)
    assert value.snapshot()['measured_linear_m_s'] == 0.03
    now[0], utc[0] = 10.3, 1000.3
    assert value.snapshot() is None


def test_repeated_header_never_renews_a_zero_velocity_sample():
    value, now, utc = feed()
    assert value.observe(**sample(measured_linear_m_s=0.))
    now[0], utc[0] = 10.2, 1000.2
    assert not value.observe(**sample(source_now_ns=100_200_000_000, measured_linear_m_s=0.))
    assert value.snapshot() is None
    assert value.observe(**sample(stamp_ns=100_150_000_000, source_now_ns=100_200_000_000))


@pytest.mark.parametrize('changes', [dict(stamp_ns=99_000_000_000), dict(stamp_ns=100_200_000_000),
                                    dict(stamp_ns=True), dict(source_now_ns=None), dict(frame_id='map'),
                                    dict(child_frame_id='camera'), dict(measured_linear_m_s=float('nan')),
                                    dict(measured_angular_rad_s=True)])
def test_stale_future_wrong_frame_and_invalid_source_clears_proof(changes):
    value, _, _ = feed()
    assert value.observe(**sample())
    assert not value.observe(**sample(**changes))
    assert value.snapshot() is None


def test_new_odometry_epoch_does_not_reuse_old_epoch_sequence_fence():
    value, _, _ = feed()
    assert value.observe(**sample())
    assert value.observe(**sample(odom_epoch='1'))
    assert value.snapshot()['odom_epoch'] == '1'


def test_output_snapshot_never_waits_for_source_writer():
    import threading
    value, _, _ = feed()
    value.observe(**sample())
    done, result = threading.Event(), []

    def read():
        result.append(value.snapshot())
        done.set()

    value._lock.acquire()
    thread = threading.Thread(target=read)
    thread.start()
    try:
        completed = done.wait(0.1)
    finally:
        value._lock.release()
        thread.join(1.)
    assert completed and result == [None]


def test_original_read_lower_bound_includes_delay_before_feed_admission():
    value, now, utc = feed()
    now[0], utc[0] = 10.2, 1000.2
    assert value.observe(**sample(), received_at=10.1, source_received_at=1000.1)
    assert value.snapshot()['captured_at'] == pytest.approx(1000.)


@pytest.mark.parametrize('received,source_received', [(9.9, 999.9), (10.3, 1000.3),
    (True, 1000.1), (10.1, float('nan')), (10.1, None), (None, 1000.1)])
def test_invalid_or_expired_original_read_clears_motion(received, source_received):
    value, _, _ = feed()
    assert value.observe(**sample())
    assert not value.observe(**sample(stamp_ns=100_010_000_000),
        received_at=received, source_received_at=source_received)
    assert value.snapshot() is None


@pytest.mark.parametrize('expired', [(10.3, 1000.1), (10.1, 1000.3), (10.3, 1000.3)])
def test_observed_expiration_cannot_revive_after_clocks_return(expired):
    value, now, utc = feed()
    assert value.observe(**sample())
    now[0], utc[0] = expired
    assert value.snapshot() is None
    now[0], utc[0] = 10.1, 1000.1
    assert value.snapshot() is None


@pytest.mark.parametrize('advance', ['final_mono', 'utc_read'])
def test_snapshot_checks_read_end_before_returning_any_proof(advance):
    value, now, utc = feed()
    assert value.observe(**sample())
    calls = []
    def mono():
        if calls and advance == 'final_mono': now[0] = 10.4
        calls.append(True)
        return now[0]
    def source():
        if advance == 'utc_read': now[0] = 10.4
        return utc[0]
    value.clock, value.source_clock = mono, source
    assert value.snapshot() is None
    value.clock, value.source_clock = lambda: 10.1, lambda: 1000.1
    assert value.snapshot() is None


def test_observation_cannot_publish_proof_if_clock_read_itself_expires_it():
    value, now, utc = feed()
    assert value.observe(**sample())
    def slow_source():
        now[0] = 10.4
        return utc[0]
    value.source_clock = slow_source
    assert not value.observe(**sample(stamp_ns=100_010_000_000))
    now[0] = 10.1
    value.source_clock = lambda: utc[0]
    assert value.snapshot() is None
