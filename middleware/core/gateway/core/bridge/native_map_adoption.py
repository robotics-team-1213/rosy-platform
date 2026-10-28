"""Private asynchronous native readbacks; no timer, admission or writer authority.

The ROS-free constructor permits transport tests with real Futures. Only create
imports the generated ROS type and binds actual clients. The future factory
must be trusted composition; consumers are never supplied by a public request.
"""
from dataclasses import replace
import secrets
import threading

from core_features.navigation.native_map_adoption import NativeMapEvidence, ROLES
from core_features.navigation.native_map_reply import Consumer, NativeReply


class NativeMapClients:
    def __init__(self, *, consumers, clients, request_factory, source, parent, clock, stop):
        if (type(consumers) is not tuple or len(consumers) != 2
                or tuple(p.role for p in consumers if type(p) is Consumer) != ROLES
                or type(clients) is not tuple or len(clients) != 2
                or any(p.provider is not c for p, c in zip(consumers, clients))
                or not callable(request_factory)):
            raise ValueError('exact ordered clients and consumer profiles required')
        self.evidence = NativeMapEvidence(source=source, parent=parent, consumers=consumers,
            clock=clock, stop=stop)
        self._clients, self._consumers, self._request = clients, consumers, request_factory
        self._pending = {}
        self._closed, self._owned_node = False, None
        self._lock = threading.RLock()

    @classmethod
    def create(cls, node, *, consumers, endpoints, source, parent, clock, stop):
        """Explicit private installation only; ordinary RosBridge is unchanged."""
        from interfaces.srv import MapAdoption
        if (type(consumers) is not tuple or len(consumers) != 2
                or tuple(p.role for p in consumers if type(p) is Consumer) != ROLES
                or type(endpoints) is not tuple or len(endpoints) != 2
                or any(type(e) is not str or not e.startswith('/') or len(e) > 256 for e in endpoints)
                or endpoints[0] == endpoints[1]):
            raise ValueError('two explicit absolute native service endpoints required')
        clients = []
        try:
            for endpoint in endpoints:
                clients.append(node.create_client(MapAdoption, endpoint))
            profiles = tuple(replace(p, provider=c) for p, c in zip(consumers, clients))
            result = cls(consumers=profiles, clients=tuple(clients), request_factory=MapAdoption.Request,
                source=source, parent=parent, clock=clock, stop=stop)
            result._owned_node = node
            return result
        except Exception as error:
            try:
                cls._destroy_clients(node, clients)
            except Exception as cleanup_error:
                raise error from cleanup_error
            raise

    @staticmethod
    def _destroy_clients(node, clients):
        failure = None
        for client in clients:
            try:
                if node.destroy_client(client) is False:
                    raise RuntimeError('native map client destroy refused')
            except Exception as error:
                if failure is None:
                    failure = error
        if failure is not None:
            raise failure

    @property
    def pending(self):
        with self._lock:
            return bool(self._pending)

    def ready(self):
        with self._lock:
            try:
                return not self._closed and all(c.service_is_ready() for c in self._clients)
            except Exception:
                return False

    def _detach(self, client, future):
        try:
            client.remove_pending_request(future)
        except Exception:
            # Failed detachment cannot promise bounded pending transport state.
            self._closed = True
            self.evidence.close()

    def _discard(self):
        pending = self._pending
        self._pending = {}
        for role, (ticket, future) in pending.items():
            self.evidence.fail(ticket)
            self._detach(self._clients[ROLES.index(role)], future)
            future.cancel()  # Local cleanup, not a remote cancellation ACK.

    def poll(self):
        """One bounded two-role round; caller supplies the .25s scheduling tick.

        Overlap consumes the previous captured parent before attempting the
        current parent. No wait_for_service, spin or future.result wait occurs.
        """
        with self._lock:
            if self._closed:
                return False
            self._discard()
            if self._closed:
                return False
            round_ = self.evidence.begin()
            if round_ is None:
                return False
            for profile, client in zip(self._consumers, self._clients):
                try:
                    nonce = secrets.token_bytes(16)
                except Exception:
                    nonce = None  # issue's invalid challenge consumes this exact round.
                ticket = self.evidence.issue(round_, profile.role, client, nonce)
                if ticket is None:
                    self._discard()
                    return False
                try:
                    if not client.service_is_ready():
                        raise RuntimeError('native map service unavailable')
                    request = self._request()
                    request.challenge = list(nonce)
                    future = client.call_async(request)
                    self._pending[profile.role] = (ticket, future)
                    future.add_done_callback(lambda done, role=profile.role, ticket=ticket, client=client:
                        self._done(role, ticket, client, done))
                except Exception:
                    self.evidence.fail(ticket)
                    self._discard()
                    return False
            return True

    def _done(self, role, ticket, client, future):
        with self._lock:
            entry = self._pending.get(role)
            if entry is None or entry[0] is not ticket or entry[1] is not future:
                self.evidence.fail(ticket)  # Captured old parent only, never the new pair.
                return
            del self._pending[role]
            self._detach(client, future)
            try:
                if self._closed or future.cancelled():
                    raise RuntimeError('native map future closed')
                # Done callback only. Copy generated buffers outside the evidence lock.
                response = NativeReply.capture(future.result())
                accepted = self.evidence.reply(ticket, client, response)
            except Exception:
                accepted = False
            if not accepted:
                self.evidence.fail(ticket)
                self._discard()

    def close(self):
        with self._lock:
            self._closed = True
            self.evidence.close()
            self._discard()
            node, self._owned_node = self._owned_node, None
            if node is not None:
                self._destroy_clients(node, self._clients)
