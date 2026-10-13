"""Successful snapshots reveal rejected captures and producer restarts without inventing commands."""
import pytest

from fleet.server.observation_store import ObservationStore
from fleet.server.core_event_store import EventRejected
from test_observation_store import sample


def test_legacy_imports_are_identity_aliases_of_observation_journal_owner():
    from fleet.observe.events import CoreEventStore as OwnedEvents
    from fleet.observe.store import ObservationStore as OwnedObservations
    from fleet.server.core_event_store import CoreEventStore
    assert CoreEventStore is OwnedEvents and ObservationStore is OwnedObservations


def test_one_capture_identity_covers_all_rows_and_next_poll_advances(tmp_path):
    store = ObservationStore(tmp_path / 'fleet.db')
    store.append_snapshot([sample(), dict(sample(), robot_id='rosy_02')], received_at=10, monotonic_now=10)
    rows = store.read_observations()
    first, second = [row['observation']['capture'] for row in rows]
    assert first == second
    assert first['sequence'] == 1 and len(first['run_id']) == 32
    assert first['robot_ids'] == ['rosy_01', 'rosy_02'] and first['monotonic_at'] == 10
    store.append_snapshot([sample()], received_at=11, monotonic_now=11)
    last = store.read_observations()[-1]['observation']['capture']
    assert last['run_id'] == first['run_id'] and last['sequence'] == 2


def test_failed_and_empty_captures_remain_visible_as_sequence_gaps(tmp_path):
    store = ObservationStore(tmp_path / 'fleet.db')
    store.append_snapshot([sample()], received_at=10, monotonic_now=10)
    with pytest.raises(EventRejected):
        store.append_snapshot([dict(sample(), state={'api_key': 'private'})], received_at=11, monotonic_now=11)
    store.append_snapshot([], received_at=12, monotonic_now=12)
    store.append_snapshot([sample()], received_at=13, monotonic_now=13)
    assert [r['observation']['capture']['sequence'] for r in store.read_observations()] == [1, 4]


def test_reopened_producer_changes_run_identity(tmp_path):
    path = tmp_path / 'fleet.db'
    first = ObservationStore(path)
    first.append_snapshot([sample()], received_at=10, monotonic_now=10)
    second = ObservationStore(path)
    second.append_snapshot([sample()], received_at=11, monotonic_now=11)
    rows = second.read_observations()
    assert rows[0]['observation']['capture']['run_id'] != rows[1]['observation']['capture']['run_id']


def test_duplicate_subjects_reject_entire_capture(tmp_path):
    store = ObservationStore(tmp_path / 'fleet.db')
    with pytest.raises(EventRejected):
        store.append_snapshot([sample(), sample()], received_at=10, monotonic_now=10)
    assert store.read_observations() == []
