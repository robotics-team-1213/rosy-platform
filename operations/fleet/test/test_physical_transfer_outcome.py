"""Task assessment needs every sample's provenance before judging the object."""
from dataclasses import replace
from importlib import import_module

import pytest

from test_physical_transfer_evidence import BASE, context, geometry, policy, samples


def assess(policy, observations=None, *, action_state="SUCCEEDED", **changes):
    return import_module("fleet.server.physical_transfer_outcome").assess_transfer_outcome(
        policy, context(policy, "POST_ACTION"), observations or samples(policy, after=True),
        action_state=action_state, now_ns=changes.pop("now_ns", BASE + 350_000_000),
        authenticated_producer_id=changes.pop("authenticated_producer_id", policy.producer_id), **changes)


def test_observed_target_success_and_confirmed_target_miss_are_distinct(policy):
    result = assess(policy)
    assert (result.action_outcome, result.task_outcome, result.reason) == ("SUCCEEDED", "succeeded", None)
    result = assess(policy, samples(policy))
    assert (result.action_outcome, result.task_outcome, result.reason) == (
        "SUCCEEDED", "failed", "TARGET_NOT_REACHED")


def test_missing_or_conflicting_object_observations_are_unknown(policy):
    observed = samples(policy, after=True)
    for observations in ((replace(observed[0], object_pose=None), observed[1]),
                         (samples(policy)[0], observed[1])):
        result = assess(policy, observations)
        assert result.action_outcome == "SUCCEEDED" and result.task_outcome == "unknown"


@pytest.mark.parametrize("state", ["FAILED", "UNKNOWN", "HOLD", "CANCEL_REQUESTED", "RUNNING"])
def test_owner_result_is_preserved_without_claiming_task_success(policy, state):
    result = assess(policy, action_state=state)
    assert result.action_outcome == state and result.task_outcome == "unknown"


@pytest.mark.parametrize("change", [dict(attempt_id="other"), dict(object_observed_at_ns=BASE),
                                  dict(policy_digest="a" * 64)])
def test_invalid_later_sample_cannot_certify_earlier_target_miss(policy, change):
    observed = samples(policy)
    with pytest.raises(ValueError, match="PHYSICAL_"):
        assess(policy, (observed[0], replace(observed[1], **change)))


def test_unknown_gripper_or_occupied_zone_cannot_be_a_failure_label(policy):
    from test_physical_transfer_evidence import change_link
    from rosy.world.state.projections.physical_transfer import Bounds3

    observed = samples(policy)
    owner = replace(observed[0].owners[0], gripper_state="UNKNOWN", held_state="UNKNOWN")
    for first in (replace(observed[0], owners=(owner, *observed[0].owners[1:])),
                  change_link(observed[0], bounds=Bounds3((0, 0, .1), (.01, .01, .2)))):
        result = assess(policy, (first, observed[1]))
        assert result.task_outcome == "unknown"


def test_wrong_producer_and_unsupported_action_state_are_rejected(policy):
    with pytest.raises(ValueError, match="PHYSICAL_PRODUCER_MISMATCH"):
        assess(policy, authenticated_producer_id="other")
    with pytest.raises(ValueError, match="action state"):
        assess(policy, action_state="accepted")
