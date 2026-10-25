"""A receiving process restart must not erase chronology or renew evidence."""

from datetime import timedelta
import sqlite3

import pytest

from rosy.monitoring.cache import ObservationCache, ObservationRejected
from rosy.monitoring.store import MonitoringStore, StoreUnavailable
from test_cache import find, observed_node, runtime, receive, peer


def reopen(cache, clock, path):
    return ObservationCache(cache.config, monotonic=clock.monotonic, utcnow=clock.utcnow,
                            store=MonitoringStore(path, cache.config.collector_id))


def test_second_writer_cannot_open_the_same_owned_store(tmp_path):
    path = tmp_path / 'monitoring.sqlite3'
    first = MonitoringStore(path, 'collector-a')
    with pytest.raises(StoreUnavailable):
        MonitoringStore(path, 'collector-a')
    first.close()
    second = MonitoringStore(path, 'collector-a')
    second.close()


def test_restart_retains_health_age_and_shortened_deadline(runtime, tmp_path):
    original, clock = runtime
    path = tmp_path / 'monitoring.sqlite3'
    cache = reopen(original, clock, path)
    value = observed_node(health='ERROR').model_copy(update={'remaining_s': 10.0})
    cache.update_local('pc-a', nodes=(value,))
    clock.advance(4)
    restored = reopen(original, clock, path)
    result = find(restored, value.id)
    assert result.reported_health == 'ERROR' and result.freshness == 'stale'
    assert result.age_s >= 104 and result.remaining_s <= 6
    restored.update_local('pc-a', nodes=(value,))
    assert find(restored, value.id).remaining_s <= 6
    older = observed_node(health='OK', sample='old', sampled_at=value.sampled_at - timedelta(seconds=1))
    with pytest.raises(ObservationRejected):
        restored.update_local('pc-a', nodes=(older,))


def test_missing_rows_do_not_erase_durable_anchor(runtime, tmp_path):
    original, clock = runtime
    path = tmp_path / 'monitoring.sqlite3'
    cache = reopen(original, clock, path)
    value = observed_node(health='ERROR')
    cache.update_local('pc-a', nodes=(value,))
    cache.update_local('pc-a')
    restored = reopen(original, clock, path)
    with pytest.raises(ObservationRejected):
        restored.update_local('pc-a', nodes=(value.model_copy(update={'reported_health': 'OK'}),))


def test_peer_cursor_survives_receiving_restart(runtime, tmp_path):
    original, clock = runtime
    path = tmp_path / 'monitoring.sqlite3'
    cache = reopen(original, clock, path)
    message = peer(clock)
    receive(cache, clock, message)
    restored = reopen(original, clock, path)
    with pytest.raises(ObservationRejected):
        receive(restored, clock, message)


def test_storage_failure_cannot_publish_or_advance_cursor(runtime, tmp_path, monkeypatch):
    original, clock = runtime
    store = MonitoringStore(tmp_path / 'monitoring.sqlite3', original.config.collector_id)
    cache = ObservationCache(original.config, monotonic=clock.monotonic, utcnow=clock.utcnow, store=store)
    def fail(*args, **kwargs):
        raise StoreUnavailable()
    monkeypatch.setattr(store, 'save', fail)
    with pytest.raises(StoreUnavailable):
        receive(cache, clock, peer(clock))
    assert not cache._peers
    assert find(cache, 'site-a:host:pc-a').freshness == 'unknown'


def test_foreign_or_corrupt_database_is_not_recreated(tmp_path):
    for name, body in [('corrupt', b'not sqlite'), ('foreign', b'')]:
        path = tmp_path / name
        path.write_bytes(body)
        if name == 'foreign':
            with sqlite3.connect(path) as connection:
                connection.execute('create table precious (value text)')
                connection.execute("insert into precious values ('keep')")
        before = path.read_bytes()
        with pytest.raises(StoreUnavailable):
            MonitoringStore(path, 'collector-a')
        assert path.read_bytes() == before


def test_clock_rollback_fails_closed(runtime, tmp_path):
    original, clock = runtime
    path = tmp_path / 'monitoring.sqlite3'
    cache = reopen(original, clock, path)
    cache.update_local('pc-a', nodes=(observed_node(),))
    clock.t = -10
    with pytest.raises(StoreUnavailable):
        reopen(original, clock, path)


def test_history_ignores_polling_age_and_is_site_scoped(runtime, tmp_path):
    original, clock = runtime
    path = tmp_path / 'monitoring.sqlite3'
    cache = reopen(original, clock, path)
    value = observed_node()
    cache.update_local('pc-a', nodes=(value,))
    clock.advance(1)
    cache.update_local('pc-a', nodes=(value,))
    events = cache.store.events('site-a', after=0, limit=100)
    assert len(events) == 1 and events[0]['item_id'] == value.id
    assert cache.store.events('site-b', after=0, limit=100) == []


def test_removed_configuration_cannot_bypass_durable_anchor_budget(runtime, tmp_path):
    original, clock = runtime
    path = tmp_path / 'monitoring.sqlite3'
    first = reopen(original, clock, path)
    template = observed_node()
    for offset in range(0, 8192, 256):
        nodes = tuple(template.model_copy(update={'id': f'site-a:host:old-{i}'})
                      for i in range(offset, offset + 256))
        first.update_local('pc-a', nodes=nodes)
    source = original.config.sources[0].model_copy(update={'id': 'pc-new'})
    config = original.config.model_copy(update={'sources': (source, original.config.sources[1])})
    second = ObservationCache(config, monotonic=clock.monotonic, utcnow=clock.utcnow,
                              store=MonitoringStore(path, config.collector_id))
    with pytest.raises(StoreUnavailable):
        second.update_local('pc-new', nodes=(observed_node(source='pc-new'),))
    assert find(second, 'site-a:host:pc-new').freshness == 'unknown'
