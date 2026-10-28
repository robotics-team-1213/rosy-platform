"""Bounded non-trickle WHIP signaling; scoped bearer tokens never enter URLs."""

import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener


class WhipError(RuntimeError):
    """Sanitized signaling error, safe for service logs."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _origin(url, allow_loopback_http):
    parsed = urlsplit(url)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment
            or not parsed.hostname or any(ord(c) < 33 for c in url)):
        raise ValueError('media endpoint must not contain credentials or URL parameters')
    if parsed.scheme != 'https' and not (
            allow_loopback_http and parsed.scheme == 'http'
            and parsed.hostname in ('127.0.0.1', '::1', 'localhost')):
        raise ValueError('media signaling requires HTTPS')
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)


class WhipSession:
    def __init__(self, endpoint, token, *, ca_file=None, allow_loopback_http=False):
        self._origin = _origin(endpoint, allow_loopback_http)
        if (not token or not isinstance(token, str)
                or any(ord(c) < 33 or ord(c) > 126 for c in token)):
            raise ValueError('invalid scoped media credential')
        self._endpoint = endpoint
        self._token = token
        self._loopback = allow_loopback_http
        self._session = None
        self._http = build_opener(ProxyHandler({}), _NoRedirect(),
                                 HTTPSHandler(context=ssl.create_default_context(cafile=ca_file)))

    def _request(self, method, url, data=None):
        request = Request(url, data=data, method=method, headers={
            'Authorization': 'Bearer ' + self._token,
            'Content-Type': 'application/sdp',
        })
        try:
            return self._http.open(request, timeout=3)
        except HTTPError as exc:
            raise WhipError(f'media signaling refused ({exc.code})') from None
        except (URLError, OSError, TimeoutError):
            raise WhipError('media signaling unavailable') from None

    def open(self, offer):
        if self._session is not None:
            raise WhipError('media session already open')
        if not isinstance(offer, str) or not offer.startswith('v=0') or len(offer) > 65536:
            raise ValueError('invalid SDP offer')
        with self._request('POST', self._endpoint, offer.encode('utf-8')) as response:
            if response.status != 201:
                raise WhipError('media signaling did not create a session')
            location = response.headers.get('Location')
            if not location:
                raise WhipError('media signaling omitted session location')
            session = urljoin(self._endpoint, location)
            if _origin(session, self._loopback) != self._origin:
                raise WhipError('media signaling changed session origin')
            self._session = session
            content_type = response.headers.get_content_type()
            answer = response.read(65537)
            if content_type != 'application/sdp' or len(answer) > 65536 or not answer.startswith(b'v=0'):
                self.close()
                raise WhipError('invalid media SDP answer')
            return answer.decode('utf-8')

    def close(self):
        if self._session is not None:
            session, self._session = self._session, None
            with self._request('DELETE', session):
                pass
