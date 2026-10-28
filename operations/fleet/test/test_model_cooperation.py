"""Independent review preserves scope and stops without creating execution authority."""
import asyncio
from dataclasses import replace
import importlib
import importlib.util

import pytest

from rosy.decision.deliberation import Problem


def api():
    name = 'rosy.decision.deliberation.cooperation'
    assert importlib.util.find_spec(name) is not None, 'conditional cooperation is missing'
    return importlib.import_module(name)


def problem(**changes):
    return replace(Problem('pinky', 'lane-1', 'g1', 'line_follow', 100.0,
        ('core-1',), ('reobserve', 'human'), 'INTERVENE', facts_json='{"state":"blocked"}',
        fleet_choice='human'), **changes)


def reply(request, choice='reobserve', objections=()):
    return dict(subject_id=request.subject_id, case_id=request.case_id, generation=request.generation,
        input_hash=request.digest, choice=choice, evidence_ids=['core-1'], objections=list(objections))


def test_trigger_requires_scoped_valid_opinion_and_preserves_safety():
    m, request = api(), problem()
    assert m.cooperation_trigger(request, reply(request)) == 'baseline_disagreement'
    assert m.cooperation_trigger(request, reply(request, 'human')) is None
    assert m.cooperation_trigger(request, reply(request, objections=['unsafe'])) is None
    assert m.cooperation_trigger(request, reply(request, objections=['conflict'])) == 'conflict'
    assert m.cooperation_trigger(request, reply(request, objections=['insufficient_evidence'])) == 'insufficient_evidence'
    assert m.cooperation_trigger(replace(request, necessity='DO_NOT_INTERVENE'), {}) is None
    with pytest.raises(ValueError): m.cooperation_trigger(request, reply(replace(request, generation='g2')))


def test_review_request_is_immutable_scoped_and_contains_readable_facts():
    m, request = api(), problem()
    review = m.ReviewRequest(request, 'critique', 'baseline_disagreement')
    assert review.body()['problem']['facts_json'] == '{"state":"blocked"}'
    assert review.body()['prior'] == []
    with pytest.raises(ValueError): m.ReviewRequest(request, 'controller', 'conflict')
    with pytest.raises(ValueError): m.ReviewRequest(request, 'critique', 'timeout')
    with pytest.raises(ValueError): m.ReviewRequest(replace(request, facts_json='{"state":"unknown"}'), 'critique', 'conflict')
