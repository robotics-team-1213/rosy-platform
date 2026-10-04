"""D-452 bounded service hints, separate from robot enrollment and authority."""
import math
import threading
import time

from core_common.protocol.network_peers import PeerCatalogue, PeerObservation, PeerSummary


class PeerCatalogueStore:
    def __init__(self, *, clock=time.monotonic, ttl_s=45.0):
        if not math.isfinite(ttl_s) or ttl_s <= 0:
            raise ValueError('peer TTL must be finite and positive')
        self._clock, self._ttl = clock, ttl_s
        self._seen = None
        self._rows = []
        self._lock = threading.RLock()

    @staticmethod
    def validate_scan(rows, *, services_only=False):
        if len(rows) > 64:
            raise ValueError('peer scan contains more than 64 services')
        result = {}
        for value in rows:
            row = PeerObservation.model_validate(value)
            if row.transport == 'session':
                raise ValueError('scanner cannot publish application sessions')
            if services_only and row.role == 'robot':
                raise ValueError('robot observations belong in devices, not services')
            key = (row.role, row.hostname, row.address, row.port)
            result.setdefault(key, row.model_copy(deep=True))
        return list(result.values())

    def replace_scan(self, rows):
        rows = self.validate_scan(rows)
        with self._lock:
            self._rows, self._seen = rows, self._clock()

    def snapshot(self, *, approved=None, directory=(), conflicts=()):
        approved = approved or {}
        with self._lock:
            rows, seen = list(self._rows), self._seen
        age = None if seen is None else max(0.0, self._clock() - seen)
        state = 'never_seen' if age is None else ('expired' if age > self._ttl else 'online')
        locations = {}
        for row in rows:
            locations.setdefault((row.role, row.hostname), set()).add((row.address, row.port))
        peers = []
        for row in rows:
            identity = approved.get((row.role, row.hostname))
            freshness = 'expired' if state == 'expired' else (
                'conflict' if (row.role, row.hostname) in conflicts or
                len(locations[(row.role, row.hostname)]) > 1 else 'fresh')
            peers.append(PeerSummary(**row.model_dump(), peer_id=identity, provenance='mdns',
                                     freshness=freshness, approval='approved' if identity else 'unapproved'))
        # Presence is supplied by an existing owner directory, never by scanner TXT.
        discovered_ids = {(row.role, row.peer_id) for row in peers if row.peer_id is not None}
        for row in directory:
            row = PeerSummary.model_validate(row)
            if (row.role, row.peer_id) not in discovered_ids:
                peers.append(row)
        peers.sort(key=lambda row: (row.approval != 'approved', row.role, row.name, row.address or ''))
        return PeerCatalogue(peers=peers[:64], scanner_state=state, scanner_age_s=age)
