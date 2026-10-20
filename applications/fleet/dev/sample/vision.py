"""Sample read grants are consumed only by the local media adapter."""
import re
import struct
import zlib

from response import DevResponse, error, reply


def sample_frame():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    rows = b''.join(b'\0' + bytes((55, 85, 110)) * 640 for _ in range(360))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 640, 360, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


class Vision:
    def __init__(self):
        self.grants = {}
        self.serial = 0
        self.leases = set()

    def frame(self, method, path, headers):
        if path != '/api/vision/sources/sample-camera/frame' or method not in ('GET', 'HEAD'):
            return error(404, 'UNKNOWN_FRAME')
        token = headers.get('authorization', '').removeprefix('Bearer ')
        if token not in self.leases:
            return error(401, 'VISION_LEASE_REQUIRED')
        return DevResponse(200, [('Content-Type', 'image/png'), ('Cache-Control', 'no-store'),
                                 ('X-Frame-Age-Ms', '0'), ('X-Frame-Rectified', 'raw')], sample_frame())

    def handle(self, method, path, body):
        if (method, path) == ('GET', '/vision/sources'):
            return reply(['sample-camera'])
        if (method, path) == ('POST', '/vision/lease'):
            if body.get('source_id') != 'sample-camera':
                return error(404, 'UNKNOWN_SOURCE')
            self.serial += 1
            token = f'sample-vision-lease-{self.serial}'
            self.leases.add(token)
            return reply({'source_id': 'sample-camera', 'lease': token, 'expires_in_s': 60,
                          'frame_path': '/api/vision/sources/sample-camera/frame'})
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
