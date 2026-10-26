"""Durable source-bound care records; advice never grants motion authority."""
import copy

import pytest

from fleet.server.device_profiles import DeviceProfileStore
from fleet.server.device_care import DeviceCareStore


def setup(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    profiles = DeviceProfileStore(path)
    for device in ('arm-one', 'arm-two'):
        profiles.put_profile(device, {'display_name': device, 'device_kind': 'manipulator'}, updated_by='alice')
    return path, DeviceCareStore(path)


def care(source='source-one'):
    return {'source_kind': 'arm', 'source_id': source, 'caution': '2·3번 관절 하중 주의', 'characteristics': None}


def test_persistence_and_source_uniqueness(tmp_path):
    path, store = setup(tmp_path)
    store.put('arm-one', care(), actor='alice')
    store.add_event('arm-one', {'kind': 'fault', 'text': '처짐 관찰'}, actor='alice')
    restored = DeviceCareStore(path)
    assert restored.by_source('arm', 'source-one')['device_id'] == 'arm-one'
    assert restored.get('arm-one')['events'][0]['text'] == '처짐 관찰'
    with pytest.raises(ValueError):
        store.put('arm-two', care(), actor='bob')
    assert store.get('arm-one')['caution'] == care()['caution']
    assert store.get('arm-two')['source_id'] is None


@pytest.mark.parametrize('change', [{'caution': []}, {'source_kind': 'camera'},
                                  {'source_id': '../arm'}, {'characteristics': {'schema': 'wrong'}}])
def test_invalid_replacement_preserves_previous(tmp_path, change):
    _, store = setup(tmp_path)
    store.put('arm-one', care(), actor='alice')
    before = store.get('arm-one')
    invalid = copy.deepcopy(care()) | change
    with pytest.raises(ValueError):
        store.put('arm-one', invalid, actor='alice')
    assert store.get('arm-one') == before


def test_missing_profile_and_unbound_reports_rejected(tmp_path):
    _, store = setup(tmp_path)
    with pytest.raises(ValueError):
        store.put('missing', care(), actor='alice')
    with pytest.raises(ValueError):
        store.ingest('arm-one', 'wrong-source', {}, now=100)
    assert store.get('arm-one')['latest_analysis'] is None
