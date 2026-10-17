"""Full map identity is an original observation, never Nav2 adoption authority."""
from dataclasses import replace
from uuid import uuid4

import pytest


@pytest.fixture
def source():
    from core_features.navigation.map_evidence import GridContent, MapEvidence
    content = GridContent('map', 2, 2, .05, (-1., -.5, 0., 0., 0., 0., 1.),
                          (0, 100, -1, 50), 1000000000, 1000000000)
    return MapEvidence(robot_id='robot', boot_id=uuid4()), content


def put(owner, content):
    token = owner.begin(content.stamp_ns, content.load_time_ns)
    assert owner.complete(token, content)
    return owner.snapshot()


def test_digest_uses_versioned_full_binary_grid_and_ignores_temporal_header(source):
    import hashlib
    import struct
    from core_features.navigation.map_evidence import content_digest
    _, content = source
    payload = (b'ROSY-GRID-v1\0' + struct.pack('<I', 3) + b'map'
               + struct.pack('<II8d', 2, 2, .05, -1., -.5, 0., 0., 0., 0., 1.)
               + bytes([0, 100, 255, 50]))
    assert content_digest(content) == hashlib.sha256(payload).hexdigest()
    assert content_digest(replace(content, stamp_ns=2000000000)) == content_digest(content)


def test_ticket_is_one_use_and_old_cleanup_cannot_clear_new_source(source):
    owner, content = source
    first = owner.begin(content.stamp_ns, content.load_time_ns)
    second_content = replace(content, stamp_ns=2000000000)
    second = owner.begin(second_content.stamp_ns, second_content.load_time_ns)
    assert owner.complete(second, second_content)
    expected = owner.snapshot()
    assert not owner.complete(first, content)
    owner.abort(first)
    assert owner.snapshot() == expected
    assert not owner.complete(second, second_content)


def test_lifecycle_during_hash_cannot_seal_old_callback(source, monkeypatch):
    from threading import Event, Thread
    from core_features.navigation import map_evidence
    owner, content = source
    digest = map_evidence.content_digest
    done, finished, threads = Event(), [], []
    def invalidate():
        try:
            owner.lifecycle(False)
            owner.lifecycle(True)
        finally:
            done.set()
    def interpose(value):
        worker = Thread(target=invalidate, daemon=True)
        threads.append(worker)
        worker.start()
        finished.append(done.wait(1.))  # Must finish BEFORE hash returns, even with an RLock.
        return digest(value)
    monkeypatch.setattr(map_evidence, 'content_digest', interpose)
    ticket = owner.begin(content.stamp_ns, content.load_time_ns)
    accepted = owner.complete(ticket, content)
    for worker in threads: worker.join(1.)
    assert finished == [True] and not accepted and owner.snapshot() is None


def test_pending_validation_closes_snapshot_without_renewing_original_identity(source):
    owner, content = source
    original = put(owner, content)
    ticket = owner.begin(content.stamp_ns, content.load_time_ns)
    assert owner.snapshot() is None
    assert owner.complete(ticket, content)
    assert owner.snapshot().generation == original.generation


@pytest.mark.parametrize('change', ['stamp_reverse', 'load_reverse', 'changed_same_stamp'])
def test_original_order_and_unchanged_header_payload_are_enforced(source, change):
    owner, content = source
    put(owner, replace(content, stamp_ns=2000000000))
    other = content if change == 'stamp_reverse' else replace(content, stamp_ns=2000000000)
    if change == 'load_reverse': other = replace(other, load_time_ns=0)
    elif change == 'changed_same_stamp': other = replace(other, data=(1, 100, -1, 50))
    ticket = owner.begin(other.stamp_ns, other.load_time_ns)
    assert not owner.complete(ticket, other) and owner.snapshot() is None


def test_static_latched_map_does_not_get_an_odometry_age_or_new_backend_ack(source):
    owner, content = source
    original = put(owner, replace(content, stamp_ns=0, load_time_ns=0))
    assert original.stamp_ns == original.load_time_ns == 0
    assert owner.snapshot() == original
    assert not hasattr(original, 'backend_ack') and not hasattr(original, 'admitted')
