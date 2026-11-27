"""Wire shape and image checks for CORE `POST /api/v1/map/site` (site-aligned master grid bundle)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from typing import Annotated, Optional, Any

from pydantic import BaseModel, ConfigDict, Field

MAX_PGM_B64 = 8_000_000
MAX_CELLS = 4096 * 4096
_WS = rb"(?:[ \t\r\n]+(?:#[^\r\n]*\r?\n[ \t\r\n]*)*|#[^\r\n]*\r?\n[ \t\r\n]*)"
_PGM_HEADER_RE = re.compile(rb"P5" + _WS + rb"(\d+)" + _WS + rb"(\d+)" + _WS + rb"255[ \t\r\n]")
_Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1000.0, le=1000.0)]


class SiteMapBundleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    version: int = Field(ge=0, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolution: float = Field(ge=0.005, le=0.2, allow_inf_nan=False)
    origin: list[_Coordinate] = Field(min_length=3, max_length=3)
    occupied_thresh: float = Field(default=0.65, ge=0.65, le=0.99, allow_inf_nan=False)
    free_thresh: float = Field(default=0.196, ge=0.01, le=0.196, allow_inf_nan=False)
    pgm_base64: str = Field(max_length=MAX_PGM_B64)
    grid_id: Optional[str] = Field(default=None, max_length=64)
    source: str = Field(default="", max_length=256)
    alignment: Optional[dict[str, Any]] = None
    activate: bool = False


class SiteMapBundleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def decode_site_map_pgm(body: SiteMapBundleBody) -> bytes:
    """The bundle image bytes, or SiteMapBundleError when base64, sha256 or the P5 header/size disagree."""
    try:
        pgm = base64.b64decode(body.pgm_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SiteMapBundleError("VALIDATION_ERROR", "pgm_base64 is not base64") from exc
    if hashlib.sha256(pgm).hexdigest() != body.sha256:
        raise SiteMapBundleError("SHA256_MISMATCH", "the site map image does not match its sha256")
    match = _PGM_HEADER_RE.match(pgm)
    if not match:
        raise SiteMapBundleError("VALIDATION_ERROR", "the site map image is not a P5 PGM with maxval 255")
    width, height = int(match[1]), int(match[2])
    if not 0 < width * height <= MAX_CELLS or len(pgm) - match.end() != width * height:
        raise SiteMapBundleError("VALIDATION_ERROR", "the site map image size does not match its header")
    return pgm
