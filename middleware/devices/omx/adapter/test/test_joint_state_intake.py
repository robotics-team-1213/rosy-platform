"""Source age must survive transport; malformed/replayed data gives no new credit."""
import pytest

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
