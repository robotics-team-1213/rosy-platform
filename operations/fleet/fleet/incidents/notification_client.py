"""Fleet HTTP boundary for the remote D-998 notification service."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def should_run_embedded_notification_worker(remote_url: str | None) -> bool:
    return not remote_url or not remote_url.strip()


class RemoteNotificationSink:
    def __init__(self, base_url: str, *, bearer_token: str | None = None, timeout_s: float = 5.0, opener=None):
        if not isinstance(base_url, str):
            raise ValueError('notification service URL must be HTTP(S)')
        target = urlsplit(base_url)
        if (target.scheme not in ('http', 'https') or not target.hostname
                or target.username or target.password or target.query or target.fragment):
            raise ValueError('notification service URL must be HTTP(S)')
        self.base_url = base_url.rstrip('/')
        self.bearer_token = bearer_token
        self.timeout_s = timeout_s
        self._opener = opener

    def _headers(self, *, json_body: bool = True) -> dict[str, str]:
        headers = {'Content-Type': 'application/json'} if json_body else {}
        if self.bearer_token:
            headers['Authorization'] = f'Bearer {self.bearer_token}'
        return headers

    def _send(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload, allow_nan=False).encode('utf-8') if payload is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            headers=self._headers(json_body=payload is not None),
            method=method,
        )
        open_fn = self._opener.open if self._opener is not None else urlopen
        with open_fn(request, timeout=self.timeout_s) as response:
            return json.load(response)

    def submit_delivery(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._send('POST', '/api/notifications/v1/deliveries', payload)

    def read_delivery(self, notification_id: str) -> dict[str, Any]:
        return self._send('GET', f'/api/notifications/v1/deliveries/{notification_id}')
