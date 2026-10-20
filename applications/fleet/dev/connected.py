"""Single-upstream HTTPS adapter for the independent Fleet frontend."""
from http.client import HTTPSConnection, HTTPException
from http.cookies import CookieError, SimpleCookie
import ssl
import re
from urllib.parse import urlsplit, urlunsplit

from response import DevResponse, error

HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer',
       'transfer-encoding', 'upgrade', 'content-length'}
REQUEST_HEADERS = {'accept', 'accept-language', 'content-type', 'authorization', 'x-rosy-session', 'idempotency-key',
                   'range', 'if-none-match', 'if-modified-since', 'last-event-id'}


def origin_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('connected origins must be HTTPS scheme and authority only')
    return parsed


class Stream:
    def __init__(self, response, connection):
        self.response, self.connection = response, connection
        self.closed = False

    def __iter__(self):
        try:
            while not self.closed:
                chunk = self.response.read1(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            self.response.close()
            self.connection.close()


class ConnectedAPI:
    def __init__(self, upstream, ssl_context, local_origin):
        self.upstream, self.local = origin_url(upstream), origin_url(local_origin)
        if self.local.hostname not in ('localhost', '127.0.0.1'):
            raise ValueError('local development origin must be loopback')
        if ssl_context.verify_mode != ssl.CERT_REQUIRED or not ssl_context.check_hostname:
            raise ValueError('upstream TLS certificate and hostname verification are required')
        self.ssl_context, self.local_origin, self.upstream_origin = ssl_context, local_origin, upstream

    def handle(self, method, target, headers, body):
        incoming = {key.lower(): value for key, value in headers.items()}
        supplied = incoming.get('origin')
        if (incoming.get('host') != self.local.netloc or (supplied is not None and supplied != self.local_origin)
                or (method not in ('GET', 'HEAD') and supplied != self.local_origin)):
            return error(403, 'DEV_ORIGIN_REJECTED')
        parsed = urlsplit(target)
        frame = method in ('GET', 'HEAD') and re.fullmatch(r'/api/vision/sources/[A-Za-z0-9_-]+/frame', parsed.path)
        if (parsed.scheme or parsed.netloc or parsed.fragment or not (parsed.path.startswith('/api/fleet/') or frame)
                or any(ord(char) < 32 or ord(char) == 127 for char in target)):
            return error(400, 'INVALID_TARGET')
        outgoing = {key: value for key, value in incoming.items() if key in REQUEST_HEADERS}
        outgoing['Host'] = self.upstream.netloc
        if supplied is not None:
            outgoing['Origin'] = self.upstream_origin
        if supplied is not None or incoming.get('sec-fetch-site') == 'same-origin':
            outgoing['Sec-Fetch-Site'] = 'same-origin'
        cookie = SimpleCookie()
        try:
            cookie.load(incoming.get('cookie', ''))
        except CookieError:
            return error(400, 'INVALID_COOKIE')
        if not frame and 'rosy_fleet_session' in cookie:
            outgoing['Cookie'] = 'rosy_fleet_session=' + cookie['rosy_fleet_session'].coded_value
        connection = HTTPSConnection(self.upstream.hostname, self.upstream.port or 443,
                                     context=self.ssl_context, timeout=15)
        try:
            connection.request(method, target, body=body or None, headers=outgoing)
            response = connection.getresponse()
            blocked = HOP | {name.strip().lower() for name in response.getheader('Connection', '').split(',')}
            result = []
            for name, value in response.getheaders():
                lower = name.lower()
                if lower in blocked:
                    continue
                if lower == 'set-cookie':
                    values = SimpleCookie()
                    values.load(value)
                    if not values or any(item['domain'] for item in values.values()):
                        raise ValueError('domain cookies are not supported')
                    if set(values) != {'rosy_fleet_session'}:
                        continue
                if lower == 'location':
                    destination = urlsplit(value)
                    if destination.netloc:
                        if destination.scheme != 'https' or destination.netloc != self.upstream.netloc:
                            raise ValueError('external redirects are not supported')
                        value = urlunsplit((self.local.scheme, self.local.netloc, destination.path,
                                            destination.query, destination.fragment))
                    elif destination.scheme or value.startswith('//'):
                        raise ValueError('external redirects are not supported')
                result.append((name, value))
            return DevResponse(response.status, result, Stream(response, connection))
        except (OSError, HTTPException, ValueError, CookieError):
            connection.close()
            return error(502, 'UPSTREAM_UNAVAILABLE', 'Fleet connection or response validation failed')
