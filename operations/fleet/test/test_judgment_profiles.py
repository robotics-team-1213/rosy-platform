from dataclasses import FrozenInstanceError, replace

import pytest

from rosy.decision.deliberation import Problem
from rosy.decision.deliberation.profiles import AdapterCapabilities, ModelProfile, bind_profile


def problem(domain='line_follow'):
    return Problem('robot', 'case', 'g1', domain, 1, ('e1',), ('human', 'reobserve'), 'INTERVENE')


def profile(**changes):
    values = dict(profile_id='model-primary', profile_revision='p1', role='primary',
                  provider_kind='local', model_id='model', model_revision='digest-1', adapter='json-local',
                  domains=('line_follow', 'door', 'arm_target'), modalities=('text',),
                  timeout_s=30, max_output_bytes=16384, max_calls=2, max_cost_usd=0,
                  calibration_revision=None)
    return ModelProfile(**{**values, **changes})


def adapter(**changes):
    values = dict(provider_kind='local', model_id='model', model_revision='digest-1', adapter='json-local',
                  schema_version=2, domains=('line_follow', 'door', 'arm_target'), modalities=('text',),
                  ready=True, isolated=True, cost_verified=True)
    return AdapterCapabilities(**{**values, **changes})


@pytest.mark.parametrize('domain', ['line_follow', 'door', 'arm_target'])
def test_generic_model_binding_scopes_case_profile_and_capabilities(domain):
    p, selected = problem(domain), profile()
    bound = bind_profile(p, selected, adapter(), required_modalities=('text',))
    assert bound.profile == selected and bound.input_hash == p.digest
    bound.validate(p, selected)
    with pytest.raises(ValueError):
        bound.validate(replace(p, generation='g2'), selected)
    with pytest.raises(ValueError):
        bound.validate(p, replace(selected, profile_revision='p2'))
    with pytest.raises(FrozenInstanceError):
        bound.input_hash = 'other'


@pytest.mark.parametrize('change', [dict(ready=False), dict(isolated=False), dict(cost_verified=False),
                                  dict(model_revision='other'), dict(adapter='other'),
                                  dict(schema_version=1), dict(domains=('door',)), dict(modalities=('image',))])
def test_unready_or_incompatible_model_never_bound(change):
    with pytest.raises(ValueError):
        bind_profile(problem(), profile(), adapter(**change), required_modalities=('text',))


@pytest.mark.parametrize('change', [dict(role='driver'), dict(timeout_s=True), dict(max_cost_usd=float('nan')),
                                  dict(max_output_bytes=16385), dict(max_calls=0), dict(domains=('unknown',)),
                                  dict(modalities=()), dict(schema_version=1)])
def test_profiles_reject_unbounded_or_unknown_configuration(change):
    with pytest.raises(ValueError):
        profile(**change)


def test_profile_copies_capability_lists_and_supports_vendor_neutral_replacement():
    domains = ['line_follow']
    p = profile(domains=domains)
    domains.append('door')
    assert p.domains == ('line_follow',)
    replacement = profile(profile_id='next-model', model_id='another', model_revision='next-digest')
    bind_profile(problem(), replacement, adapter(model_id='another', model_revision='next-digest'),
                 required_modalities=('text',))
