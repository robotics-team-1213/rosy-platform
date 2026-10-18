"""Actual Fleet HTTP governance -> SIM session; owner transport/RGB remain HOST fixtures."""
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
import sqlite3

import pytest

from test_omx_policy_session import setup_session, CameraSnapshot
from test_policy_runtime_binding import runtime_methods, joint_message
from policy_chain_fixtures import approved_fleet
from rosy.execution.local.policy_journal import PolicyExecutionJournal
from rosy.execution.local.policy_lease import FleetLeaseConsumer, LeaseScope
from rosy.execution.local.policy_chain import SimPolicyChain


@contextmanager
def chain_setup(tmp_path, *, enabled=True):
    seed, driver, clock, _, _ = setup_session(tmp_path, camera=True)
    runtime = runtime_methods(seed, driver)
    policy = seed.policy
    with approved_fleet(tmp_path/'fleet', workcell_id=seed.owner.config.workcell_id,
            instance_id=seed.owner.config.instance_id, policy_revision=policy.recheck()['revision']) as fleet:
        scope = LeaseScope(seed.lease.identity, seed.lease.episode_id, seed.lease.policy_revision,
            seed.owner.session_id, fleet.window['window_id'], fleet.rig_revision,
            fleet.calibration_revision, fleet.scope)
        consumer = FleetLeaseConsumer(scope, request=fleet.device, monotonic=runtime.monotonic)
        rgb = bytes(range(12))
        def camera():
            return CameraSnapshot('front','cam-front','a'*64,(3,2,2), int(clock[0]*1e9), sha256(rgb).hexdigest())
        options = dict(policy=policy, runtime=runtime, fence=seed.fence, consumer=consumer,
            journal=PolicyExecutionJournal(tmp_path/'execution.sqlite3'), owner_identity=seed._identity,
            camera_current=lambda:(camera(),), capture=lambda:(rgb,camera()), principal='sim-sdk', enabled=enabled)
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
            fleet.admin('POST', fleet.base+'/windows/'+fleet.window['window_id']+'/close',
                        dict(operator_confirmed=True, reason='SIM revoke'))
        elif fault == 'confirmation':
            fleet.admin('POST', fleet.base+'/confirmations', dict(operator_confirmed=True,
                reason='owner_fault', policy_revision=original.policy_revision, evidence={'simulation':True}))
        elif fault == 'incident':
            fleet.admin('POST', fleet.base+'/incidents', dict(operator_confirmed=True, description='SIM incident'))
        else:
            fleet.server.close()
        with pytest.raises(PermissionError): chain.consumer.renew(chain.session)
        runtime._watchdog_tick()
        assert chain.session.hold_reason and chain.session.owner.state == 'hold'
        assert driver.handles[-1].cancel_calls == 1
        with pytest.raises(PermissionError): chain.consumer.acquire()
        assert not chain.consumer.authority(renewed)


def test_chain_refuses_owner_scope_substitution(tmp_path):
    with chain_setup(tmp_path, enabled=False) as (options, fleet):
        options['enabled'] = True
        scope = options['consumer'].scope
        options['consumer'] = FleetLeaseConsumer(replace(scope, owner_session_id='foreign-owner'),
            request=fleet.device, monotonic=options['runtime'].monotonic)
        with pytest.raises(ValueError): SimPolicyChain(**options)
        with sqlite3.connect(fleet.db) as db:
            assert db.execute('SELECT count(*) FROM fleet_policy_lease').fetchone()[0] == 0
