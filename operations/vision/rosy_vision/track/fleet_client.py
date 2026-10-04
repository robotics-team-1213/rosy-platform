"""Source-token client for the Fleet detections endpoints (D-457 4).

Writes anonymous detections and reads this source's own tracking config (approved
calibration record and relearn counter). The token is sent only as a header. Vision
calls no other Fleet route besides sightings and pairing sync (test_app_roles.py).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from core_common.protocol.overhead_detections import OverheadDetectionsPayload

DETECTIONS_PATH = "/api/fleet/detections"
CONFIG_PATH = "/api/fleet/detections/config"


class TrackPublishError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class TrackClient:
    def __init__(self, base_url: str, source_token: str, *, transport=None,
                 timeout_s: float = 2.0) -> None:
        parts = urlsplit(base_url)
        if (parts.scheme not in {"http", "https"} or not parts.netloc or parts.query
                or parts.fragment or parts.username or parts.password):
            raise ValueError("Fleet base URL must be an absolute HTTP(S) origin without credentials")
        if not source_token:
            raise ValueError("detection source token is required")
        self._authorization = f"Bearer {source_token}"
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s,
                                         transport=transport, follow_redirects=False)

    async def __aenter__(self) -> "TrackClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def publish(self, payload: OverheadDetectionsPayload) -> dict[str, Any]:
        response = await self._client.post(DETECTIONS_PATH, json=payload.model_dump(mode="json"),
                                           headers={"Authorization": self._authorization})
        return _body(response, "DETECTION_HTTP_ERROR", "BAD_RESPONSE")

    async def fetch_config(self) -> dict[str, Any]:
        response = await self._client.get(CONFIG_PATH, headers={"Authorization": self._authorization})
        body = _body(response, "CONFIG_HTTP_ERROR", "CONFIG_BAD_RESPONSE")
        calibration = body.get("calibration")
        if (not isinstance(body.get("source_id"), str) or not isinstance(body.get("map_id"), str)
                or type(body.get("relearn_seq")) is not int
                or not (calibration is None or isinstance(calibration, dict))):
            raise TrackPublishError(response.status_code, "CONFIG_BAD_RESPONSE",
                                    "Fleet returned a malformed tracking config")
        return body


def _body(response: httpx.Response, error_code: str, bad_code: str) -> dict[str, Any]:
    if not response.is_success:
        try:
            detail = response.json().get("detail", {})
        except (ValueError, AttributeError):
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        raise TrackPublishError(response.status_code, str(detail.get("code", error_code)),
                                str(detail.get("message", "Fleet rejected the request")))
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise TrackPublishError(response.status_code, bad_code, "Fleet returned a non-object response")
    return body
