"""Actual DDS clients against synthetic services; no native adoption or writer proof."""
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from interfaces.srv import MapAdoption

from core.bridge.native_map_adoption import NativeMapClients
from core_features.navigation.map_evidence import MapEvidence, GridContent
from core_features.navigation.native_map_reply import Consumer


def pump(executor, predicate, seconds=8.):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        executor.spin_once(timeout_sec=.02)
    assert predicate(), 'bounded DDS wait expired'


def main():
    import core.bridge.native_map_adoption as adapter
    assert Path(adapter.__file__).resolve() == Path(
        'middleware/core/gateway/core/bridge/native_map_adoption.py').resolve()
    rclpy.init()
    executor = SingleThreadedExecutor()
    namespace = '/wire_' + uuid4().hex
    client_node = rclpy.create_node('core_client', namespace=namespace)
    server_node = rclpy.create_node('synthetic_consumers', namespace=namespace)
    executor.add_node(client_node)
    executor.add_node(server_node)
    raw = MapEvidence(robot_id='wire', boot_id=uuid4())
    token = raw.begin(20, 10)
    assert raw.complete(token, GridContent('map', 2, 1, .05,
        (-1., 2., 0., 0., 0., 0., 1.), (0, 100), 20, 10))
    observation = raw.snapshot()
    state = NS(time=10., parent=object(), stopped=[], queries=[], negative=False)
    profiles = tuple(Consumer(role, namespace + '/' + node, 'a'*64, 'b'*64, object())
        for role, node in [('amcl', 'amcl'), ('static_layer', 'global_costmap/global_costmap')])
    endpoints = (namespace + '/amcl/map_adoption', namespace + '/global_costmap/static_layer/map_adoption')

    def serve(role):
        profile = next(p for p in profiles if p.role == role)
        def callback(request, response):
            state.queries.append((role, bytes(request.challenge)))
            response.contract_version = 1
            response.challenge = request.challenge
            response.instance_id = [1 if role == 'amcl' else 2]*16
            response.generation = 1
            response.active, response.adopted = True, not state.negative
            response.reason = 'adopted' if not state.negative else 'synthetic_closed'
            response.role, response.node_fqn = role, profile.node_fqn
            response.build_id, response.config_digest = profile.build_id, profile.config_digest
            response.grid_digest, response.frame_id = observation.digest, observation.frame
            response.width, response.height = observation.width, observation.height
            response.resolution, response.origin = observation.resolution, list(observation.origin)
            response.source_stamp_ns, response.map_load_time_ns = 20, 10
            return response
        return callback

    servers = [server_node.create_service(MapAdoption, endpoint, serve(profile.role))
        for profile, endpoint in zip(profiles, endpoints)]
    transports = []

    def create(endpoints_=endpoints):
        transport = NativeMapClients.create(client_node, consumers=profiles, endpoints=endpoints_,
            source=lambda: raw, parent=lambda: state.parent, clock=lambda: state.time,
            stop=state.stopped.append)
        transports.append(transport)
        return transport

    try:
        class FailingCleanup:
            def __init__(self):
                self.attempted = []

            def create_client(self, *args):
                return client_node.create_client(*args)

            def destroy_client(self, client):
                self.attempted.append(client)
                result = client_node.destroy_client(client)
                if len(self.attempted) == 1:
                    raise RuntimeError('injected destroy failure after native cleanup')
                return result

        failed_node = FailingCleanup()
        try:
            NativeMapClients.create(failed_node, consumers=profiles, endpoints=endpoints,
                source=None, parent=lambda: state.parent, clock=lambda: state.time,
                stop=state.stopped.append)
        except ValueError as error:
            assert 'bounded native map owner binding required' in str(error)
            assert isinstance(error.__cause__, RuntimeError)
        else:
            raise AssertionError('invalid private configuration must fail')
        assert len(failed_node.attempted) == 2 and not tuple(client_node.clients)
        print('DDS failed configuration preserves setup error and attempts both native client cleanups: PASS')

        transport = create()
        pump(executor, transport.ready)
        assert transport.poll()
        assert transport.evidence.sample(state.parent) is None
        pump(executor, lambda: transport.evidence.sample(state.parent) is not None)
        selected = transport.evidence.sample(state.parent)
        assert selected.first_before == 10. and selected.expires_at == 10.5
        assert not state.stopped and len(state.queries) == 2
        state.time = 10.25
        assert transport.poll()
        pump(executor, lambda: len(state.queries) == 4 and not transport.pending)
        refreshed = transport.evidence.sample(state.parent)
        assert refreshed is not selected and refreshed.expires_at == 10.75
        assert len({nonce for _, nonce in state.queries}) == 4
        state.time = 10.5
        assert not transport.evidence.valid(selected, state.parent, raw_source=raw, now=state.time)
        assert transport.evidence.valid(refreshed, state.parent, raw_source=raw, now=state.time)
        transport.close()
        assert state.stopped == [state.parent] and not transport.pending
        assert not transport.poll() and transport.evidence.sample(state.parent) is None
        print('DDS success/refresh/nonce/old selected deadline/explicit close: PASS')

        # Do not spin either node until the first requests have timed out. Then
        # receive BOTH old and replacement-parent replies through real DDS.
        state.time, state.parent, state.stopped = 20., object(), []
        transport = create()
        pump(executor, transport.ready)
        old = state.parent
        assert transport.poll() and transport.pending
        state.time, state.parent = 20.26, object()
        replacement = state.parent
        assert transport.poll()
        assert state.stopped == [old]
        pump(executor, lambda: transport.evidence.sample(replacement) is not None)
        assert state.stopped == [old] and not transport.pending
        transport.close()
        assert state.stopped == [old, replacement]
        print('DDS pending timeout/detach/late replies/replacement parent: PASS')

        state.time, state.parent, state.stopped, state.negative = 30., object(), [], True
        transport = create()
        pump(executor, transport.ready)
        assert transport.poll()
        pump(executor, lambda: bool(state.stopped))
        assert state.stopped == [state.parent]
        assert transport.evidence.sample(state.parent) is None
        assert not transport.poll()
        transport.close()
        print('DDS negative response permanently consumes captured parent: PASS')

        state.time, state.parent, state.stopped, state.negative = 40., object(), [], False
        transport = create((namespace + '/absent/map_adoption', endpoints[1]))
        assert not transport.poll() and state.stopped == [state.parent]
        assert transport.evidence.sample(state.parent) is None and not transport.pending
        transport.close()
        print('DDS missing service closes without waiting: PASS')
    finally:
        for transport in transports:
            transport.close()
        for server in servers:
            server_node.destroy_service(server)
        executor.remove_node(client_node)
        executor.remove_node(server_node)
        executor.shutdown()
        client_node.destroy_node()
        server_node.destroy_node()
        rclpy.shutdown()
    print('native_map_clients: actual typed async DDS transport passed; synthetic services, no motion authority')


if __name__ == '__main__':
    main()
