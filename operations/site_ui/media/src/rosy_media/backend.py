"""Local MediaMTX management; never accepts a caller-selected upstream or PID."""

import ipaddress
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID


class MediaBackendUnavailable(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MediaMTXClient:
    def __init__(self, base_url, admin_token):
        parsed = urlsplit(base_url)
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
            valid_port = parsed.port is not None
        except (ValueError, TypeError):
            loopback, valid_port = False, False
        if (parsed.scheme != 'http' or not loopback or not valid_port
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('', '/')):
            raise ValueError('media backend requires an explicit local loopback address')
        if not isinstance(admin_token, str) or not admin_token or any(
                ord(char) < 33 or ord(char) > 126 for char in admin_token):
            raise ValueError('invalid local media management credential')
        self._base, self._token = base_url.rstrip('/'), admin_token
        self._http = build_opener(ProxyHandler({}), _NoRedirect())

    def kick(self, session_id):
        # UUID parsing disallows slashes, query fragments and arbitrary API paths.
        identity = str(UUID(session_id))
        request = Request(self._base + '/v3/webrtc/sessions/kick/' + identity,
                          data=b'', method='POST', headers={'Authorization': 'Bearer ' + self._token})
        try:
            with self._http.open(request, timeout=.75) as response:
                if response.status != 200:
                    raise MediaBackendUnavailable('media session termination refused')
        except HTTPError as exc:
            if exc.code == 404:
                return  # already terminated, not an unverified live session
            raise MediaBackendUnavailable('media session termination refused') from None
        except (URLError, OSError, TimeoutError):
            raise MediaBackendUnavailable('local media backend unavailable') from None
