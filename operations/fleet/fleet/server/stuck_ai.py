"""D-577 shadow: Fleet asks the AI PC about one open stuck and keeps the facts it returns.

Facts only (D-516, D-523): a fact names what is happening (``kind``, ``value``, ``confidence``),
never what to do. A reply that carries a command word anywhere, an unknown kind, or a malformed
fact is dropped whole. Facts are shown on the stuck row (shadow, D-577 6); no rule reads them.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

import httpx

#: D-577 3: the first fact kinds. Adding one is an amendment of D-577.
KINDS = frozenset({
    "wait_cycle_confirmed", "wait_cycle_stale_input", "waiting_but_moving", "livelock", "stalled",
    "unknown_occupancy_long", "lane_obs_vs_range", "lane_conf_collapse", "shadow_active_drift",
    "pose_vs_paint", "pose_sources_disagree", "obstacle_identity"})
COMMAND_WORDS = frozenset({"WAIT", "RESUME", "BACK_AND_RETRY", "YIELD", "ABORT", "MANUAL", "STOP", "GO"})
_FIELDS = frozenset({"kind", "robot_ids", "value", "confidence", "evidence", "source", "observed_at", "ttl_s"})
MAX_FACTS = 32
MAX_TTL_S = 8.0


def _has_command(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().upper() in COMMAND_WORDS
    if isinstance(value, Mapping):
        return any(_has_command(k) or _has_command(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_has_command(v) for v in value)
    return False


def parse_facts(payload: Any) -> list[dict]:
    """The checked facts of one AI PC reply. Raises ValueError on anything outside D-577 3."""
    facts = payload.get("facts") if isinstance(payload, Mapping) else None
    if not isinstance(facts, list) or len(facts) > MAX_FACTS:
        raise ValueError("reply must be {'facts': [...]} with at most 32 facts")
    if _has_command(payload):
        raise ValueError("reply carries a command word")
    checked = []
    for fact in facts:
        if not isinstance(fact, Mapping) or not set(fact) <= _FIELDS or fact.get("kind") not in KINDS:
            raise ValueError(f"not a D-577 fact: {fact!r:.120}")
        confidence, ttl = fact.get("confidence"), fact.get("ttl_s")
        for number, low, high in ((confidence, 0.0, 1.0), (ttl, 1e-9, MAX_TTL_S)):
            if (isinstance(number, bool) or not isinstance(number, (int, float))
                    or not math.isfinite(number) or not low <= number <= high):
                raise ValueError(f"confidence must be 0..1 and ttl_s 0..{MAX_TTL_S:g}: {fact!r:.120}")
        checked.append(dict(fact))
    return checked


class HttpSituationAsk:
    """POST <ai_url>/v1/situation with one stuck row; returns its checked facts."""

    def __init__(self, url: str, *, token: Optional[str] = None, timeout_s: float = 3.0) -> None:
        self._url = url.rstrip("/") + "/v1/situation"
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.timeout_s = timeout_s

    async def __call__(self, situation: dict) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout_s) as http:
            response = await http.post(self._url, json=situation, headers=self._headers)
            response.raise_for_status()
            return parse_facts(response.json())
