"""Canonical Cell Job documents and the bounded transfer grant digest."""

import hashlib
import json
from typing import Any, Mapping

from core_common.protocol.schemas import FleetCellTransferGrant


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Cell Job data must be finite JSON") from exc


def cell_transfer_grant_digest(grant: Mapping[str, Any]) -> str:
    """Digest the canonical complete CELL_TRANSFER grant, excluding its digest field."""
    parsed = FleetCellTransferGrant.model_validate(dict(grant))
    document = parsed.model_dump(mode="json")
    document.pop("request_digest")
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
