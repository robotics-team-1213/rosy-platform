"""Fleet HTTP boundary for the remote D-998 notification service."""

from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import re
from typing import Any, Mapping
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from core_common.protocol.notification_delivery import DeliveryOwnerReply, DeliveryRequest
from fastapi import Request as HttpRequest
from fastapi.responses import JSONResponse


def should_run_embedded_notification_worker(remote_url: str | None) -> bool:
    return not remote_url or not remote_url.strip()


def delivery_notification_id(row: Mapping[str, Any]) -> str:
    return f"fleet-{row['event_id']}-{row['channel']}-{str(row['route_hash'])[:16]}"


def build_delivery_request(row: Mapping[str, Any], facts: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if facts is None:
        facts = json.loads(row['payload'])
    raw_revision = str(row['judgment_revision'])
    revision = (
        raw_revision
        if re.fullmatch(r'[A-Za-z0-9_.:-]{1,96}', raw_revision)
        else hashlib.sha256(raw_revision.encode('utf-8')).hexdigest()
    )
    raw_classification = str(
        facts.get('necessity') or facts.get('action_credit') or facts.get('reason') or row['kind']
    )
    classification = (
        raw_classification
        if re.fullmatch(r'[A-Za-z0-9_.:-]{1,96}', raw_classification)
        else str(row['kind'])
    )
    return {
        'producer': 'fleet',
        'notification_id': delivery_notification_id(row),
        'channel': str(row['channel']),
        'kind': str(row['kind']),
        'subject_id': str(row['robot_id']),
        'occurrence_id': str(row['stuck_id']),
        'revision': revision,
        'classification': classification,
        'observed_at': float(facts.get('observed_at', row['created_at'])),
        'expires_at': float(row['expires_at']),
    }


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


def install_notification_owner_routes(
    app,
    worker,
    *,
    owner_token: str,
    path: str = '/api/fleet/notifications/owner-check',
) -> None:
    if not isinstance(owner_token, str) or len(owner_token.strip()) < 32:
        raise ValueError('notification owner token must be at least 32 characters')
    expected_auth = f'Bearer {owner_token}'

    @app.post(path, response_model=DeliveryOwnerReply)
    async def verify_notification_owner(request: HttpRequest):
        auth = request.headers.get('authorization', '')
        if not hmac.compare_digest(auth, expected_auth):
            return JSONResponse({'code': 'NOTIFICATION_OWNER_UNAUTHORIZED'}, status_code=401)
        try:
            body = DeliveryRequest.model_validate(await request.json())
        except Exception:
            return JSONResponse({'code': 'INVALID_DELIVERY_REQUEST'}, status_code=422)
        valid = worker.verify_delivery_owner(None, body)
        if inspect.isawaitable(valid):
            valid = await valid
        return DeliveryOwnerReply(
            notification_id=body.notification_id,
            revision=body.revision,
            valid=bool(valid),
        )

