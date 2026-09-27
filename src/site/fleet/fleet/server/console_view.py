"""Presentation-only values exposed by the Fleet console."""

from __future__ import annotations

from typing import Optional

from fleet.swarm.transport import RobotApiError


_INTERNAL_MISSION_KEYS = ("route", "settled_ticks")
STREAM_STALE_AFTER_S = 1.0
STREAM_RATE_FLOOR_HZ = 2.0


def _stream_evidence(age_s: Optional[float], *, connected: bool,
                     error: Optional[str], source: str,
                     rate_hz: Optional[float] = None, sample_count: int = 0) -> dict:
    """Judge relay observations on the server; send age is not robot receipt."""
    if error or not connected:
        state, reason = "disconnected", "stream_error" if error else "transport_down"
    elif age_s is None:
        state, reason = "unavailable", "no_sample"
    elif age_s > STREAM_STALE_AFTER_S:
        state, reason = "delayed", "sample_too_old"
    elif sample_count >= 2 and rate_hz is not None and rate_hz < STREAM_RATE_FLOOR_HZ:
        state, reason = "delayed", "rate_below_floor"
    else:
        state, reason = "fresh", "sample_within_limit"
    return {"state": state, "age_s": age_s, "reason": reason,
            "stale_after_s": STREAM_STALE_AFTER_S, "source": source}


def _formation_stream_evidence(stats, leader: str, assignment) -> dict:
    if stats is None:
        return {}
    evidence = {
        leader: _stream_evidence(
            stats.leader_age_s, connected=stats.leader_last_error is None,
            error=stats.leader_last_error, source="leader_rx",
            rate_hz=stats.leader_rx_hz, sample_count=stats.leader_frames,
        )
    }
    for rid in assignment:
        evidence[rid] = _stream_evidence(
            stats.follower_last_tx_age_s.get(rid),
            connected=stats.follower_connected.get(rid) is True,
            error=stats.follower_last_error.get(rid), source="follower_tx",
            rate_hz=stats.follower_tx_hz.get(rid),
            sample_count=stats.follower_tx.get(rid, 0),
        )
    return evidence


def _shown(mission: Optional[dict]) -> Optional[dict]:
    if mission is None:
        return None
    return {k: v for k, v in mission.items() if k not in _INTERNAL_MISSION_KEYS}


def _error_of(exc: BaseException) -> dict:
    """Show a robot refusal separately from a reachability failure."""
    if isinstance(exc, RobotApiError):
        return {"reachable": True, "code": exc.code, "message": str(exc)}
    return {"reachable": False, "code": type(exc).__name__, "message": str(exc) or type(exc).__name__}
