"""Installed local departure measurements retain source time; no HTTP injection."""
import importlib
import importlib.util

import pytest


def configured():
    name = 'core_features.docking.station_departure'
    assert importlib.util.find_spec(name) is not None, 'measured departure source is missing'
    module = importlib.import_module(name)
    now = [100.]
    profile = module.StationDepartureProfile(profile_id='SIM', revision='departure-1', station_id='charger-1',
        battery_id='pack-1', source_id='local-departure', source_epoch='source-boot',
        reverse_distance_m=.35, reverse_speed_m_s=.08, rear_margin_m=.05, max_overshoot_m=.02,
        max_lateral_m=.02, max_heading_rad=.05, max_age_s=.25, max_current_a=.05)
    feed = module.StationDepartureFeed(profile=profile, clock=lambda: now[0], source_clock=lambda: now[0])
    body = dict(robot_id='robot-1', station_id='charger-1', session_id='charge-1', attempt_id='attempt-1',
        boot_id='boot-1', battery_id='pack-1', map_id='floor', map_revision='map-1', pose_revision=1,
        profile_revision='departure-1', source_id='local-departure', source_epoch='source-boot',
        sequence=1, odom_epoch='odom-1', captured_at=100., valid_until=100.2,
        motion_sample_at=100., space_sample_at=100., power_sample_at=100., current_sample_at=100.,
        contact_sample_at=100., pose=dict(x=0., y=0., yaw=0.), measured_linear_m_s=0.,
        measured_angular_rad_s=0., rear_clearance_m=.5, sweep_verified=True,
        output_enabled=False, charging=False, current_a=0., load_present=True, faults=())
    return module, feed, body, now


def test_duplicate_reads_and_packets_do_not_extend_original_source_lifetime():
    module, feed, body, now = configured()
    assert feed.ingest(module.StationDepartureSample.model_validate(body))
    now[0] = 100.1
    assert feed.snapshot_nowait() is not None
    assert feed.ingest(module.StationDepartureSample.model_validate(body))
    now[0] = 100.2
    assert feed.snapshot_nowait() is None


@pytest.mark.parametrize('change', [dict(source_epoch='unregistered'), dict(profile_revision='other'),
    dict(valid_until=100.5, space_sample_at=99.), dict(captured_at=100.1, valid_until=100.3),
    dict(motion_sample_at=100.1), dict(rear_clearance_m=True)])
def test_unverified_or_expired_individual_source_is_never_live(change):
    module, feed, body, _ = configured()
    try:
        sample = module.StationDepartureSample.model_validate(body | change)
    except ValueError:
        return
    assert not feed.ingest(sample)
    assert feed.snapshot_nowait() is None


def test_same_sequence_cannot_carry_renewed_time_and_clock_reversal_closes_source():
    module, feed, body, now = configured()
    assert feed.ingest(module.StationDepartureSample.model_validate(body))
    now[0] += .1
    assert not feed.ingest(module.StationDepartureSample.model_validate(body | dict(valid_until=100.4)))
    assert feed.snapshot_nowait() is None
    assert feed.ingest(module.StationDepartureSample.model_validate(body | dict(
        sequence=2, captured_at=100.1, valid_until=100.3)))
    now[0] = 99.9
    assert feed.snapshot_nowait() is None


@pytest.mark.parametrize('clock_kind', ['source', 'monotonic'])
def test_clock_correction_cannot_resurrect_a_rejected_sample(clock_kind):
    module, feed, body, now = configured()
    mono = [100.]
    feed.clock = lambda: mono[0]
    sample = module.StationDepartureSample.model_validate(body)
    assert feed.ingest(sample)
    if clock_kind == 'source':
        now[0] = 101.
    else:
        mono[0] = 99.
    assert feed.snapshot_nowait() is None
    now[0] = mono[0] = 100.1
    assert feed.snapshot_nowait() is None
    assert not feed.ingest(sample)
    assert feed.snapshot_nowait() is None


def test_readback_lifetime_is_capped_to_actual_monotonic_remaining_lease():
    module, feed, body, now = configured()
    mono = [100.]
    feed.clock = lambda: mono[0]
    assert feed.ingest(module.StationDepartureSample.model_validate(body))
    now[0], mono[0] = 100.01, 100.19
    live = feed.snapshot_nowait()
    assert live.valid_until == pytest.approx(100.02)
