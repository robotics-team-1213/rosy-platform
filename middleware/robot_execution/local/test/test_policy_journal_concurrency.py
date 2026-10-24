"""A paused durable intent must not monopolize observation, lease or stop admission."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
import threading

import pytest

from test_omx_policy_session import setup_session, candidate, JointStateSnapshot
from rosy.execution.local.policy_journal import PolicyExecutionJournal
from core_common.protocol.schemas import LocalStopRequest, StopRequestSource


@contextmanager
def paused_submission(tmp_path, *, short_lease=False):
    journal = PolicyExecutionJournal(tmp_path/'policy.sqlite3')
    session, client, clock, *_ = setup_session(tmp_path, execution_journal=journal)
    if short_lease:
        session._lease = replace(session.lease, expires_at_ns=10_020_000_000)
    entered, release = threading.Event(), threading.Event()
    original = journal.prepare
    commands, results, threads = [], {}, []

    def prepare(*args, **kwargs):
        original(*args, **kwargs)
        commands.append(args[2].command_id)
        entered.set()
        if not release.wait(10):
            raise TimeoutError('test did not release durable-intent barrier')

    def launch(name, operation):
        done = threading.Event()
        def run():
            try:
                results[name] = operation()
            except Exception as error:
                results[name] = error
            finally:
                done.set()
        thread = threading.Thread(target=run, daemon=True)
        threads.append(thread)
        thread.start()
        return done

    journal.prepare = prepare
    first = launch('first', lambda: session.submit(candidate(session)))
    try:
        assert entered.wait(5), results
        yield SimpleNamespace(session=session, client=client, clock=clock, journal=journal,
                              commands=commands, results=results, release=release,
                              first=first, launch=launch)
    finally:
        release.set()
        for thread in threads:
            thread.join(5)
        assert not any(thread.is_alive() for thread in threads), 'admission lock deadlock'


@pytest.mark.parametrize('operation', ['renew', 'poll', 'observe'])
def test_journal_write_allows_current_session_services(tmp_path, operation):
    with paused_submission(tmp_path) as run:
        session = run.session
        def service():
            if operation == 'renew':
                session.renew(replace(session.lease, expires_at_ns=10_950_000_000))
            elif operation == 'poll':
                session.poll()
            else:
                session.observe(JointStateSnapshot({'joint_1': .1, 'joint_2': 0.}, 11, 10., 'cal-7'))
        done = run.launch('service', service)
        assert done.wait(2), f'{operation} blocked on durable-intent I/O'
        assert run.results['service'] is None, run.results
        assert not run.client.commands and not run.first.is_set()
        run.release.set()
        assert run.first.wait(5)
        assert run.results['first'].accepted, run.results
        intent = run.journal.read(run.commands[0])['intent']
        assert intent['lease']['expires_at_ns'] == 10_900_000_000
    assert len(run.client.commands) == 1


def test_stop_can_close_while_intent_waits_and_prevents_transport(tmp_path):
    with paused_submission(tmp_path) as run:
        session = run.session
        identity = session.lease.identity
        def stop():
            session.fence.trip(LocalStopRequest(workcell_id=identity.workcell_id,
                instance_id=identity.instance_id, authority_epoch=identity.authority_epoch,
                dispatch_generation=identity.dispatch_generation, reason='operator_stop',
                requested_at=datetime.now(timezone.utc)), source=StopRequestSource.OPERATOR_LOCAL)
        done = run.launch('stop', stop)
        assert done.wait(2), 'local stop blocked on durable-intent I/O'
        assert not isinstance(run.results['stop'], Exception)
        assert not session.fence.is_open(authority_epoch=2, dispatch_generation=7)
        run.release.set()
        assert run.first.wait(5)
        assert isinstance(run.results['first'], PermissionError)
        assert session.hold_reason and not run.client.commands
        assert run.journal.read(run.commands[0])['driver_goal_id'] is None


def test_renewed_live_lease_never_resurrects_expired_recorded_grant(tmp_path):
    with paused_submission(tmp_path, short_lease=True) as run:
        def renew():
            run.clock[0] = 10.01
            run.session.renew(replace(run.session.lease, issued_at_ns=10_010_000_000,
                                      expires_at_ns=11_000_000_000))
        done = run.launch('renew', renew)
        assert done.wait(2), 'renewal blocked on durable-intent I/O'
        assert run.results['renew'] is None, run.results
        run.clock[0] = 10.03
        run.release.set()
        assert run.first.wait(5)
        assert isinstance(run.results['first'], PermissionError)
        assert run.session.hold_reason == 'policy_lease_expired_or_invalid'
        assert run.session.lease.expires_at_ns == 11_000_000_000
        assert not run.client.commands
        intent = run.journal.read(run.commands[0])['intent']
        assert intent['lease']['expires_at_ns'] == 10_020_000_000


def test_pending_submit_cannot_be_overtaken_or_duplicated(tmp_path):
    with paused_submission(tmp_path) as run:
        attempted = threading.Event()
        def second():
            attempted.set()
            return run.session.submit(candidate(run.session))
        second_done = run.launch('second', second)
        assert attempted.wait(2)
        assert not second_done.wait(.1)
        assert len(run.commands) == 1 and not run.client.commands
        run.release.set()
        assert run.first.wait(5) and second_done.wait(5)
        assert run.results['first'].accepted
        assert isinstance(run.results['second'], PermissionError)
    assert len(run.commands) == len(run.client.commands) == 1
