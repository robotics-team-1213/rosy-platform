"""ROS-free transport orchestration with real Futures; DDS is tested separately."""
from concurrent.futures import Future
from dataclasses import fields
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from core.bridge.native_map_adoption import NativeMapClients
from core_features.navigation.map_evidence import MapEvidence, GridContent
from core_features.navigation.native_map_reply import Consumer, NativeReply


class Client:
    def __init__(self):
        self.calls, self.removed = [], []
        self.ready, self.error = True, None

    def service_is_ready(self):
        return self.ready

    def call_async(self, request):
        if self.error:
            raise self.error
        future = Future()
        self.calls.append((request, future))
        return future

    def remove_pending_request(self, future):
        self.removed.append(future)


@pytest.fixture
def run():
    raw = MapEvidence(robot_id='unit', boot_id=uuid4())
    token = raw.begin(20, 10)
    assert raw.complete(token, GridContent('map', 2, 1, .05,
        (-1., 2., 0., 0., 0., 0., 1.), (0, 100), 20, 10))
    r = NS(raw=raw, time=10., parent=object(), stopped=[])
    r.clients = (Client(), Client())
    r.consumers = tuple(Consumer(role, '/unit/' + node, 'a'*64, 'b'*64, client)
        for role, node, client in zip(('amcl', 'static_layer'),
            ('amcl', 'global_costmap/global_costmap'), r.clients))
    r.transport = NativeMapClients(consumers=r.consumers, clients=r.clients, request_factory=NS,
        source=lambda: r.raw, parent=lambda: r.parent, clock=lambda: r.time, stop=r.stopped.append)
    return r


def finish(r, index, **changes):
    client, profile = r.clients[index], r.consumers[index]
    request, future = client.calls[-1]
    observation = r.raw.snapshot()
    response = NativeReply(1, bytes(request.challenge), bytes([index+1])*16, 1,
        True, True, 'adopted', profile.role, profile.node_fqn, profile.build_id,
        profile.config_digest, observation.digest, 'map', 2, 1, .05, observation.origin, 20, 10)
    message = NS(**{f.name: getattr(response, f.name) for f in fields(response)})
    for name, value in changes.items():
        setattr(message, name, value)
    future.set_result(message)


def test_pair_and_refresh_do_not_extend_selected_sample(run):
    r, transport = run, run.transport
    assert transport.ready() and transport.poll() and transport.pending
    finish(r, 0)
    assert transport.evidence.sample(r.parent) is None
    finish(r, 1)
    old = transport.evidence.sample(r.parent)
    assert old is not None and not transport.pending
    r.time = 10.25
    assert transport.poll()
    finish(r, 1)
    finish(r, 0)
    new = transport.evidence.sample(r.parent)
    assert new is not old and old.expires_at == 10.5 and new.expires_at == 10.75
    assert len({bytes(request.challenge) for c in r.clients for request, _ in c.calls}) == 4
    assert all(len(c.removed) == 2 for c in r.clients) and not r.stopped


@pytest.mark.parametrize('failure_index', [0, 1])
def test_close_attempts_every_owned_client_even_if_destroy_raises(run, failure_index):
    r = run
    attempted = []

    def destroy(client):
        attempted.append(client)
        if client is r.clients[failure_index]:
            raise RuntimeError('native destroy failed')
        return True

    r.transport._owned_node = NS(destroy_client=destroy)
    assert r.transport.poll() and r.transport.pending
    old_parent = r.parent
    with pytest.raises(RuntimeError, match='native destroy failed'):
        r.transport.close()
    assert attempted == list(r.clients)
    assert not r.transport.pending and all(c.calls[-1][1].cancelled() for c in r.clients)
    assert r.stopped == [old_parent]
    r.parent = object()
    assert not r.transport.poll()
    assert r.transport.evidence.sample(old_parent) is None
    assert r.transport.evidence.sample(r.parent) is None


def test_close_reports_a_native_destroy_refusal_after_attempting_all_clients(run):
    attempted = []

    def destroy(client):
        attempted.append(client)
        return client is run.clients[1]

    run.transport._owned_node = NS(destroy_client=destroy)
    with pytest.raises(RuntimeError, match='destroy'):
        run.transport.close()
    assert attempted == list(run.clients)
    assert not run.transport.poll()


@pytest.mark.parametrize('fault', ['unavailable', 'send', 'exception', 'cancel', 'shape', 'negative'])
def test_transport_fault_consumes_exact_parent_and_detaches_pair(run, fault):
    r = run
    if fault == 'unavailable':
        r.clients[1].ready = False
    elif fault == 'send':
        r.clients[1].error = RuntimeError('send failure')
    started = r.transport.poll()
    if fault == 'exception':
        r.clients[1].calls[-1][1].set_exception(RuntimeError('response failure'))
    elif fault == 'cancel':
        r.clients[1].calls[-1][1].cancel()
    elif fault == 'shape':
        r.clients[1].calls[-1][1].set_result(NS())
    elif fault == 'negative':
        finish(r, 1, adopted=False)
    assert started is (fault not in ('unavailable', 'send'))
    assert r.stopped == [r.parent] and r.transport.evidence.sample(r.parent) is None
    assert not r.transport.pending and not r.transport.poll()
    assert all(f.done() for c in r.clients for _, f in c.calls)


def test_overlap_retires_old_pending_pair_and_only_stops_old_parent(run):
    r = run
    assert r.transport.poll()
    # Real Future in RUNNING state cannot be cancelled. Its late completion must
    # retain the captured ticket, never acquire the replacement parent's ticket.
    late = r.clients[0].calls[-1][1]
    assert late.set_running_or_notify_cancel()
    old = r.parent
    r.parent, r.time = object(), 10.26
    assert r.transport.poll()
    assert r.stopped == [old]
    late.set_result(NS())
    assert r.stopped == [old]
    finish(r, 0)
    finish(r, 1)
    assert r.transport.evidence.sample(r.parent) is not None and r.stopped == [old]


def test_close_invalidates_completed_evidence_and_is_permanent(run):
    r = run
    assert r.transport.poll()
    finish(r, 0)
    finish(r, 1)
    sample = r.transport.evidence.sample(r.parent)
    assert sample is not None
    r.transport.close()
    r.transport.close()
    assert r.stopped == [r.parent] and not r.transport.pending
    assert not r.transport.evidence.valid(sample, r.parent, raw_source=r.raw, now=r.time)
    r.parent = object()
    assert not r.transport.poll() and not r.transport.ready()
    assert r.transport.evidence.begin() is None


def test_nonce_failure_consumes_parent_without_sending(run, monkeypatch):
    import core.bridge.native_map_adoption as adapter
    monkeypatch.setattr(adapter.secrets, 'token_bytes', lambda _: (_ for _ in ()).throw(OSError('entropy')))
    assert not run.transport.poll()
    assert run.stopped == [run.parent] and not run.transport.pending
    assert not any(c.calls for c in run.clients)
