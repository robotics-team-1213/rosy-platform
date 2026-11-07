"""D-721 Amendment: the one person request a robot may hold, for its dashboard and its face.

Fleet owns the record and the answer. This holder keeps at most one request, with its own expiry, and gives it
away read-only. It carries no motion authority: it never sets a mode, releases a stop or passes a safety check,
and holding or clearing a request changes nothing else in CORE. Expired means gone.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from core_common.person_request_text import FACE_TEXT


class PersonRequestHolder:
    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now, self._lock = now, threading.Lock()
        self._held: Optional[dict] = None

    def put(self, *, request_id: str, kind: str, text: str, why: str, ttl_s: float, owner_id: str) -> tuple[dict, bool]:
        """Hold this request; a different id replaces the one held (at most one). The same id renews only for
        its owner. Returns ``(view, renewed)``."""
        with self._lock:
            held = self._current()
            renewed = held is not None and held["id"] == request_id
            if renewed and held["owner_id"] != owner_id:
                raise PermissionError("another credential holds this request")
            self._held = {"id": request_id, "kind": kind, "text": text, "why": why, "owner_id": owner_id,
                          "until": self._now() + ttl_s}
            return self._view(self._held), renewed

    def clear(self, request_id: str, owner_id: str) -> bool:
        """The owner's end of the request: True when it was held. Nothing else changes."""
        with self._lock:
            held = self._current()
            if held is None or held["id"] != request_id:
                return False
            if held["owner_id"] != owner_id:
                raise PermissionError("another credential holds this request")
            self._held = None
            return True

    def view(self) -> Optional[dict]:
        with self._lock:
            held = self._current()
            return None if held is None else self._view(held)

    def _current(self) -> Optional[dict]:
        if self._held is not None and self._now() >= self._held["until"]:
            self._held = None
        return self._held

    def _view(self, held: dict) -> dict:
        return {"id": held["id"], "kind": held["kind"], "text": held["text"], "why": held["why"],
                "face_text": FACE_TEXT[held["kind"]], "remaining_s": round(max(0.0, held["until"] - self._now()), 1),
                "motion": False}
