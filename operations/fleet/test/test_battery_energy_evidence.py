"""Voltage-only power telemetry must not manufacture capacity or health measurements."""
import importlib
import importlib.util


def adapter(health):
    name = 'rosy.execution.site.battery_evidence'
    assert importlib.util.find_spec(name) is not None, 'battery evidence adapter is not implemented'
    return importlib.import_module(name).battery_evidence_from_health(
        health, battery_id='pack-1', now=100.0, max_age_s=5.0)


def test_legacy_voltage_health_is_only_soc_evidence():
    value = adapter({'evidence': 'fresh', 'sample_age_s': 0.2, 'percent': 60.0})
    assert value.soc_percent == 60.0
    assert value.source == 'voltage_only'
    assert value.captured_at == 99.8
    assert value.soh_percent is None and value.usable_energy_wh is None


def test_missing_or_stale_telemetry_is_not_converted_into_a_fresh_healthy_pack():
    missing = adapter({})
    assert missing.source == 'unknown'
    assert missing.soc_percent is None
    assert missing.fault is not None
    stale = adapter({'evidence': 'stale', 'sample_age_s': 9.0, 'percent': 60.0})
    assert stale.valid_until < 100.0
    assert stale.soh_percent is None
