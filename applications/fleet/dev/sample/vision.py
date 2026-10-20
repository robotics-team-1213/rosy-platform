"""Sample read grants are consumed only by the local media adapter."""
import re

from response import error, reply


class Vision:
    def __init__(self):
        self.grants = {}
        self.serial = 0

    def handle(self, method, path, body):
        match = re.fullmatch(r'/robots/([^/]+)/media-grant(?:/([^/]+)(/renew)?)?', path)
        if not match:
            return None
        robot, identifier, renew = match.groups()
        if robot != 'sample-robot':
            return error(404, 'UNKNOWN_ROBOT')
        if method == 'POST' and identifier is None:
            self.serial += 1
            identifier = f'sample-grant-{self.serial}'
            self.grants[identifier] = {'grant_id': identifier, 'token': 'sample-only-not-a-credential',
                                       'robot_id': robot, 'expires_at': 4102444800, 'audience': 'sample',
                                       'path': f'robots/{robot}/front', 'action': 'read', 'site_url': 'https://sample.invalid'}
            return reply(self.grants[identifier], 201)
        if method == 'POST' and renew:
            row = self.grants.get(identifier)
            return reply(row) if row else error(403, 'FORBIDDEN')
        if method == 'DELETE' and identifier and not renew:
            self.grants.pop(identifier, None)
            return reply(status=204)
        return None
