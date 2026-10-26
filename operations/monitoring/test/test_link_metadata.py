from datetime import timedelta

import pytest
from pydantic import ValidationError

from rosy.monitoring.models import MonitoringLink
from test_cache import BASE, runtime, observed_node


def link(**changes):
    value = dict(id='site-a:probe:collector-a:pc-a', source_id='site-a:collector:collector-a',
                 target_id='site-a:host:pc-a', kind='probe', expected=True, reachable=True,
                 failure_stage='none', duration_ms=2.0, transport='https', last_success_at=BASE,
                 site_id='site-a', origin_collector='collector-a', origin_source='pc-a',
                 sample_id='probe-1', sampled_at=BASE, age_s=0.0, valid_for_s=15,
                 remaining_s=15.0, report_remaining_s=15.0, freshness='fresh')
    return MonitoringLink(**(value | changes))


def test_transport_and_success_metadata_are_closed_and_aware():
    assert link().transport == 'https'
    for changes in ({'transport': 'ssh-command'}, {'last_success_at': 10},
                    {'last_success_at': BASE.replace(tzinfo=None)},
                    {'last_success_at': BASE + timedelta(seconds=1)}):
        with pytest.raises(ValidationError):
            link(**changes)


def test_failed_probe_preserves_previous_success(runtime):
    cache, clock = runtime
    cache.update_local('pc-a', nodes=(observed_node(),), links=(link(),))
    clock.advance(1)
    failed = link(sample_id='probe-2', sampled_at=clock.utcnow(), reachable=False,
                  failure_stage='connect', last_success_at=None)
    cache.update_local('pc-a', nodes=(observed_node(),), links=(failed,))
    result = cache.snapshot(frozenset({'site-a'})).links[0]
    assert result.last_success_at == BASE and result.failure_stage == 'connect'
