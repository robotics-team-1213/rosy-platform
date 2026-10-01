"""Paired camera credentials for Vision, synced from Fleet (D-341 11-12).

Vision never sees a paired token: Fleet lists ``token_sha256`` per ``source_id`` and Vision
compares the SHA-256 of the presented bearer in constant time. The sync runs on its own
daemon thread every 2 s, so CPU work on the ingest event loop cannot starve it (2026-10-01
starvation lesson); the loop only reads the latest list, replaced atomically.

State is *unknown* (close 4503, retryable) until the first good list and when the last good
list is older than 10 min. A credential missing from a fresh list is unknown (close 4401,
final): revoked, expired or never issued.
"""

from __future__ import annotations

import hmac
import logging
import re
import ssl
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

ROLE = "overhead-camera"
LIST_PATH = "/api/fleet/pairing/v1/credentials"
SYNC_INTERVAL_S = 2.0
STALE_AFTER_S = 600.0
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_EXPIRES_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def parse_listing(body: object) -> list[tuple[str, bytes, str, float]]:
    """``(source_id, digest, credential_id, expires_wall)`` rows from Fleet's list, or ValueError."""
    if not isinstance(body, dict) or body.get("role") != ROLE or not isinstance(body.get("credentials"), list):
        raise ValueError("pairing credential list has the wrong shape")
    rows = []
    for item in body["credentials"]:
        if not isinstance(item, dict):
            raise ValueError("pairing credential row must be an object")
        source, credential_id = item.get("source_id"), item.get("credential_id")
        digest, expires_at = item.get("token_sha256"), item.get("expires_at")
        if (not isinstance(source, str) or not source or not isinstance(credential_id, str)
                or not credential_id or not isinstance(digest, str) or not _SHA256_HEX.fullmatch(digest)
                or not isinstance(expires_at, str) or not _EXPIRES_AT.fullmatch(expires_at)):
            raise ValueError("pairing credential row is malformed")
        expires = datetime.strptime(expires_at[:-1] + "+0000", "%Y-%m-%dT%H:%M:%S%z")
        rows.append((source, bytes.fromhex(digest), credential_id, expires.timestamp()))
    return rows


class PairedCredentials:
    """The latest synced digests for this Vision's ``paired`` sources."""

    def __init__(self, paired_sources: Iterable[str], *, max_age_s: float = STALE_AFTER_S,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self.sources = frozenset(paired_sources)
        if not self.sources:
            raise ValueError("paired credentials need at least one paired source")
        self.max_age_s = float(max_age_s)
        self._clock = clock
        self._wall = wall
        # (synced_at, {source: ((digest, credential_id, expires_wall), ...)}); replaced whole.
        self._state: tuple[float, dict[str, tuple[tuple[bytes, str, float], ...]]] | None = None

    def replace(self, credentials: list[dict]) -> None:
        self.replace_rows(parse_listing({"role": ROLE, "credentials": credentials}))

    def replace_rows(self, rows: list[tuple[str, bytes, str, float]]) -> None:
        by_source: dict[str, list[tuple[bytes, str, float]]] = {}
        for source, digest, credential_id, expires in rows:
            if source in self.sources:  # static or unknown sources never take paired tokens
                by_source.setdefault(source, []).append((digest, credential_id, expires))
        self._state = (self._clock(), {source: tuple(items) for source, items in by_source.items()})

    def available(self) -> bool:
        state = self._state
        return state is not None and self._clock() - state[0] <= self.max_age_s

    def check(self, source: str, bearer_sha256: bytes) -> tuple[str, str | None]:
        """``("ok", credential_id)``, ``("unknown", None)`` or ``("unavailable", None)``."""
        state = self._state
        if state is None or self._clock() - state[0] > self.max_age_s:
            return "unavailable", None
        wall = self._wall()
        matched = None
        for digest, credential_id, expires in state[1].get(source, ()):
            # Compare every row so timing does not depend on which one matches.
            if hmac.compare_digest(digest, bearer_sha256) and expires > wall:
                matched = credential_id
        return ("ok", matched) if matched is not None else ("unknown", None)

    def check_any(self, bearer_sha256: bytes) -> str:
        if not self.available():
            return "unavailable"
        verdicts = [self.check(source, bearer_sha256)[0] for source in sorted(self.sources)]
        return "ok" if "ok" in verdicts else "unknown"


class PairingSync:
    """Fetch Fleet's credential list every ``interval_s`` on a daemon thread."""

    def __init__(self, credentials: PairedCredentials, *, url: str | None = None,
                 token: str | None = None, ca_file: str | None = None,
                 interval_s: float = SYNC_INTERVAL_S, timeout_s: float = 1.5,
                 fetch: Callable[[], object] | None = None,
                 on_cycle: Callable[[], None] | None = None) -> None:
        if fetch is None:
            if not url or not token:
                raise ValueError("pairing sync needs a Fleet URL and its sync token")
            if not url.startswith(("https://", "http://")):
                raise ValueError("pairing sync URL must be http(s)")
            verify: ssl.SSLContext | bool = (ssl.create_default_context(cafile=ca_file)
                                             if ca_file else True)
            endpoint = url.rstrip("/") + LIST_PATH
            headers = {"Authorization": f"Bearer {token}"}

            def fetch() -> object:
                with httpx.Client(verify=verify, timeout=timeout_s) as client:
                    response = client.get(endpoint, params={"role": ROLE}, headers=headers)
                    response.raise_for_status()
                    return response.json()

        self.credentials = credentials
        self.interval_s = float(interval_s)
        self._fetch = fetch
        self._on_cycle = on_cycle
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.failures = 0

    def run_once(self) -> None:
        try:
            self.credentials.replace_rows(parse_listing(self._fetch()))
        except Exception as exc:  # noqa: BLE001 - any failure keeps the last good list
            self.failures += 1
            # Never log the URL, headers or body: only the failure type.
            logger.warning("pairing credential sync failed error_type=%s", type(exc).__name__)
        if self._on_cycle is not None:
            try:
                self._on_cycle()
            except Exception:
                logger.exception("pairing credential enforcement scheduling failed")

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            self.run_once()
            self._stop.wait(max(0.0, self.interval_s - (time.monotonic() - started)))

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="rosy-vision-pairing-sync",
                                        daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout_s)
            self._thread = None
