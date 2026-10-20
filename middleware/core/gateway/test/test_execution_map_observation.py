"""Original map callback -> native source owner; no Nav2 consumer ACK claim."""
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace as NS
from uuid import uuid4
import math

import pytest

from core_features.command._execution_budget import Budget, Pose
from core_features.command.manager import Twist
from test_native_execution_binding import unbound_robot as robot, wheels  # noqa: F401


def message(stamp=1):
    return NS(header=NS(frame_id='map', stamp=NS(sec=stamp, nanosec=0)),
        info=NS(width=2, height=2, resolution=.05, map_load_time=NS(sec=1, nanosec=0),
            origin=NS(position=NS(x=-1., y=-.5, z=0.), orientation=NS(x=0., y=0., z=0., w=1.))),
        data=[0, 100, -1, 50])


def receive(r, msg=None):
    from core.bridge.map_observation import receive_map
    return receive_map(NS(_svc=r.svc, _map_pose_lease=None), message() if msg is None else msg, warn=lambda _: None)


def next_parent(r):
    assert r.ledger._current.stop_request.requested
    assert r.ledger.read().state == 'STOPPED'  # Commit the asynchronous request before retirement.
    assert r.binding.fence.retire(r.ledger._current)
    budget = Budget(limits=r.limits, initial=Pose(1000000000, 1000000000, 'odom', '0', 0., 0.),
        before_mono=10., after_mono=10., now_utc=100., captured_utc=99.9,
        admit_until_utc=100.1, duration_s=10., path_m=10., rotation_rad=20., radius_m=5.)
    parent = r.binding.fence.admit(replace(r.identity, parent_id=uuid4()), budget)
    assert parent is not None
    return parent


def test_actual_original_map_is_frozen_full_digest_and_stops_captured_parent(robot):
    r = robot
    r.svc.state.set_map_id('saved-map')
    assert receive(r)
    receipt = r.binding.map_snapshot()
    assert receipt.robot_id == r.svc.identity.robot_id and receipt.boot_id == r.identity.boot_id
    assert len(receipt.digest) == 64 and set(receipt.digest) <= set('0123456789abcdef')
    assert receipt.frame == 'map' and (receipt.width, receipt.height, receipt.resolution) == (2, 2, .05)
    assert receipt.origin == (-1., -.5, 0., 0., 0., 0., 1.)
    assert receipt.stamp_ns == receipt.load_time_ns == 1000000000
    with pytest.raises(FrozenInstanceError): receipt.generation = 20
    assert r.svc.state.map_id == 'saved-map'  # Display ID is not map content authority.
    assert r.ledger.read().state == 'STOPPED' and wheels(r) == [Twist()]


@pytest.mark.parametrize('change', ['cell', 'dimensions', 'resolution', 'origin_x', 'origin_y', 'yaw'])
def test_same_display_id_cannot_hide_full_map_content_change(robot, change):
    r = robot
    r.svc.state.set_map_id('same-id')
    assert receive(r)
    first = r.binding.map_snapshot()
    m = message(2)
    if change == 'cell': m.data[-1] = 51
    elif change == 'dimensions': m.info.width, m.info.height = 4, 1
    elif change == 'resolution': m.info.resolution = .06
    elif change == 'origin_x': m.info.origin.position.x = -.9
    elif change == 'origin_y': m.info.origin.position.y = -.4
    elif change == 'yaw':
        m.info.origin.orientation.z, m.info.origin.orientation.w = math.sin(.1), math.cos(.1)
    assert receive(r, m)
    second = r.binding.map_snapshot()
    assert second.digest != first.digest and second.generation > first.generation
    assert r.svc.state.map_id == 'same-id'


def test_map_aba_advances_generation_and_identical_delivery_does_not(robot):
    r = robot
    assert receive(r)
    first = r.binding.map_snapshot()
    assert receive(r)
    assert r.binding.map_snapshot().generation == first.generation
    other = message(2)
    other.data[0] = 1
    assert receive(r, other)
    second = r.binding.map_snapshot()
    assert receive(r, message(3))
    third = r.binding.map_snapshot()
    assert third.digest == first.digest and first.generation < second.generation < third.generation


def test_render_input_and_returned_cache_cannot_mutate_original_evidence(robot):
    r = robot
    m = message()
    assert receive(r, m)
    original = r.binding.map_snapshot()
    m.data[0] = 77
    render = r.svc.maps.get_map()
    render['data'][0] = 88
    render['origin']['x'] = 123.
    assert r.binding.map_snapshot() == original
    r.svc.maps.set_map({**render, 'data': [1, 2, 3, 4]}, map_id='render-only')
    assert r.binding.map_snapshot() == original


@pytest.mark.parametrize('fault', ['frame', 'nan', 'zero_quaternion', 'tilt', 'lateral_origin',
    'cell_range', 'boolean_cell', 'length', 'dimensions', 'oversize', 'stamp_bool'])
def test_invalid_original_map_clears_source_and_cannot_be_corrected_same_header(robot, fault):
    r = robot
    assert receive(r)
    m = message(2)
    if fault == 'frame': m.header.frame_id = 'other/map'
    elif fault == 'nan': m.info.resolution = float('nan')
    elif fault == 'zero_quaternion': m.info.origin.orientation.w = 0.
    elif fault == 'tilt': m.info.origin.orientation.x, m.info.origin.orientation.w = .6, .8
    elif fault == 'lateral_origin': m.info.origin.position.z = .1
    elif fault == 'cell_range': m.data[0] = 101
    elif fault == 'boolean_cell': m.data[0] = True
    elif fault == 'length': m.data.pop()
    elif fault == 'dimensions': m.info.width = True
    elif fault == 'oversize': m.info.width, m.info.height = 4194305, 1
    elif fault == 'stamp_bool': m.header.stamp.sec = True
    assert not receive(r, m) and r.binding.map_snapshot() is None
    if fault != 'stamp_bool':
        assert not receive(r, message(2))  # A corrected payload is still the consumed original.
    assert receive(r, message(3))


def test_lifecycle_change_discards_old_ticket_and_latched_delivery_is_only_observation(robot):
    from core.bridge.map_observation import lifecycle
    r = robot
    assert receive(r)
    first = r.binding.map_snapshot()
    current_parent = next_parent(r)
    bridge = NS(_svc=r.svc, _map_pose_lease=None)
    lifecycle(bridge, False)
    assert current_parent.stop_request.requested and r.ledger.read().state == 'STOPPED'
    assert r.binding.map_snapshot() is None and not receive(r, message(2))
    lifecycle(bridge, True)
    assert r.binding.map_snapshot() is None
    assert receive(r)  # Static map may carry an old source timestamp; it is not a consumer ACK.
    current = r.binding.map_snapshot()
    assert current.digest == first.digest and current.lifecycle_epoch > first.lifecycle_epoch
    assert current.generation > first.generation


def test_invalid_first_original_map_requests_stop_before_validation(robot):
    r = robot
    m = message()
    m.data[0] = 101
    assert not receive(r, m)
    assert r.ledger.read().state == 'STOPPED'


def test_oversize_grid_is_refused_before_iterating_even_with_matching_length(robot):
    r = robot
    iterated = []
    class OversizeData:
        def __len__(self): return 4194305
        def __iter__(self):
            iterated.append(True)
            raise AssertionError('must not traverse an oversized grid')
    m = message()
    m.info.width, m.info.height, m.data = 4194305, 1, OversizeData()
    assert not receive(r, m) and not iterated


def test_lifecycle_old_cleanup_never_stops_a_replacement_parent(robot, monkeypatch):
    from core.bridge.map_observation import lifecycle
    r = robot
    owner = r.svc.nav._map_evidence
    original = owner.lifecycle
    replacement = []
    def interpose(active):
        replacement.append(next_parent(r))  # The captured old parent must already have STOP.
        original(active)
    monkeypatch.setattr(owner, 'lifecycle', interpose)
    lifecycle(NS(_svc=r.svc, _map_pose_lease=None), False)
    assert r.ledger._current is replacement[0] and r.ledger.read().state == 'ACTIVE'


def test_slow_old_hash_cannot_overwrite_new_source_or_stop_replacement_parent(robot, monkeypatch):
    from core_features.navigation import map_evidence
    r = robot
    digest = map_evidence.content_digest
    entered, replacement = [], []
    def interpose(content):
        if not entered:
            entered.append(True)
            assert receive(r, message(2))
            replacement.append(next_parent(r))
        return digest(content)
    monkeypatch.setattr(map_evidence, 'content_digest', interpose)
    assert not receive(r)
    assert r.binding.map_snapshot().stamp_ns == 2000000000
    assert r.ledger._current is replacement[0] and r.ledger.read().state == 'ACTIVE'


def test_ordinary_factory_preserves_render_path_without_fabricating_evidence(core_client):
    from core.bridge.map_observation import receive_map
    _, svc = core_client()
    assert svc.nav._map_evidence is None
    assert receive_map(NS(_svc=svc, _map_pose_lease=None), message(), warn=lambda _: None)
    assert svc.state.map_id.startswith('occupancy:') and svc.maps.get_map()['data'] == message().data


@pytest.mark.parametrize('operation', ['start', 'save', 'reset'])
def test_native_mapping_attempt_still_rejects_before_source_or_backend_mutation(robot, operation):
    from core_features.navigation.manager import NavigationError
    r = robot
    assert receive(r)
    original = r.binding.map_snapshot()
    with pytest.raises(NavigationError):
        if operation == 'start': r.svc.nav.start_mapping()
        elif operation == 'save': r.svc.nav.save_map()
        else: r.svc.nav.reset_mapping()
    assert r.binding.map_snapshot() == original and not r.svc.nav.mapping_active
