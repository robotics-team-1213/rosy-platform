"""Parsers for the two AI PC asks. Neither result is a robot command.

Identity facts classify an obstacle. Choice candidates name one allowlisted
option or abstain. Stuck answers, meet orders, and ``cmd_vel`` stay outside
this module (D-523).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

THINGS = frozenset({"wall", "object", "robot", "person", "unknown"})
COMMAND_WORDS = frozenset({"WAIT", "YIELD", "RESUME", "ABORT", "MANUAL"})
MIN_CONFIDENCE = 0.7
MAX_AGE_S = 8.0
_IDENTITY_KEYS = frozenset({"thing", "confidence"})


@dataclass(frozen=True)
class IdentityFact:
    """One checked identity observation. ``state`` is ``OK`` or ``UNKNOWN``."""

    thing: str
    confidence: float | None
    observed_at: datetime | None
    age_s: float | None
    state: str
    profile_id: str
    source: str = "vlm"


@dataclass(frozen=True)
class ChoiceCandidate:
    """One allowlisted choice, or ``choice is None`` when the model abstains."""

    choice: str | None
    profile_id: str
    generation: str


def _unknown(profile_id: str) -> IdentityFact:
    return IdentityFact(
        thing="unknown", confidence=None, observed_at=None, age_s=None,
        state="UNKNOWN", profile_id=profile_id, source="vlm",
    )


def _abstain(profile_id: str, generation: str) -> ChoiceCandidate:
    return ChoiceCandidate(choice=None, profile_id=profile_id, generation=generation)


def _identifier(value: object) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if len(value) > 128 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def _aware(value: object) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _confidence(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        return None
    return number


def _clearance(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    return math.isfinite(number) and number >= 0.0


def parse_identity(
    *,
    cause: str,
    front_clearance_m: object,
    opened_at: object,
    captured_at: object,
    profile_id: object,
    expected_profile_id: object,
    payload: object,
    now: datetime,
    timeout_s: float = MAX_AGE_S,
    min_confidence: float = MIN_CONFIDENCE,
) -> IdentityFact:
    """Return an identity fact. A bad model reply is ``unknown``, not an exception.

    ``cause`` other than ``obstacle_ahead`` is a caller error and raises.
    ``lane_lost`` must not reach this parser.
    """
    if cause != "obstacle_ahead":
        raise ValueError("identity ask is only for obstacle_ahead")
    expected = _identifier(expected_profile_id)
    if expected is None:
        return _unknown("")
    opened = _aware(opened_at)
    captured = _aware(captured_at)
    clock = _aware(now)
    claimed = _identifier(profile_id)
    if (not _clearance(front_clearance_m) or opened is None or captured is None
            or clock is None or claimed != expected or not isinstance(payload, Mapping)
            or set(payload) != _IDENTITY_KEYS or timeout_s <= 0 or min_confidence < 0):
        return _unknown(expected)
    thing = payload.get("thing")
    confidence = _confidence(payload.get("confidence"))
    age_s = (clock - captured).total_seconds()
    if (thing not in THINGS or thing in COMMAND_WORDS or confidence is None
            or age_s < 0.0 or age_s > timeout_s or captured < opened):
        return _unknown(expected)
    if thing == "unknown" or confidence < min_confidence:
        return IdentityFact(
            thing="unknown", confidence=confidence, observed_at=captured, age_s=age_s,
            state="UNKNOWN", profile_id=expected, source="vlm",
        )
    return IdentityFact(
        thing=str(thing), confidence=confidence, observed_at=captured, age_s=age_s,
        state="OK", profile_id=expected, source="vlm",
    )


def _criteria(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping) or len(value) < 2:
        return None
    cleaned: dict[str, str] = {}
    for key, description in value.items():
        if (not isinstance(key, str) or not key or key != key.strip() or key in COMMAND_WORDS
                or not isinstance(description, str) or not description.strip()):
            return None
        cleaned[key] = description
    return cleaned


def _choice_of(response: object) -> str | None:
    if not isinstance(response, Mapping):
        return None
    answers: Any = response.get("answers")
    if not isinstance(answers, Mapping):
        return None
    decision: Any = answers.get("decision")
    if not isinstance(decision, Mapping):
        return None
    choice = decision.get("choice")
    if not isinstance(choice, str) or not choice or choice in COMMAND_WORDS:
        return None
    return choice


def _elapsed(value: object, timeout_s: float) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or timeout_s <= 0:
        return False
    elapsed = float(value)
    return math.isfinite(elapsed) and 0.0 <= elapsed <= timeout_s


def parse_choice(
    *,
    profile_id: object,
    expected_profile_id: object,
    generation: object,
    expected_generation: object,
    criteria: object,
    response: object,
    elapsed_s: object,
    timeout_s: float = MAX_AGE_S,
) -> ChoiceCandidate:
    """Return a choice that Fleet already allowlisted, or an abstention.

    Abstention is ``choice=None``. It is not a stuck answer and not a command.
    """
    expected = _identifier(expected_profile_id) or ""
    generation_id = _identifier(expected_generation) or ""
    allowed = _criteria(criteria)
    claimed = _identifier(profile_id)
    answered = _identifier(generation)
    if (allowed is None or claimed != expected or answered != generation_id
            or not expected or not generation_id or not _elapsed(elapsed_s, timeout_s)):
        return _abstain(expected, generation_id)
    choice = _choice_of(response)
    if choice not in allowed:
        return _abstain(expected, generation_id)
    return ChoiceCandidate(choice=choice, profile_id=expected, generation=generation_id)
