"""Test composition only: synthetic grant/model/server, actual local Action API."""
import json
import time
from dataclasses import replace
from datetime import datetime, timezone

from test_omx_action_api import _grant
from omx_adapter.action_runner import ActionRunner, DriverSubmission, parse_action_grant
from omx_adapter.action_store import ActionStore
from omx_adapter.action_api import ActionApi
from omx_adapter.journal_identity import journal_identity
from rosy.contracts.skill import AttemptIdentity
from rosy.execution.local.policy_episode import publish
from test_omx_policy_session import candidate


def trace(stage):
    print('NATIVE_CHAIN_PHASE '+json.dumps(dict(stage=stage,
        monotonic=time.monotonic(),utc=datetime.now(timezone.utc).isoformat())),flush=True)


class SessionSubmissionFence:
    """Test composition: preserve the session -> actual stop lock order."""

    def __init__(self, session):
        self.session = session

    def is_open(self, **scope):
        # Delegate the final owner check to the same genuine stop fence.
        with self.session._lock:
            return self.session.fence.is_open(**scope)

    def run_if_open(self, **scope):
        # Durable preparation precedes this boundary, allowing observations.
        with self.session._lock:
            return self.session.fence.run_if_open(**scope)


def submit_parent(session,journal,root):
    trace('parent_setup_begin')
    cfg=session.owner.config
    store=ActionStore(root/'owner.sqlite3')
    identity=journal_identity(store.path)  # Owner initialization, never verifier minting.
    commands=[]
    class Driver:
        def submit(self,_grant):
            assert store.get_action('action')['state']=='SUBMITTING'
            # Capture the actual accepted observation after parent setup, not
            # before SQLite initialization/import work consumes its age budget.
            state=None
            phase='capture_observation'
            begin=session._clock()
            stages=[dict(phase=phase,monotonic=begin)]
            try:
                state,_=session.capture_observation()
                phase='candidate'
                stages.append(dict(phase=phase,monotonic=session._clock()))
                action_candidate=candidate(session,sequence=state.sequence,
                    observed_at_ns=int(state.received_at*1e9),
                    produced_at_ns=int(session._clock()*1e9))
                phase='session_submit'
                stages.append(dict(phase=phase,monotonic=session._clock()))
                result=session.submit(action_candidate)
                assert result.accepted, result
            except Exception as exc:
                # ActionRunner correctly preserves UNKNOWN on driver errors.
                # Keep that original error, rather than masking it with a later
                # commands[0] IndexError or inferring success from callbacks.
                (root/'driver-submit-error.json').write_text(json.dumps(dict(
                    exception_type=type(exc).__name__,exception=str(exc),
                    hold=session.hold_reason,
                    phase=phase,stages=stages,
                    observation_received_at=state.received_at if state is not None else None,
                    failed_at_monotonic=session._clock()),indent=2),encoding='utf-8')
                raise
            commands.append(result.command_id)
            # Transport submission is not server acceptance. Preserve UNKNOWN
            # until actual callbacks establish UUID and terminal result, and
            # release the stop/session serializers so observations can arrive.
            return DriverSubmission(None,None)
        def cancel(self,_action):
            raise AssertionError('native fixture cancellation belongs to existing runtime/session')
    runner=ActionRunner(store,Driver(),workcell_id=cfg.workcell_id,instance_id=cfg.instance_id,
        principal_for_peer=lambda uid:'isolated-fleet-fixture',allowed_peer_uids={1001},
        current_fence=lambda epoch,generation:(epoch,generation)==(2,7),
        capability_current=lambda _:True,submission_fence=SessionSubmissionFence(session),enabled=True)
    api=ActionApi(runner,identity={'journal_id':identity})
    trace('parent_setup_complete')
    grant=parse_action_grant(_grant(mission_id='mission',step_id='step',action_id='action',
        attempt_id='attempt',workcell_id=cfg.workcell_id,instance_id=cfg.instance_id,dispatch_generation=7))
    names=('mission_id','step_id','action_id','attempt_id','workcell_id','instance_id',
           'request_digest','authority_epoch','dispatch_generation')
    session._lease=replace(session.lease,identity=AttemptIdentity(*(getattr(grant,name) for name in names)))
    # Record the guard's own clock sample and accepted observation stamp. Never
    # refresh or redeliver a snapshot to make the native test pass.
    freshness=[]
    original_fresh=session._fresh
    def observed_fresh(doc,now,cameras):
        snapshot=session._snapshot
        freshness.append(dict(now_ns=now,
            received_at=snapshot.received_at if snapshot is not None else None,
            sequence=snapshot.sequence if snapshot is not None else None,
            max_age_ns=doc['timing']['max_observation_age_ns']))
        return original_fresh(doc,now,cameras)
    session._fresh=observed_fresh
    # Test composition follows the session -> stop-fence order also used by
    # the runtime watchdog. Taking the runner fence first would deadlock it.
    try:
        trace('runner_submit_begin')
        receipt=runner.submit(grant,peer_uid=1001)
    finally:
        session._fresh=original_fresh
        (root/'guard-freshness-samples.json').write_text(
            json.dumps(freshness,indent=2),encoding='utf-8')
    trace('runner_submit_complete')
    assert receipt['state']=='UNKNOWN' and receipt['driver_goal_id'] is None, (receipt,session.hold_reason,commands)
    initial=api.dispatch(dict(version=2,operation='GetAction',action_id='action'),peer_uid=1001)
    assert initial['receipt']['state']=='UNKNOWN' and initial['receipt']['driver_goal_id'] is None
    (root/'initial-owner-readback.json').write_bytes(api._encode(initial))
    assert len(commands)==1, (
        'native submission did not return accepted; retain UNKNOWN',
        json.loads((root/'driver-submit-error.json').read_text())
        if (root/'driver-submit-error.json').exists() else None,
        receipt,session.hold_reason)
    parent=runner._policy_parent_for_validated_grant(grant,peer_uid=1001)
    trace('parent_capability_complete')
    deadline=time.monotonic()+3
    record=journal.read(commands[0])
    while record['driver_goal_id'] is None:
        assert time.monotonic()<deadline,'actual native goal acceptance timeout'
        time.sleep(.005);record=journal.read(commands[0])
    assert record['driver_goal_id']!=commands[0]
    parent.validate()
    # This is historical native readback, not a second submit/ACCEPTED grant.
    # Runtime submit and watchdog guards remain active; no stale/HOLD is erased.
    trace('native_acceptance_observed')
    return commands[0],runner,api,parent


def export_parent(root,journal,command,runner,api,parent,*,revoke):
    trace('terminal_record_begin')
    record=journal.read(command)
    terminal=record['events'][-1]
    runner.record_terminal('action','attempt',driver_goal_id=record['driver_goal_id'],
        outcome='FAILED' if revoke else 'SUCCEEDED',result_source='isolated_native_ros_callback',
        result_observed_at=datetime.now(timezone.utc).isoformat(),
        result={'status':terminal['status'],'result_code':terminal['result_code']},peer_uid=1001)
    trace('publication_begin')
    try:
        episode=publish(parent,api,journal,command,root/'episode')
    finally:
        trace('publication_return_or_error')
    from importlib.util import module_from_spec,spec_from_file_location
    from test_omx_policy_session import ROOT
    spec=spec_from_file_location('native_chain_fleet_join',ROOT/'learning/registry/policy/fleet_join.py')
    module=module_from_spec(spec);spec.loader.exec_module(module)
    fleet=module.export(root/'episode/manifest.json',root/'episode/owner-receipts/000000.json',root/'fleet.json')
    assert fleet['status']=='matched' and fleet['policy_revision']==episode['revisions']['policy']
    assert fleet['receipt']['driver_goal_id']==record['driver_goal_id']
    assert fleet['binding']['journal_id']==api.identity['journal_id']
    assert episode['status']=='incomplete' and episode['outcome']['task']=='unknown'
    assert episode['outcome']['action']==('failed' if revoke else 'succeeded')
    proof=dict(episode_revision=episode['revision'],fleet_revision=fleet['revision'],
        command_id=command,driver_goal_id=record['driver_goal_id'],journal_id=api.identity['journal_id'],
        receipt_state=fleet['receipt']['state'],native_status=terminal['status'],
        initial_receipt_state='UNKNOWN',initial_driver_goal_id=None,
        initially_server_acknowledged=False,
        task_outcome='unknown',model_inference_verified=False,physical_acceptance=False,
        native_transport_verified=True,fleet_receiver_verified=False)
    (root/'chain-receipt.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    return proof
