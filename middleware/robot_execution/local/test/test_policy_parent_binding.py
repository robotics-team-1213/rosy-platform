"""HOST parent correlation; synthetic driver/model/authority, not Fleet execution."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from test_policy_runtime_binding import attached
from test_omx_policy_session import candidate
from test_omx_action_api import _grant
from omx_adapter.action_runner import ActionRunner, DriverSubmission, parse_action_grant
from omx_adapter.action_store import ActionStore
from omx_adapter.ros_goal_contract import RosGoalEvent
from rosy.contracts.skill import AttemptIdentity


def setup_parent(tmp_path, *, admit=True):
    session, runtime, client, _, _, journal, _ = attached(tmp_path)
    cfg = session.owner.config
    grant = parse_action_grant(_grant(
        mission_id='mission', step_id='step', action_id='action', attempt_id='attempt',
        workcell_id=cfg.workcell_id, instance_id=cfg.instance_id, dispatch_generation=7))
    names = ('mission_id', 'step_id', 'action_id', 'attempt_id', 'workcell_id',
             'instance_id', 'request_digest', 'authority_epoch', 'dispatch_generation')
    session._lease = replace(session.lease, identity=AttemptIdentity(
        *(getattr(grant, name) for name in names)))
    goal = str(uuid4())
    commands = []
    class Driver:
        def submit(self, _grant):
            # Parent SUBMITTING is persisted before synthetic policy dispatch.
            assert store.get_action('action')['state'] == 'SUBMITTING'
            result = session.submit(candidate(session))
            commands.append(result.command_id)
            runtime._dispatch_goal_event(RosGoalEvent(
                'GOAL_ACCEPTED', result.command_id, None, goal, 10., 1))
            return DriverSubmission(True, goal)
        def cancel(self, action):
            raise AssertionError('read-only correlation must never cancel')
    store = ActionStore(tmp_path / 'owner.sqlite3')
    driver = Driver()
    runner = ActionRunner(store, driver, workcell_id=cfg.workcell_id, instance_id=cfg.instance_id,
        principal_for_peer=lambda uid: 'fleet-1', allowed_peer_uids={1001},
        current_fence=lambda epoch, gen: (epoch, gen) == (2, 7),
        capability_current=lambda _: True, submission_fence=session.fence, enabled=True)
    if admit:
        runner.submit(grant, peer_uid=1001)
    return runner, grant, journal, commands, goal, runtime, client


def mint(runner, grant):
    factory = getattr(runner, '_policy_parent_for_validated_grant', None)
    assert callable(factory), 'missing genuine runner-scoped policy parent capability'
    return factory(grant, peer_uid=1001)


def capture(parent, journal, command, receipt):
    from rosy.execution.local.policy_parent import correlate_parent
    return correlate_parent(parent, journal, command, json.dumps(receipt).encode())


def test_admitted_parent_exact_source_goal_and_receipt_correlate_without_permission(tmp_path):
    runner, grant, journal, commands, goal, _, client = setup_parent(tmp_path)
    parent = mint(runner, grant)
    receipt = runner.get('action', peer_uid=1001)
    before = runner.store.history('action')
    result = capture(parent, journal, commands[0], receipt)
    assert result['driver_goal_id'] == goal != commands[0]
    assert result['policy_revision'] == journal.read(commands[0])['intent']['policy_revision']
    assert result['request_digest'] == grant.request_digest
    assert result['receipt_sha256'] == __import__('hashlib').sha256(json.dumps(receipt).encode()).hexdigest()
    assert result['execution_authorized'] is False
    assert result['episode_fleet_qualified'] is False
    assert result['task_outcome'] == 'unknown'
    assert 'journal_id' not in result  # Private snapshot hash is not a wire journal ID.
    assert runner.store.history('action') == before and len(client.commands) == 1


def test_matching_lease_and_receipt_text_without_admitted_parent_reject(tmp_path):
    runner, grant, _, _, _, _, client = setup_parent(tmp_path, admit=False)
    with pytest.raises(PermissionError):
        mint(runner, grant)
    assert not client.commands and runner.store.get_action('action') is None


@pytest.mark.parametrize('mutation', ['state', 'watermark', 'goal', 'time', 'bool'])
def test_forged_current_d18_receipt_rejects_even_with_valid_identity(tmp_path, mutation):
    runner, grant, journal, commands, _, _, _ = setup_parent(tmp_path)
    parent = mint(runner, grant)
    receipt = runner.get('action', peer_uid=1001)
    if mutation == 'state': receipt['state'] = 'SUCCEEDED'
    elif mutation == 'watermark': receipt['journal_event_id'] += 1
    elif mutation == 'goal': receipt['driver_goal_id'] = commands[0]
    elif mutation == 'time': receipt['observed_at'] = datetime.now(timezone.utc).isoformat()
    else: receipt['created'] = 0
    with pytest.raises((ValueError, PermissionError)):
        capture(parent, journal, commands[0], receipt)


@pytest.mark.parametrize('mutation', ['peer', 'disabled', 'expired', 'fence', 'config', 'digest'])
def test_parent_capability_admission_preserves_actual_fleet_checks(tmp_path, mutation):
    runner, grant, *_ = setup_parent(tmp_path)
    if mutation == 'peer': runner.allowed_peer_uids = frozenset()
    elif mutation == 'disabled': runner.enabled = False
    elif mutation == 'expired': runner.now = lambda: grant.expires_at + timedelta(seconds=1)
    elif mutation == 'fence': runner.current_fence = lambda *_: False
    elif mutation == 'config': runner.capability_current = lambda _: False
    else: grant = grant.model_copy(update={'request_digest': 'b' * 64})
    with pytest.raises(PermissionError): mint(runner, grant)


def test_same_minted_parent_can_capture_terminal_but_no_retroactive_mint(tmp_path):
    runner, grant, journal, commands, goal, runtime, _ = setup_parent(tmp_path)
    parent = mint(runner, grant)
    runtime._dispatch_goal_event(RosGoalEvent(
        'TERMINAL_RESULT', commands[0], None, goal, 10.01, 2, status=4, result_code=0))
    receipt = runner.record_terminal('action', 'attempt', driver_goal_id=goal,
        outcome='SUCCEEDED', result_source='host_fixture',
        result_observed_at=datetime.now(timezone.utc).isoformat(), result={}, peer_uid=1001)
    result = capture(parent, journal, commands[0], receipt)
    assert result['action_state'] == 'SUCCEEDED' and result['task_outcome'] == 'unknown'
    with pytest.raises(PermissionError): mint(runner, grant)


@pytest.mark.parametrize('mutation', ['revoked', 'parent_changed', 'source_corrupt', 'identity'])
def test_changes_during_capture_reject_and_preserve_unbound_native_facts(tmp_path, monkeypatch, mutation):
    runner, grant, journal, commands, goal, _, _ = setup_parent(tmp_path)
    parent = mint(runner, grant)
    receipt = runner.get('action', peer_uid=1001)
    old = journal.read_source
    def changed_source(revision):
        source = old(revision)
        if mutation == 'revoked': runner.current_fence = lambda *_: False
        elif mutation == 'parent_changed': runner.store.hold_action('action', 'attempt', reason='changed')
        elif mutation == 'source_corrupt': source['payloads']['policy/model.bin'] = b'changed'
        else:
            # An internally re-sealed lease with another attempt remains unbound.
            with journal._connect() as db:
                payload = journal.read(commands[0])['intent']
                payload['lease']['identity']['attempt_id'] = 'other'
                db.execute('UPDATE policy_commands SET intent=? WHERE command_id=?',
                           (json.dumps(payload), commands[0]))
        return source
    monkeypatch.setattr(journal, 'read_source', changed_source)
    with pytest.raises((ValueError, PermissionError)):
        capture(parent, journal, commands[0], receipt)
    assert journal.read(commands[0])['driver_goal_id'] == goal


def test_parent_capability_is_not_serializable_or_reusable_with_replaced_store(tmp_path):
    runner, grant, journal, commands, _, _, _ = setup_parent(tmp_path)
    parent = mint(runner, grant)
    import pickle
    with pytest.raises(TypeError): pickle.dumps(parent)
    receipt = runner.get('action', peer_uid=1001)
    runner.store = ActionStore(tmp_path / 'other.sqlite3')
    with pytest.raises(PermissionError):
        capture(parent, journal, commands[0], receipt)


def test_directly_constructed_matching_snapshot_is_not_a_minted_capability(tmp_path):
    runner, _, journal, commands, _, _, _ = setup_parent(tmp_path)
    from omx_adapter.policy_parent import _ParentCapability
    receipt = runner.get('action', peer_uid=1001)
    with pytest.raises(PermissionError):
        fabricated = _ParentCapability(lambda: runner.store.attempt_snapshot('action', 'attempt'))
        capture(fabricated, journal, commands[0], receipt)


def test_resealed_source_with_wrong_original_policy_manifest_rejects(tmp_path):
    import hashlib
    runner, grant, journal, commands, _, _, _ = setup_parent(tmp_path)
    parent = mint(runner, grant)
    intent = journal.read(commands[0])['intent']
    source = journal.read_source(intent['source_revision'])
    path = 'policy/policy-artifact.json'
    source['payloads'][path] = b'{}'
    for ref in source['header']['files']:
        if ref['path'] == path:
            ref.update(bytes=2, sha256=hashlib.sha256(b'{}').hexdigest())
    revision = journal.store_source(source['header'], source['payloads'])
    intent['source_revision'] = revision
    with journal._connect() as db:
        db.execute('UPDATE policy_commands SET intent=? WHERE command_id=?',
                   (json.dumps(intent), commands[0]))
    with pytest.raises(ValueError):
        capture(parent, journal, commands[0], runner.get('action', peer_uid=1001))


def test_parent_snapshot_is_one_wal_revision_during_other_store_update(tmp_path, monkeypatch):
    runner, *_ = setup_parent(tmp_path)
    other = ActionStore(runner.store.path)
    connect = runner.store._connect
    fired = []
    def traced():
        db = connect()
        def interleave(sql):
            if 'SELECT * FROM omx_action_events' in sql and not fired:
                fired.append(True)
                other.hold_action('action', 'attempt', reason='other-store')
        db.set_trace_callback(interleave)
        return db
    monkeypatch.setattr(runner.store, '_connect', traced)
    snapshot = runner.store.attempt_snapshot('action', 'attempt')
    assert fired and snapshot['action']['state'] == 'ACCEPTED'
    assert snapshot['events'][-1]['state'] == 'ACCEPTED'
    assert other.get_action('action')['state'] == 'HOLD'


@pytest.mark.parametrize('mutation', ['source_payload', 'expiry'])
def test_final_native_read_cannot_hide_source_corruption_or_expiry(tmp_path, monkeypatch, mutation):
    runner, grant, journal, commands, _, _, _ = setup_parent(tmp_path)
    parent = mint(runner, grant)
    receipt = runner.get('action', peer_uid=1001)
    read, calls = journal.read, []
    def slow_read(command):
        facts = read(command)
        calls.append(command)
        if len(calls) == 2:
            if mutation == 'expiry':
                runner.now = lambda: grant.expires_at + timedelta(seconds=1)
            else:
                with journal._connect() as db:
                    db.execute('UPDATE policy_source_files SET payload=? WHERE path=?',
                               (b'corrupt', 'policy/model.bin'))
        return facts
    monkeypatch.setattr(journal, 'read', slow_read)
    with pytest.raises((ValueError, PermissionError)):
        capture(parent, journal, commands[0], receipt)
    assert len(calls) == 2


def test_resealed_normalization_binding_must_match_original_manifest(tmp_path):
    import hashlib
    runner, grant, journal, commands, _, _, _ = setup_parent(tmp_path)
    parent = mint(runner, grant)
    intent = journal.read(commands[0])['intent']
    source = journal.read_source(intent['source_revision'])
    path = 'installed/binding.json'
    binding = json.loads(source['payloads'][path])
    binding['normalization_sha256'] = 'b' * 64
    raw = json.dumps(binding).encode()
    source['payloads'][path] = raw
    for ref in source['header']['files']:
        if ref['path'] == path:
            ref.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    intent['source_revision'] = journal.store_source(source['header'], source['payloads'])
    with journal._connect() as db:
        db.execute('UPDATE policy_commands SET intent=? WHERE command_id=?',
                   (json.dumps(intent), commands[0]))
    with pytest.raises(ValueError):
        capture(parent, journal, commands[0], runner.get('action', peer_uid=1001))


@pytest.mark.parametrize('mutation', ['lease', 'episode', 'sequence', 'positions', 'owner', 'names'])
def test_rewritten_intent_must_preserve_full_candidate_command_scope(tmp_path, mutation):
    runner, grant, journal, commands, _, _, _ = setup_parent(tmp_path)
    parent = mint(runner, grant)
    intent = journal.read(commands[0])['intent']
    if mutation == 'lease': intent['candidate']['lease_id'] = 'other'
    elif mutation == 'episode': intent['candidate']['episode_id'] = 'other'
    elif mutation == 'sequence': intent['candidate']['sequence'] += 1
    elif mutation == 'positions': intent['candidate']['positions'][0] += .01
    elif mutation == 'owner': intent['command']['owner'] = 'moveit'
    else: intent['command']['joint_names'].reverse()
    with journal._connect() as db:
        db.execute('UPDATE policy_commands SET intent=? WHERE command_id=?',
                   (json.dumps(intent), commands[0]))
    with pytest.raises(ValueError):
        capture(parent, journal, commands[0], runner.get('action', peer_uid=1001))


def test_restart_does_not_renew_minted_parent_or_lose_native_goal(tmp_path):
    runner, grant, journal, commands, goal, _, _ = setup_parent(tmp_path)
    parent = mint(runner, grant)
    assert runner.store.recover_after_restart() == ['action']
    with pytest.raises(PermissionError): mint(runner, grant)
    with pytest.raises(PermissionError):
        capture(parent, journal, commands[0], runner.get('action', peer_uid=1001))
    assert journal.read(commands[0])['driver_goal_id'] == goal


def test_last_capability_provider_cannot_expire_grant_after_clock_check(tmp_path, monkeypatch):
    runner, grant, journal, commands, _, _, _ = setup_parent(tmp_path)
    current, armed = [grant.issued_at + timedelta(seconds=1)], [False]
    runner.now = lambda: current[0]
    def provider(_):
        if armed[0]: current[0] = grant.expires_at + timedelta(seconds=1)
        return True
    runner.capability_current = provider
    parent = mint(runner, grant)
    validate = parent.validate
    def final_validate():
        armed[0] = True
        validate()
    monkeypatch.setattr(parent, 'validate', final_validate)
    with pytest.raises(PermissionError):
        capture(parent, journal, commands[0], runner.get('action', peer_uid=1001))
