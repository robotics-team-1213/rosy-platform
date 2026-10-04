"""Source-token-only client for the Fleet derived-sighting endpoint."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from core_common.protocol.sightings import SiteSightingPayload


class SightingPublishError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class SightingPublisher:
    """Publish small derived poses; the source token is sent only as a header."""

    def __init__(self, base_url: str, source_token: str, *, transport=None,
                 timeout_s: float = 2.0) -> None:
        parts = urlsplit(base_url)
        if (parts.scheme not in {"http", "https"} or not parts.netloc or parts.query
                or parts.fragment or parts.username or parts.password):
            raise ValueError("Fleet base URL must be an absolute HTTP(S) origin without credentials")
        if not source_token:
            raise ValueError("sighting source token is required")
        self._authorization = f"Bearer {source_token}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            transport=transport,
            follow_redirects=False,
        )

    async def __aenter__(self) -> "SightingPublisher":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def publish(self, sighting: SiteSightingPayload) -> dict[str, Any]:
        response = await self._client.post(
            "/api/fleet/sightings",
            json=sighting.model_dump(mode="json"),
            headers={"Authorization": self._authorization},
        )
        if not response.is_success:
            detail = response.json().get("detail", {})
            if not isinstance(detail, dict):
                detail = {}
            raise SightingPublishError(
                response.status_code,
                str(detail.get("code", "SIGHTING_HTTP_ERROR")),
                str(detail.get("message", "Fleet rejected sighting")),
            )
        body = response.json()
        if not isinstance(body, dict):
            raise SightingPublishError(response.status_code, "SIGHTING_BAD_RESPONSE",
                                       "Fleet returned a non-object response")
        return body
