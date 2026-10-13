"""Read-only operator calibration probe; credential enters via private stdin."""
import argparse
import http.client
import json
import math
import re
import socket
import ssl
import sys


LIMIT = 16384


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


class VerifiedConnection(http.client.HTTPSConnection):
    def __init__(self, address, hostname, port, context, timeout):
        super().__init__(hostname, port, context=context, timeout=timeout)
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def metadata(body):
    if type(body) is not dict or 'session' not in body:
        raise ValueError('shape')
    session = body['session']
    if session is None:
        return {'session': None}
    if type(session) is not dict or type(session.get('owner')) is not dict:
        raise ValueError('shape')
    remaining = session.get('remaining_s')
    if type(remaining) not in (int, float) or not math.isfinite(remaining) or remaining < 0:
        raise ValueError('shape')
    def public_text(value):
        if type(value) is not str or not value or len(value) > 128:
            raise ValueError('shape')
        # Never pass arbitrary receiver strings or a private session id through.
        return re.sub(r'[^A-Za-z0-9 _.-]', '?', value)
    return {'session': {'kind': public_text(session.get('kind')),
                        'label': public_text(session.get('label')),
                        'remaining_s': remaining,
                        'owner': {'role': public_text(session['owner'].get('role')),
                                  'label': public_text(session['owner'].get('label'))}}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--address', required=True)
    parser.add_argument('--hostname', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--ca-file', required=True)
    parser.add_argument('--timeout', type=float, required=True)
    args = parser.parse_args()
    connection = None
    try:
        if (not re.fullmatch(r'[A-Za-z0-9.-]+', args.address)
                or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', args.hostname)
                or not 1 <= args.port <= 65535 or not 0 < args.timeout <= 30):
            raise ValueError('parameters')
        supplied = sys.stdin.buffer.read(8193)
        if len(supplied) > 8192:
            raise ValueError('credential')
        private = strict_json(supplied)
        token = private.get('token') if type(private) is dict else None
        if type(token) is not str or not token or len(token) > 4096 or not token.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError('credential')
        context = ssl.create_default_context(cafile=args.ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        connection = VerifiedConnection(args.address, args.hostname, args.port, context, args.timeout)
        # CA chain, validity and exact hostname/SNI verification complete BEFORE
        # the Authorization header is constructed or any HTTP bytes are sent.
        connection.connect()
        connection.request('GET', '/api/v1/calibration/session', headers={'Authorization': 'Bearer '+token})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('status')
        raw = response.read(LIMIT+1)
        if len(raw) > LIMIT:
            raise ValueError('body')
        result = metadata(strict_json(raw))
        # Receiver metadata cannot echo the credential through public fields.
        rendered = json.dumps(result, allow_nan=False)
        if token in rendered:
            raise ValueError('credential_echo')
        print(rendered)
        return 0
    except Exception:
        print('Secure calibration check failed.', file=sys.stderr)
        return 2
    finally:
        if connection is not None:
            connection.close()


if __name__ == '__main__':
    sys.exit(main())
