"""Fixed-origin HTTPS source control; long-lived source credentials stay at CORE."""

import json
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from core_common.protocol.media_grants import MediaGrantResponse
from .whip import _NoRedirect, _origin


class MediaHTTPError(RuntimeError):
    def __init__(self, message='media control request refused', *, status=None):
        super().__init__(message)
        self.status = status


class CoreSourceClient:
    def __init__(self, *, core_url, site_url, robot_id, audience, source_token,
                 core_ca=None, site_ca=None, clock=time.time):
        for url in (core_url, site_url):
            _origin(url, False)
            if urlsplit(url).path not in ('', '/'):
                raise ValueError('media control requires fixed HTTPS origins')
        if (not re.fullmatch(r'[A-Za-z0-9._-]{1,96}', robot_id)
                or not re.fullmatch(r'site:[A-Za-z0-9._-]{1,96}', audience)
                or not isinstance(source_token, str) or not 1 <= len(source_token) <= 512
                or any(ord(char) < 33 or ord(char) > 126 for char in source_token)):
            raise ValueError('invalid media source configuration')
        self._core, self._site = core_url.rstrip('/'), site_url.rstrip('/')
        self._robot, self._audience = robot_id, audience
        self._credential, self._clock = source_token, clock
        self._core_http = build_opener(ProxyHandler({}), _NoRedirect(),
            HTTPSHandler(context=ssl.create_default_context(cafile=core_ca)))
        self._site_http = build_opener(ProxyHandler({}), _NoRedirect(),
            HTTPSHandler(context=ssl.create_default_context(cafile=site_ca)))

    @staticmethod
    def _request(http, method, url, token, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(url, data=data, method=method, headers={
            'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            with http.open(request, timeout=1) as response:
                raw = response.read(65537)
                if response.status == 204:
                    return {}
                if len(raw) > 65536 or response.headers.get_content_type() != 'application/json':
                    raise MediaHTTPError('invalid media control response')
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise MediaHTTPError('invalid media control response')
                return result
        except HTTPError as exc:
            raise MediaHTTPError(status=exc.code) from None
        except (URLError, OSError, TimeoutError):
            raise MediaHTTPError('media control unavailable') from None
        except (ValueError, UnicodeDecodeError):
            raise MediaHTTPError('invalid media control response') from None

    def source_grant(self, grant_id=None):
        body = {'robot_id': self._robot}
        if grant_id is not None:
            body['grant_id'] = grant_id
        response = self._request(self._core_http, 'POST', self._core + '/api/v1/vision/media/source-grant',
                                 self._credential, body)
        try:
            grant = MediaGrantResponse.model_validate(response)
            if (grant.robot_id != self._robot or grant.path != f'robots/{self._robot}/front'
                    or grant.audience != self._audience or grant.action != 'publish'
                    or grant.site_url.rstrip('/') != self._site
                    or not self._clock() < grant.expires_at <= self._clock() + 60
                    or (grant_id is not None and grant.grant_id != grant_id)):
                raise ValueError()
            return grant
        except ValueError:
            raise MediaHTTPError('source grant changed authority or scope') from None

    def demand(self, grant):
        result = self._request(self._site_http, 'GET', self._site + f'/v1/sources/{self._robot}/demand', grant.token)
        if (type(result.get('active')) is not bool or result.get('robot_id') != self._robot
                or result.get('fps') not in (5, 10, 15)
                or type(result.get('target_bitrate')) is not int or not 0 < result['target_bitrate'] <= 1000000
                or result.get('max_bitrate') != 1000000):
            raise MediaHTTPError('invalid media demand response')
        return result

    def renew_session(self, grant):
        result = self._request(self._site_http, 'POST', self._site + '/v1/session/renew', grant.token)
        if result.get('active') is not True or not isinstance(result.get('session_id'), str):
            raise MediaHTTPError('media session renewal refused')
        return result

    def close_session(self, grant):
        self._request(self._site_http, 'DELETE', self._site + '/v1/session', grant.token)

    def whip_endpoint(self, grant):
        return self._site + '/' + grant.path + '/whip'
