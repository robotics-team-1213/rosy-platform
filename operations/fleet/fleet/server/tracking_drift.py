"""Calibration-drift watch: compare the approved paint fit with a fresh D-375 proposal.

The console's robot-sample verdict (2026-10-07, feat/cam-drift-warn) needs a still
robot under the camera for three consecutive polls — a site whose robots are parked
outside the view (or has none on the floor) stays blind to a re-aimed camera. Vision's
D-375 registrar already measures the current camera-to-map homography from the lane
paint alone, so Fleet asks it on a slow cadence, per source, and compares the proposal
against the operator-approved ``tracking_calibrations`` record. No robots involved.

Display only (D-457): the verdict rides the ``/api/fleet/tracking`` source rows for
the console bird's-eye. It never feeds sightings, goals, traffic, missions or motion.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Awaitable, Callable, Mapping, Optional, Sequence
from urllib.parse import urlsplit

import httpx

from core_common.protocol.vision_preview import VisionLeaseSigner
from fleet.server.sightings import SightingSource
from fleet.server.tracking_calibration import CalibrationRecord, TrackingCalibrationStore

#: Worst track-corner displacement between the two fits, map metres. A robot width
#: (Pinky ~0.26 m) is already a visible misplacement on the bird's-eye; the paint-fit
#: refinement repeats well under that on a static camera, so 0.3 m means the fits
#: genuinely disagree, not measurement noise. Display guidance, not an accuracy claim.
DRIFT_MOVE_M = 0.3
#: Relative rotation of the image->map linear parts, degrees. A bumped ceiling mount
#: yaws by degrees, not fractions; 3 deg also matches the operator-perceptible skew of
#: a straight lane painted across the site view.
DRIFT_ROTATION_DEG = 3.0
#: Default cadence of one comparison pass per source. Generous on purpose: each pass
#: triggers one registration run on Vision's single low-priority worker (D-375), and
#: the verdict only needs to notice a re-aimed camera within minutes, not seconds.
DEFAULT_INTERVAL_S = 60.0

_LOG = logging.getLogger(__name__)


def calibration_drift_verdict(approved: CalibrationRecord, body: Mapping) -> Optional[dict]:
    """Quantify the approved fit against one D-375 map-proposal response body.

    ``body`` is the Vision ``GET /api/vision/sources/{id}/map-proposal`` JSON. Only an
    accepted fit (``accepted`` true, ``proposal`` present) is evidence: a rejected fit
    usually means something covers the paint, which says nothing about the calibration.
    Returns ``None`` when there is no comparable fit — an image size change also
    returns ``None`` (the two pixel grids are then not the same camera view and any
    number computed from them would be invented), as does any non-finite matrix.

    Sample points are the four corners of the approved ``track_bounds_m`` — the only
    floor the tracking layer draws. Each corner is projected into pixels with the
    approved ``map_to_image`` and re-embedded into map metres with the proposal's
    ``image_to_map``; the displacement is exactly the display error a robot standing
    on that corner would suffer. Frame corners are deliberately not used: a tilted
    camera puts a frame edge near the horizon, where the perspective divide turns a
    tiny re-aim into many metres of corner movement and false-flags a healthy fit.

    Rotation is read from the linear parts on the map plane: ``B @ inv(A)`` for the
    proposal part ``B`` and the approved part ``A``, taking the angle of the closest
    rotation (the 2x2 Kabsch angle). That is the yaw a re-levelled mount adds, free
    of where the displacement is sampled.
    """
    if not isinstance(body, Mapping) or body.get("accepted") is not True:
        return None
    proposal = body.get("proposal")
    image = body.get("image")
    if not isinstance(proposal, Mapping) or not isinstance(image, Mapping):
        return None
    try:
        width, height = int(image["width"]), int(image["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if width != approved.image_width or height != approved.image_height:
        return None  # a different pixel grid is not the same camera view
    try:
        proposal_i2m = _matrix33(proposal["image_to_map"])
    except (KeyError, TypeError, ValueError):
        return None
    approved_i2m = _invert3(approved.map_to_image)
    if approved_i2m is None or proposal_i2m is None:
        return None

    max_move = 0.0
    min_x, min_y, max_x, max_y = approved.track_bounds_m
    for corner in ((min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)):
        pixel = _apply3(approved.map_to_image, *corner)
        moved = _apply3(proposal_i2m, *pixel) if pixel is not None else None
        if pixel is None or moved is None:
            return None  # a corner at or beyond the proposal's horizon: incomparable
        max_move = max(max_move, math.hypot(moved[0] - corner[0], moved[1] - corner[1]))

    relative = _linear_relative(approved_i2m, proposal_i2m)
    if relative is None:
        return None
    rotation = math.degrees(math.atan2(relative[1][0] - relative[0][1],
                                       relative[0][0] + relative[1][1]))
    stale = max_move > DRIFT_MOVE_M or abs(rotation) > DRIFT_ROTATION_DEG
    return {"state": "stale" if stale else "ok",
            "max_move_m": round(max_move, 3), "rotation_deg": round(abs(rotation), 2)}


class CalibrationDriftWatch:
    """One verdict per source, refreshed from Vision on a slow cadence.

    CPU frugality (D-375): the registrar is single-flight and low-priority. A miss —
    Vision busy (429, a manual operator proposal holds the worker), no fresh frame,
    a rejected fit, a transport error — simply skips that source for this pass; the
    watch never queues work behind a manual run. The last verdict stands until a good
    proposal or a calibration change replaces it, because a rejected fit is not drift
    evidence. A newly approved or revoked record clears the source's verdict: the
    operator has just re-fitted, and an old comparison against the old fit is void.
    """

    def __init__(self, *, sources: Sequence[SightingSource],
                 calibrations: TrackingCalibrationStore,
                 fetch_proposal: Callable[[str], Awaitable[Optional[Mapping]]],
                 clock: Callable[[], float] = time.time,
                 interval_s: float = DEFAULT_INTERVAL_S) -> None:
        if not math.isfinite(interval_s) or interval_s <= 0:
            raise ValueError("calibration drift interval must be positive and finite")
        self.sources = tuple(sources)
        self.calibrations = calibrations
        self.interval_s = interval_s
        self._fetch_proposal = fetch_proposal
        self._clock = clock
        self._verdicts: dict[str, dict] = {}

    def verdicts(self) -> dict[str, dict]:
        """The per-source verdicts the tracking snapshot embeds (a copy)."""
        return dict(self._verdicts)

    async def poll_once(self) -> None:
        for source in self.sources:
            record = self.calibrations.get(source.source_id)
            if record is None or record.map_id != source.map_id:
                self._verdicts.pop(source.source_id, None)  # revoked or wrong map
                continue
            held = self._verdicts.get(source.source_id)
            if held is not None and held.get("calibration_revision") != record.calibration_revision:
                self._verdicts.pop(source.source_id, None)  # a new approval resets it
            body = await self._fetch_proposal(source.source_id)
            if body is None:
                continue
            metrics = calibration_drift_verdict(record, body)
            if metrics is None:
                continue
            self._verdicts[source.source_id] = {
                **metrics,
                "calibration_revision": record.calibration_revision,
                "frame_seq": body.get("frame_seq"),
                "checked_at": self._clock(),
            }

    async def run(self) -> None:
        """The app lifespan task: one pass per interval, forever; errors never stop it."""
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOG.exception("calibration drift check pass failed")
            await asyncio.sleep(self.interval_s)

    async def aclose(self) -> None:
        close = getattr(self._fetch_proposal, "aclose", None)
        if callable(close):
            await close()


class VisionMapProposalReader:
    """Fetch one source's current map proposal with a self-issued preview lease.

    The lease is the console preview lease (60 s, source-scoped, ``frame:read``);
    Fleet signs it with the same vision preview secret the console uses, so Vision
    needs no new credential and its per-lease-subject rate bucket keeps this reader
    in its own lane. The base URL is an absolute HTTP(S) origin without credentials —
    the site stack uses ``https://vision:<port>`` on the internal compose network
    (the fleet container verifies the site CA via ``SSL_CERT_FILE``); a loopback
    ``http://`` origin is accepted for local runs.
    """

    def __init__(self, *, base_url: str, signer: VisionLeaseSigner,
                 principal_id: str = "fleet-calibration-drift-watch",
                 client: Optional[httpx.AsyncClient] = None,
                 timeout_s: float = 20.0) -> None:
        parts = urlsplit(base_url)
        if (parts.scheme not in {"https", "http"} or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment
                or parts.path not in ("", "/")
                or (parts.scheme != "https" and parts.hostname not in {"127.0.0.1", "::1", "localhost"})):
            raise ValueError("vision base URL must be the HTTPS origin (loopback HTTP allowed) "
                             "of the ingest server, without credentials")
        if not isinstance(signer, VisionLeaseSigner):
            raise ValueError("a Vision preview lease signer is required")
        self.base_url = base_url.rstrip("/")
        self._signer = signer
        self._principal_id = principal_id
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_s, follow_redirects=False)

    async def __call__(self, source_id: str) -> Optional[dict]:
        """One proposal body, or None when this cycle has nothing comparable.

        A registration run takes seconds, so the timeout is generous; any non-200
        (429 busy, 404 no frame / no paint configured, 401, 422 undecodable) is a
        skip, never an error path — the watch keeps its last verdict.
        """
        try:
            lease = self._signer.issue(principal_id=self._principal_id, source_id=source_id, ttl_s=60)
        except ValueError:
            return None
        try:
            response = await self._client.get(
                f"{self.base_url}/api/vision/sources/{source_id}/map-proposal",
                headers={"Authorization": f"Bearer {lease}", "Accept": "application/json"})
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


# -- small matrix helpers (fleet stays numpy-free) ----------------------------

def _matrix33(raw) -> tuple[float, ...]:
    rows = [float(value) for row in raw for value in row]
    if len(rows) != 9 or not all(math.isfinite(value) for value in rows):
        raise ValueError("matrix must be nine finite numbers")
    return tuple(rows)


def _apply3(matrix: Sequence[float], x: float, y: float) -> Optional[tuple[float, float]]:
    a, b, c, d, e, f, g, h, i = matrix
    w = g * x + h * y + i
    if not math.isfinite(w) or abs(w) < 1e-9:
        return None  # at the horizon: the projection is undefined here
    return ((a * x + b * y + c) / w, (d * x + e * y + f) / w)


def _invert3(m: Sequence[float]) -> Optional[tuple[float, ...]]:
    a, b, c, d, e, f, g, h, i = m
    det = (a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g))
    if not math.isfinite(det) or abs(det) < 1e-12:
        return None
    inverse = ((e * i - f * h) / det, -(b * i - c * h) / det, (b * f - c * e) / det,
               -(d * i - f * g) / det, (a * i - c * g) / det, -(a * f - c * d) / det,
               (d * h - e * g) / det, -(a * h - b * g) / det, (a * e - b * d) / det)
    return inverse


def _linear_relative(approved_i2m: Sequence[float],
                     proposal_i2m: Sequence[float]) -> Optional[tuple[tuple[float, float], ...]]:
    """``B @ inv(A)`` for the 2x2 linear parts, as the map-plane relative transform.

    The 2x2 part of a row-major 3x3 sits at indices 0, 1, 3, 4 (m00, m01, m10, m11).
    """
    a = (approved_i2m[0], approved_i2m[1], approved_i2m[3], approved_i2m[4])
    det = a[0] * a[3] - a[1] * a[2]
    if not math.isfinite(det) or abs(det) < 1e-12:
        return None
    inv_a = ((a[3] / det, -a[1] / det), (-a[2] / det, a[0] / det))
    b = (proposal_i2m[0], proposal_i2m[1], proposal_i2m[3], proposal_i2m[4])
    relative = ((b[0] * inv_a[0][0] + b[1] * inv_a[1][0], b[0] * inv_a[0][1] + b[1] * inv_a[1][1]),
                (b[2] * inv_a[0][0] + b[3] * inv_a[1][0], b[2] * inv_a[0][1] + b[3] * inv_a[1][1]))
    if not all(math.isfinite(value) for row in relative for value in row):
        return None
    return relative
