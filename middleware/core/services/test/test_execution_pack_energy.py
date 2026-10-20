"""Original synthetic energy facts; no BMS/device/calibration acceptance."""
from uuid import uuid4

import pytest


def rig(**overrides):
    from core_features.power.execution_energy import EnergyProfile, PackEnergySource
    values = dict(robot_id='unit', boot_id=uuid4(), battery_id='pack', kind='bench',
                  epoch='boot-1', capacity_revision='calibrated-1', revision='SYNTHETIC',
                  whole_load_w=10., reserve_j=20., max_age_s=2., min_soh=70.,
                  min_temperature_c=0., max_temperature_c=45.)
    values.update(overrides)
    profile = EnergyProfile(**values)
    clock, provider = [10.], object()
    source = PackEnergySource(profile=profile, provider=provider, clock=lambda: clock[0])
    return source, provider, clock, profile


def reading(**overrides):
    from core_features.power.execution_energy import EnergyReading
    values = dict(sequence=1, stamp_ns=1000000000, battery_id='pack', epoch='boot-1',
                  capacity_revision='calibrated-1', usable_wh_lower=1., soc_percent=80.,
                  soh_percent=90., temperature_c=25., fault=False)
    values.update(overrides)
    return EnergyReading(**values)


def receive(source, provider, value=None, *, source_now_ns=1000000000):
    token = source.begin(provider)
    assert token is not None
    return source.complete(token, provider, reading() if value is None else value,
                           source_now_ns=source_now_ns)


def test_original_age_and_complete_read_delay_are_not_receipt_freshness():
    source, provider, clock, _ = rig()
    ticket = source.begin(provider)
    clock[0] = 10.5
    value = source.complete(ticket, provider, reading(), source_now_ns=2000000000)
    assert value is not None
    assert value.capture_mono <= 9. and value.valid_until_mono <= 11.
    assert value.valid_until_mono > clock[0]
    source, provider, clock, _ = rig()
    ticket = source.begin(provider)
    clock[0] = 11.01
    assert source.complete(ticket, provider, reading(), source_now_ns=2000000000) is None


def test_duplicate_never_refreshes_and_expired_original_cannot_revive():
    source, provider, clock, _ = rig()
    first = receive(source, provider)
    clock[0] = 10.5
    same = receive(source, provider, source_now_ns=1500000000)
    assert same.capture_mono <= first.capture_mono
    assert same.valid_until_mono <= first.valid_until_mono
    clock[0] = 12.
    assert receive(source, provider, source_now_ns=3000000000) is None
    # A caller cannot re-date a failed original by lying about its source-now.
    clock[0] = 12.1
    assert receive(source, provider) is None


@pytest.mark.parametrize('change', [dict(usable_wh_lower=2.), dict(soc_percent=81.),
                                   dict(soh_percent=91.), dict(temperature_c=24.)])
def test_same_sequence_with_changed_facts_invalidates_original(change):
    source, provider, clock, _ = rig()
    assert receive(source, provider) is not None
    clock[0] = 10.1
    assert receive(source, provider, reading(**change), source_now_ns=1100000000) is None
    assert receive(source, provider) is None


@pytest.mark.parametrize('change', [dict(battery_id='other'), dict(epoch='other'),
    dict(capacity_revision='other'), dict(fault=True), dict(soh_percent=69.),
    dict(temperature_c=-1.), dict(temperature_c=46.), dict(usable_wh_lower=None),
    dict(usable_wh_lower=float('nan')), dict(soc_percent=True), dict(sequence=True),
    dict(stamp_ns=0), dict(stamp_ns=2000000000)])
def test_unknown_unsafe_and_mismatched_measurements_have_no_positive_receipt(change):
    source, provider, _, _ = rig()
    assert receive(source, provider, reading(**change)) is None


def test_provider_identity_and_exact_one_use_ticket():
    source, provider, _, _ = rig()
    ticket = source.begin(provider)
    assert source.complete(ticket, object(), reading(), source_now_ns=1000000000) is None
    assert source.complete(ticket, provider, reading(), source_now_ns=1000000000) is None
    ticket = source.begin(provider)
    value = reading(sequence=2, stamp_ns=1100000000)
    assert source.complete(ticket, provider, value, source_now_ns=1100000000) is not None
    assert source.complete(ticket, provider, value, source_now_ns=1100000000) is None


def test_clock_reversal_permanently_closes_source():
    source, provider, clock, _ = rig()
    assert receive(source, provider) is not None
    clock[0] = 9.
    assert source.begin(provider) is None
    clock[0] = 11.
    assert source.begin(provider) is None


def test_genuinely_new_higher_measurement_after_synthetic_charging_is_new_fact():
    source, provider, clock, _ = rig()
    first = receive(source, provider, reading(usable_wh_lower=.2))
    clock[0] = 10.2
    second = receive(source, provider, reading(sequence=2, stamp_ns=1200000000,
                     usable_wh_lower=.8), source_now_ns=1200000000)
    assert second.available_j > first.available_j
    assert second.capture_mono > first.capture_mono
    assert first.reading.usable_wh_lower == .2


def test_full_fixed_end_consumes_idle_across_parents_and_strict_reserve():
    from core_features.power.execution_energy import covers
    source, provider, _, profile = rig(max_age_s=100.)
    sample = receive(source, provider, reading(usable_wh_lower=.05))  # 180 J lower bound
    # Whole parent (10 W * 10 s) + reserve fits; elapsed-only energy is irrelevant.
    assert covers(sample, profile, end_mono=20., now=10.)
    # Reusing the same measurement for a later parent includes all waiting time.
    assert not covers(sample, profile, end_mono=27., now=17.)
    assert sample.capture_mono <= 10.
    # Equality at whole-window cost plus reserve is not sufficient.
    source, provider, _, profile = rig(whole_load_w=100., reserve_j=2600.)
    sample = receive(source, provider, reading(usable_wh_lower=1.))
    assert not covers(sample, profile, end_mono=20., now=10.)


def test_capture_after_parent_start_counts_only_energy_since_measurement():
    from core_features.power.execution_energy import covers
    source, provider, clock, profile = rig()
    clock[0] = 11.
    sample = receive(source, provider, reading(usable_wh_lower=.05))
    assert covers(sample, profile, end_mono=20., now=11.)
    assert not covers(sample, profile, end_mono=20., now=13.)
    assert not covers(sample, profile, end_mono=float('inf'), now=11.)


@pytest.mark.parametrize('change', [dict(kind='voltage_only'), dict(kind='unknown'),
    dict(whole_load_w=0.), dict(reserve_j=0.), dict(reserve_j=float('inf')),
    dict(max_age_s=-1.), dict(min_soh=101.), dict(min_temperature_c=46.),
    dict(capacity_revision=''), dict(boot_id='not-uuid')])
def test_profile_requires_measured_scope_health_load_and_owned_reserve(change):
    with pytest.raises(ValueError):
        rig(**change)


@pytest.mark.parametrize('change', [dict(sequence=1, stamp_ns=1100000000),
                                   dict(sequence=2, stamp_ns=1000000000),
                                   dict(sequence=0, stamp_ns=900000000)])
def test_sequence_and_header_must_advance_together(change):
    source, provider, clock, _ = rig()
    assert receive(source, provider) is not None
    clock[0] = 10.1
    assert receive(source, provider, reading(**change), source_now_ns=1100000000) is None


def test_newer_genuine_reading_can_recover_facts_after_fault_without_resurrecting_original():
    source, provider, clock, _ = rig()
    assert receive(source, provider, reading(fault=True)) is None
    clock[0] = 10.1
    # An invalid original may never be made healthy by editing that original.
    assert receive(source, provider) is None
    sample = receive(source, provider, reading(sequence=2, stamp_ns=1100000000),
                     source_now_ns=1100000000)
    assert sample is not None  # CORE must still latch the affected parent STOP separately.


def test_unrelated_ticket_cannot_consume_current_pending_read():
    source, provider, _, _ = rig()
    ticket = source.begin(provider)
    assert source.complete(object(), provider, reading(), source_now_ns=1000000000) is None
    assert source.complete(ticket, provider, reading(), source_now_ns=1000000000) is not None


def test_complete_validation_delay_cannot_be_excluded_by_passing_a_fresh_receipt_time():
    source, provider, clock, _ = rig()
    ticket = source.begin(provider)
    clock[0] = 12.1
    assert source.complete(ticket, provider, reading(), source_now_ns=1000000000) is None


def test_values_are_immutable_and_remaining_wh_is_not_soc_times_nameplate():
    from dataclasses import FrozenInstanceError
    source, provider, _, _ = rig()
    sample = receive(source, provider, reading(usable_wh_lower=.01, soc_percent=100.))
    assert sample.available_j <= 36  # High displayed SOC cannot inflate measured usable Wh.
    with pytest.raises(FrozenInstanceError):
        sample.capture_mono = 11.
    with pytest.raises(FrozenInstanceError):
        sample.reading.usable_wh_lower = 100.


@pytest.mark.parametrize('stamp', [1100000000, 2100000000])
def test_original_source_now_reversal_closes_even_when_sequence_and_header_advance(stamp):
    source, provider, clock, _ = rig()
    assert receive(source, provider, source_now_ns=2000000000) is not None
    clock[0] = 10.1
    value = reading(sequence=2, stamp_ns=stamp)
    assert receive(source, provider, value, source_now_ns=1200000000) is None
    clock[0] = 10.2
    assert source.begin(provider) is None
