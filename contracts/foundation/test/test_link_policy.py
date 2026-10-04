"""D-432: development selection is explicit, scoped, expiring and authenticated."""

import pytest
import json
from datetime import datetime
from pathlib import Path
from core_common.protocol.link_policy import LinkPolicy


def test_shared_policy_vectors():
    root = Path(__file__).resolve().parents[3]
    vectors = json.loads((root / 'test/fixtures/protocol/link-policy.v1.json').read_text(encoding='utf-8'))
    now = datetime.fromisoformat(vectors['now'].replace('Z', '+00:00')).timestamp()
    for case in vectors['cases']:
        if case['expect']['accepted']:
            result = LinkPolicy.from_mapping(case['policy'], now=now)
            assert result.mode == case['expect']['mode'], case['id']
        else:
            with pytest.raises(ValueError):
                LinkPolicy.from_mapping(case['policy'], now=now, deployment=case.get('deployment', 'development'))
    policy = LinkPolicy.from_mapping(next(c['policy'] for c in vectors['cases']
                                          if c['id'] == 'development_bound'), now=now)
    for check in vectors['permits']:
        checked_at = datetime.fromisoformat(check.get('now', vectors['now']).replace('Z', '+00:00')).timestamp()
        assert policy.permits(check['device_id'], check['service_type'], check['tls_host'],
                              authenticated=check['authenticated'], now=checked_at) == check['expected'], check['id']


def profile():
    return {'mode': 'development', 'site_name': 'bench-a', 'expires_at': '2030-01-01T00:00:00Z',
            'devices': [{'device_id': 'rosy_01', 'service_type': '_rosy._tcp',
                         'tls_host': 'robot-a.local'}]}


def test_no_configuration_is_operational_paired_mode():
    assert LinkPolicy.from_mapping(None).mode == 'paired'
    assert not LinkPolicy.from_mapping(None).permits('rosy_01', '_rosy._tcp', 'robot-a.local',
                                                     authenticated=True)


def test_development_scope_never_authorizes_another_device_or_plain_channel():
    policy = LinkPolicy.from_mapping(profile(), now=1700000000)
    assert policy.permits('rosy_01', '_rosy._tcp', 'robot-a.local', authenticated=True, now=1700000000)
    assert not policy.permits('rosy_02', '_rosy._tcp', 'robot-a.local', authenticated=True, now=1700000000)
    assert not policy.permits('rosy_01', '_rosy._tcp', 'robot-a.local', authenticated=False, now=1700000000)
    assert not policy.permits('rosy_01', '_rosy-fleet._tcp', 'robot-a.local', authenticated=True, now=1700000000)
    assert not policy.permits('rosy_01', '_rosy._tcp', 'other.local', authenticated=True, now=1700000000)
    assert not policy.permits('rosy_01', '_rosy._tcp', 'robot-a.local', authenticated=True, now=2000000000)


@pytest.mark.parametrize('change', [{'mode': 'auto'}, {'site_name': ''}, {'expires_at': 'invalid'},
                                    {'devices': []}, {'expires_at': '2020-01-01T00:00:00Z'}])
def test_invalid_or_expired_development_policy_cannot_downgrade(change):
    with pytest.raises(ValueError):
        LinkPolicy.from_mapping({**profile(), **change}, now=1700000000)


def test_production_cannot_enable_development_policy():
    with pytest.raises(ValueError, match='production'):
        LinkPolicy.from_mapping(profile(), deployment='production', now=1700000000)


def test_same_host_cannot_be_assigned_to_two_devices():
    data = profile()
    data['devices'].append({**data['devices'][0], 'device_id': 'rosy_02'})
    with pytest.raises(ValueError, match='duplicate'):
        LinkPolicy.from_mapping(data, now=1700000000)
