"""Read-only admin-provisioned identities, not discovery or credential enrollment."""
import json
from pathlib import Path

from core_common.protocol.network_peers import PeerSummary


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate directory field')
        result[key] = value
    return result


def load_approved_peer_directory(path):
    if path is None:
        return ()
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('directory exceeds byte budget')
        values = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(values, list) or len(values) > 64:
            raise ValueError('directory must be an array of at most 64 peers')
        rows = tuple(PeerSummary.model_validate(value) for value in values)
        identities, endpoints = set(), set()
        for row in rows:
            if (row.provenance != 'approved-directory' or row.approval != 'approved'
                    or row.readiness != 'unknown' or row.freshness != 'unavailable'):
                raise ValueError('directory metadata cannot assert live owner evidence')
            identity = (row.role, row.peer_id)
            endpoint = (row.role, row.hostname or row.address)
            if identity in identities or (row.transport != 'session' and endpoint in endpoints):
                raise ValueError('duplicate directory identity or endpoint owner')
            identities.add(identity)
            endpoints.add(endpoint)
        return rows
    except (OSError, ValueError, TypeError):
        # Validation errors can include submitted credential values; never echo them.
        raise ValueError('invalid approved peer directory metadata') from None
