"""D-782 §3 arm state is an observed fact: bounded, fresh, monotonic and never a guessed object state."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from rosy.world.state.projections.arm_state import ArmState, ArmStateTracker


def test_fresh_state_is_returned_and_stale_state_is_not_extrapolated():
    tracker = ArmStateTracker('rig-1', 'cal-1')
    tracker.observe('s/0', 1_000, (0.,)*5+(50.,))
    assert tracker.current(1_000 + 100_000_000, .2).joints == (0.,)*5+(50.,)
    assert tracker.current(1_000 + 300_000_000, .2) is None
    assert ArmStateTracker('rig-1', 'cal-1').current(0, 1.) is None


def test_replayed_clock_is_refused():
    tracker = ArmStateTracker('rig-1', 'cal-1')
    tracker.observe('s/0', 2_000, (0.,)*6)
    with pytest.raises(ValueError, match='replayed'):
        tracker.observe('s/1', 2_000, (0.,)*6)


@pytest.mark.parametrize('joints', [(0.,)*5, (101.,)+(0.,)*5, (0.,)*5+(-1.,), (float('nan'),)*6])
def test_values_must_be_six_normalized_finite_numbers(joints):
    with pytest.raises(ValueError):
        ArmState('s/0', 1, 'rig-1', 'cal-1', joints)


def test_object_state_is_not_guessed():
    with pytest.raises(ValueError, match='object observer'):
        ArmState('s/0', 1, 'rig-1', 'cal-1', (0.,)*6, object_state='grasped')
