"""Fuse tier (stack height) readings into one cell plan hint. Sources may only raise or hold, never lower.

Tier is 1 or 2. Manifest (int) and parallax/wrist (dict with "tier") are primary; observer (dict with "tier", "age_s",
"epoch", optional "expect_epoch") and judge (a string such as "2" or "tier2") may only raise or hold.
"""
from __future__ import annotations

OBSERVER_TTL_S = 120.0


def _tier(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v in (1, 2) else None
    if isinstance(v, dict):
        return _tier(v.get("tier"))
    if isinstance(v, str):
        return {"1": 1, "tier1": 1, "2": 2, "tier2": 2}.get(v.strip().lower())
    return None


def _observer_fresh(o) -> bool:
    if not isinstance(o, dict):
        return False
    age = o.get("age_s")
    if not isinstance(age, (int, float)) or age > OBSERVER_TTL_S:
        return False
    return o.get("expect_epoch") is None or o.get("epoch") == o.get("expect_epoch")


def fuse(manifest, parallax, observer, judge, wrist) -> dict:
    """-> {layers_below 0|1, top_first, hold, sources, reason}."""
    man = _tier(manifest)
    got = {"parallax": _tier(parallax), "wrist": _tier(wrist),
           "observer": _tier(observer) if _observer_fresh(observer) else None, "judge": _tier(judge)}
    if man is not None:
        got = {"manifest": man, **got}
    got = {k: v for k, v in got.items() if v is not None}
    tiers = set(got.values())
    top = max(tiers, default=1)
    disagree = len(tiers) > 1
    hold = (disagree and man is None) or (len(got) < 2 and man is None)
    reason = ("no source answered" if not got else "disagreement without a manifest" if disagree and man is None
              else "fewer than two sources and no manifest" if hold else "ok")
    return {"layers_below": 1 if top == 2 else 0, "top_first": top == 2, "hold": hold,
            "sources": sorted(got), "reason": reason}
