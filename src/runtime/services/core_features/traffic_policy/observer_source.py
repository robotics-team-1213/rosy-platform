"""Subject: poll the read-only signal observer for measured-light evidence.

D-337: the robot's only second signal source is the observer's measured
light (`GET /observed`). This module is transport + parse — it never
touches the verdict; the TrafficPolicyManager fuses what it returns.

Contract mirrors the observer's own rules: a poll that cannot produce a
confirmed, unfrozen reading is silence (None) — a fabricated head is
never built. The stable (debounced) layer decides lit/pending, the raw
lamp layer only lends its per-frame confidence (the stable layer has
none). Colour comes from the operator's position map (`roi_map`), not
from the observer's colour `group` — interpretation belongs to the
operator's map (observer design §2), so a rewired head is the operator's
configuration error to fix, visible as a held junction.

The default transport imports httpx lazily so ROS-free imports and host
tests do not require it; tests inject a fake transport.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable, Optional

from core_features.traffic_policy.manager import SignalHeadEvidence

#: Operator position-map targets. Exactly these colour roles exist.
_COLOUR_TARGETS = ("red", "yellow", "green")

#: Transport: (url, timeout_s) -> parsed JSON dict. Raises on any failure.
Transport = Callable[[str, float], dict]


class SignalObserverConfigError(ValueError):
    """The observer source configuration is not usable."""


class ObserverHttpError(RuntimeError):
    """Non-200 response from the observer (e.g. 503 NO_FRAME)."""

    def __init__(self, status_code: int, body: object = None) -> None:
        super().__init__(f"observer http {status_code}: {body}")
        self.status_code = int(status_code)


def _finite(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


@dataclass(frozen=True)
class SignalObserverSourceConfig:
    """Operator-declared observer binding. Empty binding = feature off (T3)."""

    url: str
    roi_map: dict[str, str]
    timeout_s: float = 1.0
    poll_interval_s: float = 0.5

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) \
                or not self.url.strip().lower().startswith(
                    ("http://", "https://")):
            raise SignalObserverConfigError(
                "observer url must be an http(s) URL")
        for name in ("timeout_s", "poll_interval_s"):
            value = getattr(self, name)
            if not _finite(value) or float(value) <= 0.0:
                raise SignalObserverConfigError(
                    f"observer {name} must be finite and positive")
        if not isinstance(self.roi_map, dict) or not self.roi_map:
            raise SignalObserverConfigError(
                "roi_map must map observer lamp names to signal colours")
        targets: list[str] = []
        for name, colour in self.roi_map.items():
            if not isinstance(name, str) or not name.strip():
                raise SignalObserverConfigError(
                    "roi_map lamp names must be non-empty strings")
            if colour not in _COLOUR_TARGETS:
                raise SignalObserverConfigError(
                    f"roi_map target must be one of {_COLOUR_TARGETS}")
            if colour in targets:
                raise SignalObserverConfigError(
                    f"roi_map maps two lamps to {colour}")
            targets.append(colour)


def parse_observed(payload: object, config: SignalObserverSourceConfig, *,
                   map_id: str, scene_revision: str
                   ) -> Optional[SignalHeadEvidence]:
    """One `/observed` payload -> evidence, or None for silence.

    Silence (None): frozen frame (the server already downgraded stable to
    UNKNOWN), any lamp still pending debounce, or a malformed body. A
    confirmed frame yields evidence even with zero or plural lamps lit —
    that is real evidence the fusion reads as `signal_dark`.
    """
    if not isinstance(payload, dict):
        raise ValueError("observed payload must be an object")
    stamp = payload.get("ts")
    if not _finite(stamp):
        raise ValueError("observed payload ts must be finite")
    if bool(payload.get("frozen")):
        return None
    lamps = payload.get("lamps")
    stable = payload.get("stable")
    if not isinstance(lamps, dict) or not isinstance(stable, dict):
        raise ValueError("observed payload needs lamps and stable objects")
    lit_by_colour: dict[str, bool] = {}
    confidences: list[float] = []
    for name, colour in config.roi_map.items():
        entry = stable.get(name)
        if not isinstance(entry, dict):
            raise ValueError(f"stable layer is missing lamp {name!r}")
        if entry.get("pending") is True or entry.get("lit") is None:
            return None
        lit = entry.get("lit")
        if not isinstance(lit, bool):
            raise ValueError(f"stable lamp {name!r} lit must be a boolean")
        raw = lamps.get(name)
        if not isinstance(raw, dict) or not _finite(raw.get("confidence")) \
                or not 0.0 <= float(raw["confidence"]) <= 1.0:
            raise ValueError(f"raw lamp {name!r} needs a valid confidence")
        lit_by_colour[colour] = lit
        confidences.append(float(raw["confidence"]))
    return SignalHeadEvidence(
        stamp=float(stamp),
        map_id=map_id,
        scene_revision=scene_revision,
        red=lit_by_colour.get("red", False),
        yellow=lit_by_colour.get("yellow", False),
        green=lit_by_colour.get("green", False),
        confidence=min(confidences),
        frozen=False,
        stable=True,
    )


def _httpx_get(url: str, timeout_s: float) -> dict:
    """Default transport: one GET, JSON only on 200, errors raise."""
    import httpx  # lazy: ROS-free imports and host tests do not need it

    response = httpx.get(url, timeout=timeout_s)
    if response.status_code != 200:
        raise ObserverHttpError(
            response.status_code,
            response.json() if response.content else None,
        )
    return response.json()


class SignalObserverPoller:
    """One-shot poll helper. Scheduling/threading is the T3 wiring's job."""

    def __init__(self, config: SignalObserverSourceConfig, *,
                 map_id: str, scene_revision: str,
                 transport: Optional[Transport] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._config = config
        self._map_id = map_id
        self._scene_revision = scene_revision
        self._transport: Transport = transport or _httpx_get
        self._clock = clock
        #: Last server-side frame age (s) for T3 receipt compensation.
        self.last_age_s: Optional[float] = None
        #: Last poll outcome for T3 readback: confirmed | frozen | pending |
        #: http_error | bad_payload.
        self.last_outcome: str = "never_polled"

    def poll(self) -> Optional[SignalHeadEvidence]:
        try:
            payload = self._transport(
                self._config.url, self._config.timeout_s)
        except Exception:  # noqa: BLE001 — any transport failure is silence
            self.last_outcome = "http_error"
            self.last_age_s = None
            return None
        if not isinstance(payload, dict) or not _finite(payload.get("ts")):
            self.last_outcome = "bad_payload"
            self.last_age_s = None
            return None
        self.last_age_s = (
            float(payload.get("age_s"))
            if _finite(payload.get("age_s"))
            else None
        )
        if bool(payload.get("frozen")):
            self.last_outcome = "frozen"
            return None
        try:
            evidence = parse_observed(
                payload, self._config,
                map_id=self._map_id, scene_revision=self._scene_revision)
        except ValueError:
            self.last_outcome = "bad_payload"
            return None
        if evidence is None:  # pending debounce
            self.last_outcome = "pending"
            return None
        self.last_outcome = "confirmed"
        return evidence
