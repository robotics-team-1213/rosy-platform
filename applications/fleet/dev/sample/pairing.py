"""A pending camera request and remembered-relationship lifecycle for the receiver UI."""
from copy import deepcopy
import re

from response import error, reply


class Pairing:
    def __init__(self):
        self.request = {'request_id': 'sample-camera-request', 'label': '샘플 카메라', 'display_code': '123456',
                        'client_id': 'sample-camera', 'client_key_sha256': 'a' * 64, 'state': 'pending', 'revision': 0}
        self.relationships = []

    def handle(self, method, path, body):
        if (method, path) == ('GET', '/pairing/v2/pending'):
            return reply([self.request] if self.request['state'] == 'pending' else [])
        if (method, path) == ('GET', '/pairing/v2/relationships'):
            return reply(self.relationships)
        if (method, path) == ('GET', '/pairing/v2/identity'):
            return reply({'receiver_id': 'sample-site', 'label': '샘플 현장', 'tls_ca_sha256': 'b' * 64})
        if (method, path) == ('GET', '/pairing/v1/pending'):
            return reply({'pending': [], 'paired_sources': [{'source_id': 'sample-camera',
                          'has_credential': any(row['state'] != 'revoked' for row in self.relationships)}]})
        if (method, path) == ('POST', '/pairing/v2/requests/sample-camera-request/decision'):
            if body.get('revision') != self.request['revision'] or self.request['state'] != 'pending':
                return error(409, 'REVISION_CONFLICT')
            if body.get('action') not in ('approve', 'reject'):
                return error(422, 'INVALID_REQUEST')
            if body['action'] == 'approve':
                if body.get('source_id') != 'sample-camera':
                    return error(422, 'INVALID_SOURCE')
                self.relationships.append({'relationship_id': 'sample-relationship', 'label': self.request['label'],
                                           'state': 'active', 'persistent': bool(body.get('persist_requested')),
                                           'authorization_available': True, 'source_id': body['source_id']})
                self.request['state'] = 'approved'
            else:
                self.request['state'] = 'rejected'
            self.request['revision'] += 1
            return reply(self.request)
        if (method, path) == ('GET', '/pairing/v2/requests/sample-camera-request'):
            return reply(self.request)
        if (method, path) == ('POST', '/pairing/v2/relationships/sample-relationship/revoke'):
            if not self.relationships:
                return error(404, 'RELATIONSHIP_NOT_FOUND')
            self.relationships[0].update(state='revoked', authorization_available=False)
            return reply(self.relationships[0])
        return None
