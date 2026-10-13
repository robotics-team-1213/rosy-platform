"""Trusted, bounded reads from the existing source-scoped Vision preview API."""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlsplit

import httpx

from core_common.protocol.schemas import (
    ER2_IMAGE_MAX_BYTES,
    ER2_POST_ACTION_OBSERVATION_MAX_AGE_SECONDS,
    MissionFeedbackTurnScope,
)
from core_common.protocol.vision_preview import VisionLeaseSigner

from .candidate import ImageObservation, ImageTransform

_MAX_DIMENSION = 8192
_MAX_CAPTURE_ATTEMPTS = 3
_CAPTURE_RETRY_SECONDS = 1.05
_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")


class VisionObservationUnavailable(ValueError):
    """The scoped Vision source could not provide a bounded fresh frame."""


def _identifier(name: str, value: Any, *, limit: int = 160) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{name} must be a bounded trimmed identifier")
    return value


def _timestamp(value: str, *, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class VisionObservationSourceSpec:
    """Trusted static mapping from a Mission workcell to a Vision camera source."""

    workcell_id: str
    source_id: str
    camera_id: str
    frame_id: str
    calibration_revision: str
    transform_revision: str

    def __post_init__(self) -> None:
        for name in ("workcell_id", "camera_id", "frame_id",
                     "calibration_revision", "transform_revision"):
            _identifier(name, getattr(self, name))
        if not isinstance(self.source_id, str) or not _SOURCE_ID.fullmatch(self.source_id):
            raise ValueError("source_id is not a valid Vision source identifier")


class VisionPostActionObservationSource:
    """Read a fresh Vision frame tied to the turn owner and action watermark.

    The model never chooses a URL or source. Both are fixed by trusted
    configuration and the durable workcell scope. Vision credentials are short
    lived source-scoped leases; frame bytes remain in process memory only.
    """

    def __init__(self, *, base_url: str, lease_signer: VisionLeaseSigner,
                 sources: Mapping[str, VisionObservationSourceSpec],
                 client: httpx.AsyncClient | None = None,
                 clock: Callable[[], datetime] | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        parts = urlsplit(base_url)
        if (parts.scheme not in {"https", "http"} or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment):
            raise ValueError("Vision base URL must be an absolute HTTP(S) origin without credentials")
        if parts.scheme != "https" and parts.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("remote Vision traffic requires HTTPS")
        if not isinstance(lease_signer, VisionLeaseSigner):
            raise ValueError("a dedicated Vision lease signer is required")
        checked_sources: dict[str, VisionObservationSourceSpec] = {}
        for workcell_id, spec in sources.items():
            _identifier("workcell_id", workcell_id, limit=96)
            if not isinstance(spec, VisionObservationSourceSpec) or spec.workcell_id != workcell_id:
                raise ValueError("Vision source mapping must match its workcell key")
            checked_sources[workcell_id] = spec
        if not checked_sources:
            raise ValueError("at least one trusted Vision source mapping is required")
        self.base_url = base_url.rstrip("/")
        self.lease_signer = lease_signer
        self.sources = checked_sources
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(3.5), follow_redirects=False,
        )

    async def capture_after(self, *, scope: MissionFeedbackTurnScope,
                            based_on_event_id: int,
                            after_action_at: str) -> Mapping[str, Any]:
        if not isinstance(scope, MissionFeedbackTurnScope):
            raise ValueError("Vision capture requires a typed durable turn scope")
        if (type(based_on_event_id) is not int
                or based_on_event_id != scope.event_watermark):
            raise ValueError("Vision capture event must match the trusted turn watermark")
        action_at = _timestamp(after_action_at, name="after_action_at")
        spec = self.sources.get(scope.workcell_id)
        if spec is None:
            raise VisionObservationUnavailable("no Vision source is configured for the workcell")
        lease = self.lease_signer.issue(
            principal_id=scope.principal_id, source_id=spec.source_id, ttl_s=60,
        )
        url = (f"{self.base_url}/api/vision/sources/"
               f"{spec.source_id}/frame")
        for attempt in range(_MAX_CAPTURE_ATTEMPTS):
            if attempt:
                await self._sleep(_CAPTURE_RETRY_SECONDS)
            observation = await self._read_frame(
                url=url, lease=lease, spec=spec,
            )
            if _timestamp(observation.observed_at, name="captured_at") > action_at:
                return {
                    "observation": observation,
                    "scope": {
                        "mission_id": scope.mission_id,
                        "workcell_id": scope.workcell_id,
                        "action_id": scope.action_id,
                        "attempt_id": scope.attempt_id,
                        "dispatch_generation": scope.dispatch_generation,
                        "based_on_event_id": based_on_event_id,
                        "observation_id": observation.observation_id,
                        "observed_at": observation.observed_at,
                        "image_sha256": observation.sha256,
                    },
                }
        raise VisionObservationUnavailable(
            "Vision frames did not advance past the terminal Action time"
        ) from None

    async def _read_frame(self, *, url: str, lease: str,
                          spec: VisionObservationSourceSpec) -> ImageObservation:
        headers = {
            "Authorization": f"Bearer {lease}",
            "Accept": "image/jpeg",
            "Cache-Control": "no-cache",
        }
        try:
            async with self.client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    raise VisionObservationUnavailable("Vision frame is unavailable")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                cache_control = {
                    item.strip().lower() for item in
                    response.headers.get("cache-control", "").split(",")
                }
                if content_type != "image/jpeg" or "no-store" not in cache_control:
                    raise VisionObservationUnavailable("Vision frame contract is invalid")
                length = response.headers.get("content-length")
                if length is not None:
                    try:
                        if int(length) < 1 or int(length) > ER2_IMAGE_MAX_BYTES:
                            raise VisionObservationUnavailable("Vision frame exceeds image limits")
                    except ValueError as exc:
                        raise VisionObservationUnavailable("Vision frame length is invalid") from exc
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > ER2_IMAGE_MAX_BYTES:
                        raise VisionObservationUnavailable("Vision frame exceeds image limits")
                    body.extend(chunk)
                if not body:
                    raise VisionObservationUnavailable("Vision frame is empty")
                if not body.startswith(b"\xff\xd8"):
                    raise VisionObservationUnavailable("Vision frame is not a JPEG")
                return self._observation(response.headers, bytes(body), spec)
        except httpx.HTTPError as exc:
            raise VisionObservationUnavailable("Vision frame request failed") from exc

    def _observation(self, headers: Mapping[str, str], body: bytes,
                     spec: VisionObservationSourceSpec) -> ImageObservation:
        try:
            sequence = int(headers["x-frame-seq"])
            age_ms = int(headers["x-frame-age-ms"])
            captured_epoch = float(headers["x-frame-captured-at"])
            width = int(headers["x-frame-width"])
            height = int(headers["x-frame-height"])
            rotation = int(headers["x-frame-rotation-deg"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VisionObservationUnavailable("Vision frame metadata is incomplete") from exc
        if (type(sequence) is not int or not 0 <= sequence <= 0xFFFFFFFF
                or age_ms < 0
                or age_ms > ER2_POST_ACTION_OBSERVATION_MAX_AGE_SECONDS * 1000
                or not math.isfinite(captured_epoch)
                or not 1 <= width <= _MAX_DIMENSION
                or not 1 <= height <= _MAX_DIMENSION
                or rotation not in {0, 90, 180, 270}
                or headers.get("x-frame-rectified", "").lower() != "false"):
            raise VisionObservationUnavailable("Vision frame metadata is outside limits")
        try:
            captured_at = datetime.fromtimestamp(captured_epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise VisionObservationUnavailable("Vision capture time is invalid") from exc
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise VisionObservationUnavailable("Fleet clock must be timezone-aware")
        age = (now.astimezone(timezone.utc) - captured_at).total_seconds()
        if (age < 0 or age > ER2_POST_ACTION_OBSERVATION_MAX_AGE_SECONDS
                or age_ms / 1000 > ER2_POST_ACTION_OBSERVATION_MAX_AGE_SECONDS):
            raise VisionObservationUnavailable("Vision frame is stale or from the future")
        stamp = captured_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
        from hashlib import sha256

        digest = sha256(body).hexdigest()
        observation_id = f"vision:{spec.source_id}:{sequence}:{digest[:16]}"
        return ImageObservation(
            observation_id=observation_id,
            camera_id=spec.camera_id,
            frame_id=spec.frame_id,
            observed_at=stamp,
            image_bytes=body,
            mime_type="image/jpeg",
            image_transform=ImageTransform(
                source_width=width, source_height=height,
                rotation_quadrants_clockwise=rotation // 90,
            ),
            calibration_revision=spec.calibration_revision,
            transform_revision=spec.transform_revision,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()


__all__ = [
    "VisionObservationSourceSpec", "VisionObservationUnavailable",
    "VisionPostActionObservationSource",
]
