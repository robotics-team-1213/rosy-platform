"""Finite sampled native map evidence; synthetic replies confer no device authority."""
from dataclasses import replace
from types import SimpleNamespace as NS
from uuid import uuid4
import math

import pytest

from core_features.navigation.map_evidence import MapEvidence, GridContent
from core_features.navigation.native_map_adoption import Consumer, NativeMapEvidence
from core_features.navigation.native_map_reply import NativeReply


def raw(boot=None):
    source = MapEvidence(robot_id='unit', boot_id=boot or uuid4())
    token = source.begin(20, 10)
    assert source.complete(token, GridContent('map', 2, 1, .05,
        (-1., 2., 0., 0., 0., 0., 1.), (0, 100), 20, 10))
    return source


@pytest.fixture
def run():
    state = NS(source=raw(), parent=object(), time=10., stopped=[])
    profiles = tuple(Consumer(role, '/unit/' + node, 'a'*64, 'b'*64, object())
        for role, node in [('amcl', 'amcl'), ('static_layer', 'global_costmap/global_costmap')])
    state.owner = NativeMapEvidence(source=lambda: state.source, parent=lambda: state.parent,
        consumers=profiles, clock=lambda: state.time, stop=state.stopped.append,
        max_parents=4, max_queries=256)
    state.profiles = {profile.role: profile for profile in profiles}
    state.nonce = 0
    return state


def issue(run, round_, role):
    run.nonce += 1
    profile = run.profiles[role]
    return run.owner.issue(round_, role, profile.provider, run.nonce.to_bytes(16, 'big'))


def reply(run, ticket, **changes):
    observation = run.source.snapshot()
    profile = run.profiles[ticket.role]
    value = NativeReply(1, ticket.nonce, bytes([1 if ticket.role == 'amcl' else 2])*16,
        1, True, True, 'adopted', ticket.role, profile.node_fqn, profile.build_id,
        profile.config_digest, observation.digest, observation.frame, observation.width,
        observation.height, observation.resolution, observation.origin,
        observation.stamp_ns, observation.load_time_ns)
    return replace(value, **changes)


def complete(run, **changes):
    round_ = run.owner.begin()
    assert round_ is not None
    for role in ('amcl', 'static_layer'):
        ticket = issue(run, round_, role)
        assert ticket is not None
        assert run.owner.reply(ticket, run.profiles[role].provider,
            reply(run, ticket, **changes.get(role, {})))
    return run.owner.sample(run.parent)


def test_both_independent_replies_required_and_first_before_bounds_lifetime(run):
    round_ = run.owner.begin()
    run.time = 10.01
    a = issue(run, round_, 'amcl')
    assert run.owner.reply(a, run.profiles['amcl'].provider, reply(run, a))
    assert run.owner.sample(run.parent) is None
    run.time = 10.10
    b = issue(run, round_, 'static_layer')
    run.time = 10.24
    assert run.owner.reply(b, run.profiles['static_layer'].provider, reply(run, b))
    sample = run.owner.sample(run.parent)
    assert sample.source is run.source and sample.observation is run.source.snapshot()
    assert sample.parent is run.parent and sample.first_before == 10.01
    assert sample.expires_at == 10.51
    assert run.owner.valid(sample, run.parent, raw_source=run.source, now=10.50)
    assert not run.owner.valid(sample, run.parent, raw_source=run.source, now=10.51)


def test_default_global_nonce_capacity_cannot_be_reset_by_a_new_parent(run):
    run.owner = NativeMapEvidence(source=lambda: run.source, parent=lambda: run.parent,
        consumers=tuple(run.profiles.values()), clock=lambda: run.time, stop=run.stopped.append)
    for index in range(32768):
        run.time = 10. + index * .25
        sample = complete(run)
        assert sample is not None
    assert run.nonce == 65536 and not run.stopped
    run.time = 10. + 8192.
    round_ = run.owner.begin()
    assert round_ is not None and issue(run, round_, 'amcl') is None
    assert run.stopped == [run.parent]
    assert not run.owner.valid(sample, run.parent, raw_source=run.source, now=run.time)
    old_parent = run.parent
    run.parent = object()
    round_ = run.owner.begin()
    assert round_ is not None and issue(run, round_, 'amcl') is None
    assert run.stopped == [old_parent, run.parent]


def test_default_parent_capacity_never_evicts_consumed_parent_history(run):
    run.owner = NativeMapEvidence(source=lambda: run.source, parent=lambda: run.parent,
        consumers=tuple(run.profiles.values()), clock=lambda: run.time, stop=run.stopped.append)
    parents = []
    for _ in range(64):
        run.parent = object()
        parents.append(run.parent)
        assert complete(run) is not None
    run.parent = object()
    assert run.owner.begin() is None
    assert run.parent in run.stopped
    for parent in parents:
        run.parent = parent
        assert run.owner.begin() is None


def test_explicit_transport_close_invalidates_cached_proof_for_all_future_parents(run):
    sample = complete(run)
    assert sample is not None
    run.owner.close()
    run.owner.close()
    assert run.stopped == [run.parent]
    assert not run.owner.valid(sample, run.parent, raw_source=run.source, now=run.time)
    run.parent = object()
    assert run.owner.begin() is None


@pytest.mark.parametrize('change', ['identical_delivery', 'new_owner', 'lifecycle'])
def test_equal_values_cannot_replace_captured_original_object_during_queries(run, change):
    round_ = run.owner.begin()
    a = issue(run, round_, 'amcl')
    assert run.owner.reply(a, run.profiles['amcl'].provider, reply(run, a))
    b = issue(run, round_, 'static_layer')
    value = reply(run, b)
    if change == 'identical_delivery':
        token = run.source.begin(20, 10)
        assert run.source.complete(token, GridContent('map', 2, 1, .05,
            (-1., 2., 0., 0., 0., 0., 1.), (0, 100), 20, 10))
    elif change == 'new_owner':
        run.source = raw(run.source._boot)
    else:
        run.source.lifecycle(False)
    assert not run.owner.reply(b, run.profiles['static_layer'].provider, value)
    assert run.stopped == [run.parent] and run.owner.sample(run.parent) is None
    assert run.owner.begin() is None


@pytest.mark.parametrize('field,value', [
    ('active', False), ('adopted', False), ('contract_version', 2), ('role', 'other'),
    ('node_fqn', '/wrong/amcl'), ('build_id', 'c'*64), ('config_digest', 'c'*64),
    ('grid_digest', 'c'*64), ('generation', 0), ('instance_id', bytes(16)),
    ('challenge', b'x'*16), ('frame_id', 'other'), ('width', 3), ('height', 2),
    ('resolution', .06), ('origin', (-1., 2., -0., 0., 0., 0., 1.)),
    ('source_stamp_ns', 21), ('map_load_time_ns', 11),
])
def test_negative_or_mismatched_original_reply_consumes_captured_parent(run, field, value):
    round_ = run.owner.begin()
    ticket = issue(run, round_, 'amcl')
    assert not run.owner.reply(ticket, run.profiles['amcl'].provider, reply(run, ticket, **{field: value}))
    assert run.stopped == [run.parent] and run.owner.begin() is None


def test_wrong_provider_and_duplicate_nonce_cannot_complete_queries(run):
    round_ = run.owner.begin()
    a = issue(run, round_, 'amcl')
    assert not run.owner.reply(a, object(), reply(run, a))
    assert run.stopped == [run.parent]


def test_nonce_reuse_across_roles_is_not_a_second_query(run):
    round_ = run.owner.begin()
    a = issue(run, round_, 'amcl')
    assert run.owner.issue(round_, 'static_layer', run.profiles['static_layer'].provider, a.nonce) is None
    assert run.stopped == [run.parent]


def test_replayed_completed_ticket_retires_successful_evidence(run):
    round_ = run.owner.begin()
    a = issue(run, round_, 'amcl')
    value = reply(run, a)
    assert run.owner.reply(a, run.profiles['amcl'].provider, value)
    b = issue(run, round_, 'static_layer')
    assert run.owner.reply(b, run.profiles['static_layer'].provider, reply(run, b))
    assert run.owner.sample(run.parent) is not None
    assert not run.owner.reply(a, run.profiles['amcl'].provider, value)
    assert run.owner.sample(run.parent) is None


def test_new_poll_does_not_extend_an_old_selected_sample(run):
    before = complete(run)
    run.time = 10.25
    after = complete(run)
    assert before is not after and before.tuple is after.tuple
    run.time = 10.51
    assert run.owner.valid(after, run.parent, raw_source=run.source, now=run.time)
    assert not run.owner.valid(before, run.parent, raw_source=run.source, now=run.time)
    assert not run.owner.valid(replace(after, expires_at=99.), run.parent,
        raw_source=run.source, now=run.time)


def test_a_gap_cannot_be_revived_by_later_same_tuple(run):
    assert complete(run) is not None
    run.time = 10.5
    assert run.owner.begin() is None
    run.time = 10.6
    assert run.owner.sample(run.parent) is None and run.owner.begin() is None
    assert run.stopped == [run.parent]


@pytest.mark.parametrize('mutation', ['reset_generation', 'regression', 'new_instance'])
def test_any_native_tuple_change_consumes_old_parent_even_same_map(run, mutation):
    assert complete(run) is not None
    run.time = 10.25
    round_ = run.owner.begin()
    a = issue(run, round_, 'amcl')
    changes = ({'generation': 2} if mutation == 'reset_generation' else
        {'generation': 0} if mutation == 'regression' else {'instance_id': b'z'*16})
    # A reset and full reapplication can finish between polls with no new CORE map callback.
    assert not run.owner.reply(a, run.profiles['amcl'].provider, reply(run, a, **changes))
    assert run.owner.sample(run.parent) is None and run.owner.begin() is None


@pytest.mark.parametrize('time', [10.251, 9.99, math.nan, math.inf, True])
def test_late_or_faulting_clock_never_grants_evidence(run, time):
    round_ = run.owner.begin()
    ticket = issue(run, round_, 'amcl')
    value = reply(run, ticket)
    run.time = time
    assert not run.owner.reply(ticket, run.profiles['amcl'].provider, value)
    assert run.stopped == [run.parent]


def test_late_callback_for_old_parent_cannot_stop_replacement(run):
    old = run.parent
    round_ = run.owner.begin()
    ticket = issue(run, round_, 'amcl')
    value = reply(run, ticket)
    run.parent = object()
    replacement = complete(run)
    assert replacement is not None
    assert not run.owner.reply(ticket, run.profiles['amcl'].provider, value)
    assert run.stopped == [old]
    assert run.owner.sample(run.parent) is replacement


def test_overlapping_rounds_and_unavailable_source_fail_closed(run):
    assert run.owner.begin() is not None
    assert run.owner.begin() is None and run.stopped == [run.parent]


def test_writer_predicate_does_not_acquire_original_source_lock(run):
    sample = complete(run)
    run.source._lock.acquire()
    try:
        assert run.owner.valid(sample, run.parent, raw_source=run.source, now=run.time)
    finally:
        run.source._lock.release()
    run.source.begin(20, 10)
    assert not run.owner.valid(sample, run.parent, raw_source=run.source, now=run.time)


def test_missing_original_cannot_be_repaired_for_the_same_consumed_parent(run):
    original = run.source
    run.source = None
    assert run.owner.begin() is None
    run.source = original
    assert run.owner.begin() is None and run.stopped == [run.parent]


def test_bounded_capture_copies_generated_array_shapes_before_owner_lock(run):
    from array import array
    round_ = run.owner.begin()
    ticket = issue(run, round_, 'amcl')
    value = reply(run, ticket)
    wire = NS(**value.__dict__)
    wire.challenge, wire.instance_id = array('B', wire.challenge), array('B', wire.instance_id)
    wire.origin = array('d', wire.origin)
    captured = NativeReply.capture(wire)
    wire.challenge[0] = 99
    wire.origin[0] = 99.
    assert captured.challenge == ticket.nonce and captured.origin == value.origin
    assert run.owner.reply(ticket, run.profiles['amcl'].provider, captured)


@pytest.mark.parametrize('field,value', [
    ('challenge', [1]*17), ('instance_id', [True]*16), ('origin', [0.]*8),
    ('reason', 'x'*65), ('reason', '\ud800'), ('role', 'x'*33), ('node_fqn', 'x'*257),
    ('active', 1), ('adopted', 1), ('generation', True), ('width', True),
    ('resolution', math.nan), ('origin', (0.,)*6 + (math.inf,)),
    ('source_stamp_ns', -1), ('map_load_time_ns', 2**64),
])
def test_malformed_native_wire_cannot_escape_bounded_capture(run, field, value):
    round_ = run.owner.begin()
    ticket = issue(run, round_, 'amcl')
    wire = NS(**reply(run, ticket).__dict__)
    setattr(wire, field, value)
    with pytest.raises(ValueError):
        NativeReply.capture(wire)


@pytest.mark.parametrize('phase', ['begin', 'issue', 'reply', 'sample'])
def test_source_callback_delay_is_inside_the_final_clock_bracket(run, phase):
    if phase in ('begin', 'sample'):
        assert complete(run) is not None
        delayed_time = 10.6
    else:
        round_ = run.owner.begin()
        ticket = issue(run, round_, 'amcl') if phase == 'reply' else None
        value = reply(run, ticket) if ticket is not None else None
        delayed_time = 10.3

    def delayed_source():
        run.time = delayed_time
        return run.source

    run.owner._source = delayed_source
    if phase == 'begin': assert run.owner.begin() is None
    elif phase == 'sample': assert run.owner.sample(run.parent) is None
    elif phase == 'issue': assert issue(run, round_, 'amcl') is None
    else: assert not run.owner.reply(ticket, run.profiles['amcl'].provider, value)
    assert run.stopped == [run.parent]


def test_reply_validation_delay_rechecks_query_deadline_before_publishing(run, monkeypatch):
    round_ = run.owner.begin()
    ticket = issue(run, round_, 'amcl')
    value = reply(run, ticket)
    original = NativeReply.matches

    def delayed(self, *args):
        run.time = 10.3
        return original(self, *args)

    monkeypatch.setattr(NativeReply, 'matches', delayed)
    assert not run.owner.reply(ticket, run.profiles['amcl'].provider, value)
    assert run.stopped == [run.parent]


def test_cloned_failure_ticket_cannot_consume_the_real_issued_round(run):
    round_ = run.owner.begin()
    ticket = issue(run, round_, 'amcl')
    assert not run.owner.fail(replace(ticket))
    assert not run.stopped
    assert run.owner.reply(ticket, run.profiles['amcl'].provider, reply(run, ticket))
    second = issue(run, round_, 'static_layer')
    assert run.owner.reply(second, run.profiles['static_layer'].provider, reply(run, second))
    assert run.owner.sample(run.parent) is not None
