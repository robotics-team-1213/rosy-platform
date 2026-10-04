"""Viewer-only peer directory; no enrollment, endpoint edits or control dispatch."""
from urllib.parse import urlsplit
import ipaddress

from core_common.protocol.network_peers import PeerSummary


def install_peer_routes(app, *, catalogue, console, enrollment, pairing, read_guard, directory_rows=()):
    @app.get('/api/fleet/peers', dependencies=read_guard, tags=['fleet-discovery'])
    def peers():
        approved = {}
        directory = list(directory_rows)
        conflicts = set()

        def claim(key, identity):
            if key in conflicts:
                return
            if key in approved and approved[key] != identity:
                conflicts.add(key)
                approved.pop(key, None)
            else:
                approved[key] = identity

        names = enrollment.enrolled_names() if enrollment is not None else {}
        for name, identity in names.items():
            claim(('robot', name.lower() + '.local'), identity)
        for row in directory_rows:
            if row.hostname is not None:
                claim((row.role, row.hostname), row.peer_id)
        for identity, base_url in console.registered_endpoints.items():
            endpoint = urlsplit(base_url)
            host = (endpoint.hostname or '').lower().rstrip('.')
            try:
                address = str(ipaddress.ip_address(host))
                hostname = None
            except ValueError:
                address, hostname = None, host
            try:
                directory.append(PeerSummary(name=identity, role='robot', transport=endpoint.scheme,
                    service_type='_rosy._tcp', hostname=hostname, address=address,
                    port=endpoint.port or (443 if endpoint.scheme == 'https' else 80), peer_id=identity,
                    provenance='approved-directory', approval='approved', freshness='unavailable'))
            except ValueError:
                # Localhost/test-only endpoints are not routable network peers.
                continue
            if hostname is not None:
                claim(('robot', hostname), identity)
        if pairing is not None:
            # Active credentials establish approved source registration, not a live Cam session.
            source_ids = sorted({row['source_id'] for row in pairing.sync_listing()})
            directory.extend(PeerSummary(name=source, role='cam', transport='session', peer_id=source,
                                     provenance='approved-directory', approval='approved',
                                     freshness='unavailable') for source in source_ids[:64])
        return catalogue.snapshot(approved=approved, directory=directory,
                                  conflicts=conflicts).model_dump(mode='json')
