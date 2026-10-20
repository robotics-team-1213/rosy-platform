"""Source-token-only client for the Fleet derived-sighting endpoint."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import TypeAdapter

from core_common.protocol.place_markers import PlaceMarkerPayload
from core_common.protocol.sightings import SiteSightingPayload
from core_common.protocol.station_charging import Identifier, StationObservation
from rosy_vision.track.fleet_client import _body


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
            trust_env=False,
        )

    async def __aenter__(self) -> "SightingPublisher":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def publish(self, sighting: SiteSightingPayload) -> dict[str, Any]:
        return await self._post("/api/fleet/sightings", sighting)

    async def publish_place_markers(self, payload: PlaceMarkerPayload) -> dict[str, Any]:
        """D-564: floor place marker poses, same source token."""
        return await self._post("/api/fleet/place-markers", payload)

    async def publish_station_observation(self, observation) -> dict[str, Any]:
        return await self._post('/api/fleet/station-observations', observation)

    async def publish_station_pose(self, candidate) -> dict[str, Any]:
        return await self._post('/api/fleet/station-poses', candidate)

    async def station_scope(self, robot_id):
        robot_id = TypeAdapter(Identifier).validate_python(robot_id)
        response = await self._client.get('/api/fleet/station-observation-scope/'+robot_id,
                                          headers={'Authorization': self._authorization})
        if not response.is_success:
            raise SightingPublishError(response.status_code, 'STATION_SCOPE_HTTP_ERROR', 'Fleet scope unavailable')
        body = response.json()
        if not isinstance(body, dict) or 'scope' not in body:
            raise SightingPublishError(response.status_code, 'STATION_SCOPE_BAD_RESPONSE', 'Fleet scope unavailable')
        if body['scope'] is None:
            return None
        scope = StationObservation.model_validate(body['scope'])
        if scope.visible or scope.pose is not None or scope.sequence != 0:
            raise SightingPublishError(response.status_code, 'STATION_SCOPE_BAD_RESPONSE', 'Scope is not metadata')
        return scope

    async def _post(self, path: str, body) -> dict[str, Any]:
        response = await self._client.post(
            path,
            json=body.model_dump(mode="json"),
            headers={"Authorization": self._authorization},
        )
        return _body(response, "SIGHTING_HTTP_ERROR", "SIGHTING_BAD_RESPONSE",
                     error_type=SightingPublishError, rejection_message="Fleet rejected sighting")
