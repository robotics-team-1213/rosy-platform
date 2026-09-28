import pytest

from fleet.server.goal_evidence import GoalEvidence, GoalEvidenceError, GoalPredicate, verify_goal


def predicate():
    return GoalPredicate(
        predicate_id="block-in-tray", condition="object_in_destination",
        object_id="block-1", destination_id="tray-1", evidence_source="camera_observation",
    )


def evidence(**changes):
    values = dict(
        predicate_id="block-in-tray", object_id="block-1", destination_id="tray-1",
        evidence_source="camera_observation", evidence_id="camera:frame-55",
        evidence_revision="cal-v3/tf-v7", observed_at=10.0, satisfied=True,
    )
    values.update(changes)
    return GoalEvidence(**values)


def test_independent_fresh_matching_predicate_is_confirmed():
    assert verify_goal(predicate(), evidence(), now=10.2, max_age_s=0.5)


@pytest.mark.parametrize("changes, reason", [
    ({"evidence_source": "model_summary"}, "source"),
    ({"object_id": "block-2"}, "object"),
    ({"destination_id": "other-tray"}, "destination"),
    ({"satisfied": False}, "not satisfied"),
    ({"observed_at": 9.0}, "stale"),
    ({"evidence_revision": ""}, "revision"),
])
def test_goal_success_refuses_model_claims_conflicts_and_stale_evidence(changes, reason):
    with pytest.raises(GoalEvidenceError, match=reason):
        verify_goal(predicate(), evidence(**changes), now=10.2, max_age_s=0.5)
