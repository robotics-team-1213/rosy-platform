"""Source age must survive transport; malformed/replayed data gives no new credit."""
import pytest
from dataclasses import FrozenInstanceError

from omx_adapter.command_owner import ArmCommandConfig
from omx_adapter.joint_state_intake import JointStateIntake


def intake():
    return JointStateIntake(ArmCommandConfig(
        enabled=True, workcell_id="w", instance_id="i", joint_names=("joint1", "joint2"),
        position_limits={"joint1": (-1., 1.), "joint2": (-1., 1.)},
        allowed_owners=("moveit",), calibration_revision="cal", max_joint_state_age_s=.5))


def sample(reader, **changes):
    values = dict(names=["joint2", "joint1", "mimic"], positions=[.2, .1, .3],
                  stamp_ns=1_000_000_000, source_now_ns=1_200_000_000, received_at=10.)
    values.update(changes)
    return reader.snapshot(**values)


def test_transport_delay_is_deducted_from_owner_freshness():
    snapshot = sample(intake())
    assert snapshot.received_at == pytest.approx(9.8)
    assert dict(snapshot.positions) == {"joint1": .1, "joint2": .2}


def test_source_stamps_remain_bound_to_the_accepted_snapshot_after_rejection():
    reader = intake()
    first = sample(reader)
    assert (first.source_stamp_ns, first.source_now_ns) == (1_000_000_000, 1_200_000_000)
    with pytest.raises(ValueError):
        sample(reader, stamp_ns=1_300_000_000)
    reader.last_attempt['stamp_ns'] = 9
    reader.last_attempt['source_now_ns'] = 10
    assert (first.source_stamp_ns, first.source_now_ns, first.sequence) == (1_000_000_000, 1_200_000_000, 1)
    assert first.received_at == pytest.approx(9.8)
    with pytest.raises(FrozenInstanceError):
        first.source_stamp_ns = 9
    second = sample(reader, stamp_ns=1_100_000_000, received_at=10.1)
    assert (second.source_stamp_ns, second.source_now_ns, second.sequence) == (1_100_000_000, 1_200_000_000, 2)
    assert second.received_at == pytest.approx(10.)


def test_legacy_snapshot_has_no_invented_source_time():
    from omx_adapter.command_owner import JointStateSnapshot
    state = JointStateSnapshot({'joint1': .1}, 1, 10., 'cal')
    assert state.source_stamp_ns is None and state.source_now_ns is None
    assert state.received_at == 10.


@pytest.mark.parametrize('stamp,now', [(None, 2), (1, None), (True, 2), (1, True),
                                       (0, 2), (-1, 2), (2, 1), (1., 2)])
def test_partial_or_invalid_source_metadata_cannot_be_attached_to_a_snapshot(stamp, now):
    from omx_adapter.command_owner import JointStateSnapshot
    with pytest.raises(ValueError):
        JointStateSnapshot({'joint1': .1}, 1, 10., 'cal', source_stamp_ns=stamp, source_now_ns=now)


def test_metadata_preserves_source_integers_without_adding_a_new_intake_range_gate():
    stamp = 2**80
    state = sample(intake(), stamp_ns=stamp, source_now_ns=stamp)
    assert (state.source_stamp_ns, state.source_now_ns, state.received_at) == (stamp, stamp, 10.)


@pytest.mark.parametrize("changes", [
    {"stamp_ns": 0}, {"stamp_ns": 1_300_000_000}, {"stamp_ns": 600_000_000},
    {"names": ["joint1", "joint1", "joint2"]},
    {"positions": [.1]}, {"names": ["joint1", "other", "mimic"]},
    {"positions": [float("nan"), .1, .2]}, {"positions": [True, .1, .2]},
])
def test_rejected_packet_does_not_poison_next_valid_source_or_sequence(changes):
    reader = intake()
    with pytest.raises(ValueError):
        sample(reader, **changes)
    assert sample(reader).sequence == 1


def test_replay_and_backward_source_do_not_refresh_sequence():
    reader = intake()
    first = sample(reader)
    for stamp in [1_000_000_000, 900_000_000]:
        with pytest.raises(ValueError):
            sample(reader, stamp_ns=stamp)
    assert sample(reader, stamp_ns=1_100_000_000).sequence == first.sequence + 1


def test_increasing_clocks_with_variable_delay_cannot_deliver_regressed_receipt():
    reader = intake()
    first = sample(reader)
    # Both clocks/stamps advance, but subtracting the larger source age goes backward.
    with pytest.raises(ValueError):
        sample(reader, stamp_ns=1_100_000_000, source_now_ns=1_400_000_000, received_at=10.05)
    current = sample(reader, stamp_ns=1_100_000_000, source_now_ns=1_200_000_000, received_at=10.1)
    assert current.sequence == first.sequence+1
    assert current.received_at == pytest.approx(10.)

@pytest.mark.parametrize('changes,code', [
    ({'stamp_ns': 1_400_000_000}, 'STAMP_REJECTED'),
    ({'stamp_ns': 1_000_000_000}, 'STAMP_REJECTED'),
    ({'stamp_ns': 1_100_000_000, 'source_now_ns': 1_900_000_000}, 'SOURCE_STALE'),
    ({'stamp_ns': 1_100_000_000, 'positions': [.1]}, 'ARRAY_SHAPE'),
    ({'stamp_ns': 1_100_000_000, 'positions': [float('nan'), .1, .2]}, 'NONFINITE'),
])
def test_rejection_facts_preserve_original_rejection_and_do_not_refresh(changes, code):
    reader = intake()
    first = sample(reader)
    with pytest.raises(ValueError):
        sample(reader, **changes)
    facts = reader.last_rejection
    assert facts is reader.last_attempt
    assert facts == dict(stamp_ns=changes['stamp_ns'],
                         source_now_ns=changes.get('source_now_ns', 1_200_000_000),
                         received_at=10., prior_accepted_stamp_ns=1_000_000_000,
                         accepted=False, rejection_code=code, error_type='ValueError',
                         wall_received_at=facts['wall_received_at'])
    assert facts['wall_received_at'] > 0
    assert reader._last_stamp_ns == 1_000_000_000 and reader._sequence == first.sequence
    second = sample(reader, stamp_ns=1_150_000_000)
    assert second.sequence == first.sequence + 1
    assert second.received_at == pytest.approx(9.95)
    assert reader.last_attempt['accepted'] is True
    assert reader.last_rejection is facts


def test_observation_wrapper_calls_algorithm_once_and_preserves_return_and_exception_identity(monkeypatch):
    reader = intake()
    marker = object()
    calls = []
    def succeed(*args, **kwargs):
        calls.append(kwargs)
        return marker
    monkeypatch.setattr(reader, '_snapshot', succeed)
    assert sample(reader) is marker and len(calls) == 1
    assert reader.last_attempt == dict(stamp_ns=1_000_000_000, source_now_ns=1_200_000_000,
                                      received_at=10., prior_accepted_stamp_ns=0, accepted=True,
                                      wall_received_at=reader.last_attempt['wall_received_at'])
    error = OverflowError('PRIVATE_INPUT_MUST_NOT_BE_RECORDED')
    def reject(*args, **kwargs):
        calls.append(kwargs)
        raise error
    monkeypatch.setattr(reader, '_snapshot', reject)
    with pytest.raises(OverflowError) as caught:
        sample(reader)
    assert caught.value is error and len(calls) == 2
    assert reader.last_rejection['rejection_code'] == 'INPUT_INVALID'
    assert 'PRIVATE_INPUT' not in repr(reader.last_rejection)


def test_invalid_observation_values_never_copy_arbitrary_payload():
    reader = intake()
    with pytest.raises(ValueError):
        sample(reader, stamp_ns=['PRIVATE'], source_now_ns={'token': 'PRIVATE'}, received_at='PRIVATE')
    assert reader.last_rejection == dict(stamp_ns=None, source_now_ns=None, received_at=None,
                                        prior_accepted_stamp_ns=0, accepted=False,
                                        rejection_code='STAMP_REJECTED', error_type='ValueError',
                                        wall_received_at=reader.last_rejection['wall_received_at'])


def test_intake_counts_and_steady_observation_time_are_bounded(monkeypatch):
    import omx_adapter.joint_state_intake as module
    reader = intake()
    monkeypatch.setattr(module.time, 'monotonic', lambda: 123.5)
    sample(reader)
    for _ in range(3):
        with pytest.raises(ValueError):
            sample(reader)
    assert (reader.attempt_count, reader.accepted_count, reader.rejected_count) == (4, 1, 3)
    assert reader.last_attempt['wall_received_at'] == 123.5
    reader.attempt_count = reader.accepted_count = reader.rejected_count = 2**63-1
    sample(reader, stamp_ns=1_100_000_000)
    with pytest.raises(ValueError):
        sample(reader)
    assert (reader.attempt_count, reader.accepted_count, reader.rejected_count) == (2**63-1,) * 3
