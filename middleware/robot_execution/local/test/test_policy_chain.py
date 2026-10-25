"""Actual Fleet HTTP governance -> SIM session; owner transport/RGB remain HOST fixtures."""
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from hashlib import sha256
import sqlite3
import threading
import time

import pytest

from test_omx_policy_session import setup_session, CameraSnapshot
from test_policy_runtime_binding import runtime_methods, joint_message
from policy_chain_fixtures import approved_fleet
from rosy.execution.local.policy_journal import PolicyExecutionJournal
from rosy.execution.local.policy_lease import FleetLeaseConsumer, LeaseScope
from rosy.execution.local.policy_chain import SimPolicyChain


def test_worker_renews_before_round_trip_cost_exhausts_current_lease():
    from types import SimpleNamespace
    clock, completed, waits = [.34], [], []
    class Stop:
        def is_set(self): return False
        def set(self): pass
        def wait(self, delay):
            waits.append(delay)
            clock[0] += delay
            return len(waits) > 1
    def renew(session):
        clock[0] += .54
        completed.append(clock[0])
    chain = object.__new__(SimPolicyChain)
    chain.session = SimpleNamespace(lease=SimpleNamespace(expires_at_ns=1_000_000_000),hold_reason='')
    chain.consumer = SimpleNamespace(max_duration_ns=1_000_000_000,monotonic=lambda:clock[0],
                                     renew=renew,close=lambda:None)
    chain._stop, chain._hold = Stop(), lambda:None
    chain._run()
    assert completed and completed[0] < 1., 'renewal must finish within the original one-second lease'


@contextmanager
def chain_setup(tmp_path, *, enabled=True, camera=True):
    seed, driver, clock, _, _ = setup_session(tmp_path, camera=camera)
    runtime = runtime_methods(seed, driver)
    policy = seed.policy
    with approved_fleet(tmp_path/'fleet', workcell_id=seed.owner.config.workcell_id,
            instance_id=seed.owner.config.instance_id, policy_revision=policy.recheck()['revision']) as fleet:
        scope = LeaseScope(seed.lease.identity, seed.lease.episode_id, seed.lease.policy_revision,
            seed.owner.session_id, fleet.window['window_id'], fleet.rig_revision,
            fleet.calibration_revision, fleet.scope)
        consumer = FleetLeaseConsumer(scope, request=fleet.device, monotonic=runtime.monotonic)
        rgb, top = bytes(range(12)), bytes(range(12, 24))
        def cameras():
            stamp = int(clock[0]*1e9)
            front = CameraSnapshot('front','cam-front','a'*64,(3,2,2), stamp, sha256(rgb).hexdigest())
            if camera != 2:
                return (front,)
            return front, CameraSnapshot('top','cam-top','b'*64,(3,2,2), stamp, sha256(top).hexdigest())
        def capture():
            snapshots = cameras()
            return nullcontext((rgb, snapshots[0]) if len(snapshots) == 1 else tuple(zip((rgb, top), snapshots)))
        options = dict(policy=policy, runtime=runtime, fence=seed.fence, consumer=consumer,
            journal=PolicyExecutionJournal(tmp_path/'execution.sqlite3'), owner_identity=seed._identity,
            camera_current=cameras, capture=capture, principal='sim-sdk',
            installed_rig_revision='sim-rig', enabled=enabled)
        if not enabled:
            yield options, fleet
        else:
            chain = SimPolicyChain(**options)
            try:
                runtime._on_joint_state(joint_message(runtime))
                yield chain, fleet, runtime, driver, clock
            finally:
                chain.close()


def test_chain_defaults_disabled_without_issuing_a_lease(tmp_path):
    with chain_setup(tmp_path, enabled=False) as (options, fleet):
        options.pop('enabled')
        with pytest.raises(PermissionError): SimPolicyChain(**options)
        with sqlite3.connect(fleet.db) as db:
            assert db.execute('SELECT count(*) FROM fleet_policy_lease').fetchone()[0] == 0


@pytest.mark.parametrize('fault', ['window','confirmation','incident','disconnect'])
def test_real_fleet_renewal_then_stop_cancels_exact_session_goal(tmp_path, fault):
    with chain_setup(tmp_path) as (chain, fleet, runtime, driver, clock):
        source = chain.port.observation('sim-sdk', chain.session.lease.policy_revision)
        result = chain.port.submit('sim-sdk', observation_id=source['observation_id'],
            policy_revision=source['policy_revision'], positions={'joint_1':.101,'joint_2':.001})
        assert result['accepted'] and driver.commands[-1].command_id == result['command_id']
        original = chain.session.lease
        clock[0] += .2
        runtime._on_joint_state(joint_message(runtime))
        renewed = chain.consumer.renew(chain.session)
        assert renewed.lease_id == original.lease_id and renewed.expires_at_ns > original.expires_at_ns
        if fault == 'window':
            fleet.operator('POST', fleet.base+'/windows/'+fleet.window['window_id']+'/close',
                        dict(operator_confirmed=True, reason='SIM revoke'))
        elif fault == 'confirmation':
            fleet.operator('POST', fleet.base+'/confirmations', dict(operator_confirmed=True,
                reason='owner_fault', policy_revision=original.policy_revision, evidence={'simulation':True}))
        elif fault == 'incident':
            fleet.operator('POST', fleet.base+'/incidents', dict(operator_confirmed=True, description='SIM incident'))
        else:
            fleet.server.close()
        with pytest.raises(PermissionError): chain.consumer.renew(chain.session)
        runtime._watchdog_tick()
        assert chain.session.hold_reason and chain.session.owner.state == 'hold'
        assert driver.handles[-1].cancel_calls == 1
        with pytest.raises(PermissionError): chain.consumer.acquire()
        assert not chain.consumer.authority(renewed)


def test_two_installed_cameras_chain_and_bind_both_frames(tmp_path):
    with chain_setup(tmp_path, camera=2) as (chain, fleet, runtime, driver, clock):
        source = chain.port.observation('sim-sdk', chain.session.lease.policy_revision)
        assert [c['name'] for c in source['cameras']] == ['front', 'top']
        result = chain.port.submit('sim-sdk', observation_id=source['observation_id'],
            policy_revision=source['policy_revision'], positions={'joint_1':.101,'joint_2':.001})
        assert result['accepted'] and driver.commands[-1].command_id == result['command_id']


def test_policy_without_installed_camera_is_refused_before_issuance(tmp_path):
    with chain_setup(tmp_path, enabled=False, camera=False) as (options, fleet):
        options['enabled'] = True
        with pytest.raises(ValueError): SimPolicyChain(**options)
        with sqlite3.connect(fleet.db) as db:
            assert db.execute('SELECT count(*) FROM fleet_policy_lease').fetchone()[0] == 0


@pytest.mark.parametrize('field', ['owner_session_id', 'rig_revision', 'calibration_revision'])
def test_chain_refuses_installed_scope_substitution_before_issuance(tmp_path, field):
    with chain_setup(tmp_path, enabled=False) as (options, fleet):
        options['enabled'] = True
        scope = options['consumer'].scope
        options['consumer'] = FleetLeaseConsumer(replace(scope, **{field:'foreign-binding'}),
            request=fleet.device, monotonic=options['runtime'].monotonic)
        with pytest.raises(ValueError): SimPolicyChain(**options)
        with sqlite3.connect(fleet.db) as db:
            assert db.execute('SELECT count(*) FROM fleet_policy_lease').fetchone()[0] == 0


def test_worker_closes_authority_after_actual_fleet_window_revoke(tmp_path):
    with chain_setup(tmp_path) as (chain, fleet, runtime, driver, clock):
        fleet.operator('POST', fleet.base+'/windows/'+fleet.window['window_id']+'/close',
                    dict(operator_confirmed=True, reason='SIM worker revoke'))
        chain.start()
        deadline = time.monotonic()+3
        while not chain.session.hold_reason and time.monotonic() < deadline:
            time.sleep(.01)
        runtime._watchdog_tick()  # This HOST fixture has no ROS executor to drive its original timer.
        assert chain.session.hold_reason and chain.session.owner.state == 'hold'


def test_close_reaches_owner_while_refresh_network_is_blocked(tmp_path):
    with chain_setup(tmp_path) as (chain, fleet, runtime, driver, clock):
        source = chain.port.observation('sim-sdk', chain.session.lease.policy_revision)
        assert chain.port.submit('sim-sdk', observation_id=source['observation_id'],
            policy_revision=source['policy_revision'], positions={'joint_1':.101,'joint_2':.001})['accepted']
        entered, release = threading.Event(), threading.Event()
        request = chain.consumer.request
        def stalled(*args):
            entered.set()
            assert release.wait(3), 'test did not release its own network fixture'
            return request(*args)
        chain.consumer.request = stalled
        chain.start()
        closer = None
        try:
            assert entered.wait(2)
            closer = threading.Thread(target=chain.close)
            closer.start()
            deadline = time.monotonic()+.5
            while not driver.handles[-1].cancel_calls and time.monotonic() < deadline:
                time.sleep(.005)
            assert driver.handles[-1].cancel_calls == 1 and not release.is_set()
        finally:
            release.set()
            if closer is not None:
                closer.join(3)
                assert not closer.is_alive()
        assert not chain.consumer.authority(chain.session.lease)


def test_close_persists_fence_before_waiting_on_trusted_identity_provider(tmp_path):
    with chain_setup(tmp_path) as (chain, fleet, runtime, driver, clock):
        entered, release = threading.Event(), threading.Event()
        identity = chain.session._identity
        def blocked_identity():
            entered.set()
            assert release.wait(3)
            return identity()
        chain.session._identity = blocked_identity
        def poll():
            try:
                chain.session.poll()
            except PermissionError:
                pass
        poller = threading.Thread(target=poll)
        closer = None
        poller.start()
        try:
            assert entered.wait(1)
            closer = threading.Thread(target=chain.close)
            closer.start()
            scope = chain.session.lease.identity
            deadline = time.monotonic()+.5
            while chain.session.fence.is_open(authority_epoch=scope.authority_epoch,
                    dispatch_generation=scope.dispatch_generation) and time.monotonic() < deadline:
                time.sleep(.005)
            assert not chain.session.fence.is_open(authority_epoch=scope.authority_epoch,
                                                   dispatch_generation=scope.dispatch_generation)
            assert not release.is_set()
        finally:
            release.set()
            poller.join(3)
            if closer is not None:
                closer.join(3)
                assert not closer.is_alive()
            assert not poller.is_alive()
