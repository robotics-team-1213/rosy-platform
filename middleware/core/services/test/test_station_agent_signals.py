"""Legacy dock telemetry cannot invent a measured charger/BMS termination event."""
import pytest

from core_features.docking import agent


def poll(monkeypatch, **changes):
    document = dict(load_present=True, charging=False, current_a=0.0, faults=[]) | changes
    monkeypatch.setattr(agent, 'poll_json', lambda *args, **kwargs: (agent.PollReachability.OK, document, None))
    return agent.DockAgent('http://example').poll()


def test_legacy_zero_current_report_remains_unknown(monkeypatch):
    status = poll(monkeypatch)
    assert hasattr(status, 'termination'), 'dock termination source is not represented'
    assert status.termination == 'UNKNOWN'
    assert status.termination_sample_at is None


def test_measured_normal_event_preserves_source_timestamp_and_pack_identity(monkeypatch):
    status = poll(monkeypatch, termination='NORMAL', termination_source='charger',
                  termination_sample_at=100.0, battery_id='pack-1')
    assert hasattr(status, 'termination'), 'dock termination source is not represented'
    assert status.termination == 'NORMAL'
    assert status.termination_source == 'charger'
    assert status.termination_sample_at == 100.0 and status.battery_id == 'pack-1'


@pytest.mark.parametrize('changes', [dict(termination_source='unknown'), dict(termination_sample_at=None),
                                    dict(termination_sample_at=True), dict(termination_sample_at=float('nan')),
                                    dict(battery_id=None), dict(charging=True), dict(load_present=False),
                                    dict(faults=['OVER_TEMPERATURE'])])
def test_incoherent_or_unmeasured_normal_signal_is_never_promoted(monkeypatch, changes):
    fields = dict(termination='NORMAL', termination_source='charger', termination_sample_at=100.0,
                  battery_id='pack-1') | changes
    status = poll(monkeypatch, **fields)
    assert hasattr(status, 'termination'), 'dock termination source is not represented'
    assert status.termination == 'UNKNOWN'


@pytest.mark.parametrize('field', ['load_present', 'charging'])
@pytest.mark.parametrize('value', ['false', 'true', 0, 1, None, [], {}])
def test_non_boolean_required_fields_are_bad_responses(monkeypatch, field, value):
    assert poll(monkeypatch, **{field: value}).reachability == agent.DockReachability.BAD_RESPONSE


def test_switch_sample_time_is_preserved_without_using_poll_receipt_time(monkeypatch):
    status = poll(monkeypatch, load_sample_at=100.0)
    assert hasattr(status, 'load_sample_at'), 'physical contact sample time is missing'
    assert status.load_sample_at == 100.0
    assert poll(monkeypatch).load_sample_at is None
