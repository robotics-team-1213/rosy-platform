"""Fail-closed traffic policy between perception and command arbitration."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from core_common.protocol.schemas import TrafficPolicyStatus
from core_features.traffic_policy.manager_helpers import (
    APPROACH_MIN_SCALE,
    RoadEvidence,
    SignalHeadEvidence,
    TrafficDecision,
    TrafficPolicyConfig,
    TrafficPolicyMode,
    _finite,
)

__all__ = [
    "APPROACH_MIN_SCALE",
    "RoadEvidence",
    "SignalHeadEvidence",
    "TrafficDecision",
    "TrafficPolicyConfig",
    "TrafficPolicyManager",
    "TrafficPolicyMode",
    "_finite",
]


class TrafficPolicyManager:
    def __init__(self, events, *, config: Optional[TrafficPolicyConfig] = None,
                 clock: Callable[[], float] = time.monotonic,
                 simulation_signal_control: bool = False) -> None:
        self._events = events
        self._config = config or TrafficPolicyConfig()
        self._clock = clock
        self._lock = threading.RLock()
        self._generation = 0
        self._evidence_revision = 0
        self._observation: Optional[RoadEvidence] = None
        self._received_at: Optional[float] = None
        self._signal_observation: Optional[SignalHeadEvidence] = None
        self._signal_received_at: Optional[float] = None
        self._stopped_at: Optional[float] = None
        self._staged_config: Optional[TrafficPolicyConfig] = None
        self._simulation_signal_control = bool(simulation_signal_control)
        self._simulation_signal_colour = "RED"
        self._status = TrafficPolicyStatus(
            mode=self._config.mode.value,
            state=(
                "DISABLED"
                if self._config.mode is TrafficPolicyMode.DISABLED
                else "HOLD"
            ),
            reason=("policy_disabled"
                    if self._config.mode is TrafficPolicyMode.DISABLED
                    else "no_road_evidence"),
            enforced=self._config.mode is TrafficPolicyMode.ENFORCED,
            map_id=self._config.map_id or None,
            scene_revision=self._config.scene_revision or None,
            policy_revision=self._config.policy_revision,
        )

    @property
    def mode(self) -> TrafficPolicyMode:
        with self._lock:
            return self._config.mode

    def set_mode(self, mode: TrafficPolicyMode | str) -> TrafficPolicyStatus:
        selected = (
            mode if isinstance(mode, TrafficPolicyMode)
            else TrafficPolicyMode(mode)
        )
        with self._lock:
            self._config = TrafficPolicyConfig(
                **{**self._config.__dict__, "mode": selected})
            self._generation += 1
            self._stopped_at = None
            if selected is TrafficPolicyMode.DISABLED:
                self._set_status(
                    "DISABLED", "policy_disabled", None, 1.0)
            else:
                self._set_status(
                    "HOLD", "no_road_evidence", None, 0.0)
            return self._status.model_copy()

    @staticmethod
    def _config_dict(config: TrafficPolicyConfig) -> dict:
        return {
            "mode": config.mode.value,
            "map_id": config.map_id,
            "scene_revision": config.scene_revision,
            "policy_revision": config.policy_revision,
            "junction_rule": config.junction_rule,
            "approach_distance_m": config.approach_distance_m,
            "stop_distance_m": config.stop_distance_m,
            "stop_dwell_s": config.stop_dwell_s,
            "stale_after_s": config.stale_after_s,
            "min_confidence": config.min_confidence,
            "proceed_speed_scale": config.proceed_speed_scale,
        }

    def configuration(self) -> dict:
        with self._lock:
            return {
                "active": self._config_dict(self._config),
                "staged": (
                    None
                    if self._staged_config is None
                    else self._config_dict(self._staged_config)
                ),
                "simulation_signal": {
                    "available": self._simulation_signal_control,
                    "colour": self._simulation_signal_colour,
                },
            }

    def stage(self, patch: dict, *, actor: str) -> dict:
        if type(patch) is not dict or not patch:
            raise ValueError("traffic policy patch is required")
        if not isinstance(actor, str) or not actor:
            raise ValueError("traffic policy actor is required")
        allowed = set(self._config_dict(self._config))
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError(
                "unsupported traffic policy fields: "
                + ", ".join(sorted(unknown)))
        with self._lock:
            values = {**self._config_dict(self._config), **patch}
            candidate = TrafficPolicyConfig(**values)
            self._staged_config = candidate
            self._events.publish(
                "nav.traffic_policy_staged",
                source="traffic_policy_manager",
                data={
                    "actor": actor,
                    "policy_revision": candidate.policy_revision,
                },
            )
            return self.configuration()

    def apply_staged(self, *, actor: str) -> dict:
        if not isinstance(actor, str) or not actor:
            raise ValueError("traffic policy actor is required")
        with self._lock:
            if self._staged_config is None:
                raise ValueError("no staged traffic policy")
            self._config = self._staged_config
            self._staged_config = None
            self._observation = None
            self._received_at = None
            self._signal_observation = None
            self._signal_received_at = None
            self._stopped_at = None
            self._generation += 1
            self._evidence_revision += 1
            if self._config.mode is TrafficPolicyMode.DISABLED:
                self._set_status(
                    "DISABLED", "policy_disabled", None, 1.0)
            else:
                self._set_status(
                    "HOLD", "no_road_evidence", None, 0.0)
            self._events.publish(
                "nav.traffic_policy_applied",
                source="traffic_policy_manager",
                data={
                    "actor": actor,
                    "policy_revision": self._config.policy_revision,
                    "mode": self._config.mode.value,
                },
            )
            return self.configuration()

    def set_simulation_signal(self, colour: str, *, actor: str) -> dict:
        if not self._simulation_signal_control:
            raise RuntimeError("simulation signal control unavailable")
        if colour not in ("RED", "YELLOW", "GREEN"):
            raise ValueError("unsupported simulation signal colour")
        if not isinstance(actor, str) or not actor:
            raise ValueError("simulation signal actor is required")
        with self._lock:
            self._simulation_signal_colour = colour
            self._events.publish(
                "sim.traffic_signal_changed",
                source="traffic_policy_manager",
                data={"actor": actor, "colour": colour},
            )
            return {"available": True, "colour": colour}

    def observe(self, observation: RoadEvidence,
                received_at: Optional[float] = None,
                source_now: Optional[float] = None) -> None:
        now = self._clock() if received_at is None else received_at
        if not _finite(now):
            raise ValueError("received_at must be finite")
        effective_received_at = float(now)
        if source_now is not None:
            if not _finite(source_now):
                raise ValueError("source_now must be finite")
            source_age = float(source_now) - observation.stamp
            if source_age < -0.1:
                raise ValueError("road evidence timestamp is in the future")
            effective_received_at -= max(0.0, source_age)
        with self._lock:
            self._observation = observation
            self._received_at = effective_received_at
            self._evidence_revision += 1
            if not observation.stop_line_visible:
                self._stopped_at = None

    def observe_signal(self, observation: SignalHeadEvidence,
                       received_at: Optional[float] = None,
                       source_now: Optional[float] = None) -> None:
        """Ingest measured-light evidence (D-337 §2). Fails closed on form."""
        now = self._clock() if received_at is None else received_at
        if not _finite(now):
            raise ValueError("received_at must be finite")
        effective_received_at = float(now)
        if source_now is not None:
            if not _finite(source_now):
                raise ValueError("source_now must be finite")
            source_age = float(source_now) - observation.stamp
            if source_age < -0.1:
                raise ValueError(
                    "signal head evidence timestamp is in the future")
            effective_received_at -= max(0.0, source_age)
        with self._lock:
            self._signal_observation = observation
            self._signal_received_at = effective_received_at
            self._evidence_revision += 1

    def reset(self, reason: str = "reset") -> TrafficPolicyStatus:
        with self._lock:
            self._observation = None
            self._received_at = None
            self._signal_observation = None
            self._signal_received_at = None
            self._stopped_at = None
            self._generation += 1
            self._evidence_revision += 1
            if self._config.mode is TrafficPolicyMode.DISABLED:
                self._set_status(
                    "DISABLED", "policy_disabled", None, 1.0)
            else:
                self._set_status(
                    "HOLD", "no_road_evidence", None, 0.0)
            self._events.publish(
                "nav.traffic_policy_reset",
                source="traffic_policy_manager",
                data={"reason": str(reason)},
            )
            return self._status.model_copy()

    def status(self) -> TrafficPolicyStatus:
        with self._lock:
            return self._status.model_copy()

    def gate(self, linear: float, angular: float,
             now: Optional[float] = None) -> TrafficDecision:
        if not _finite(linear) or not _finite(angular):
            raise ValueError("traffic candidate must be finite")
        current = self._clock() if now is None else now
        if not _finite(current):
            raise ValueError("traffic policy clock must be finite")
        with self._lock:
            allowed_linear, allowed_angular = self._evaluate(
                float(linear), float(angular), float(current))
            return TrafficDecision(
                linear=allowed_linear,
                angular=allowed_angular,
                generation=self._generation,
                evidence_revision=self._evidence_revision,
                mode=self._config.mode,
                policy_revision=self._config.policy_revision,
            )

    def apply_if_current(self, decision: TrafficDecision,
                         apply: Callable[[TrafficDecision], None]) -> bool:
        with self._lock:
            if (
                decision.generation != self._generation
                or decision.evidence_revision != self._evidence_revision
                or decision.mode is not self._config.mode
                or decision.policy_revision != self._config.policy_revision
            ):
                return False
            apply(decision)
            return True

    def _evaluate(self, linear: float, angular: float,
                  now: float) -> tuple[float, float]:
        if self._config.mode is TrafficPolicyMode.DISABLED:
            self._set_status("DISABLED", "policy_disabled", None, 1.0)
            return linear, angular

        state, reason, age, scale = self._verdict(now)
        self._set_status(state, reason, age, scale, now)
        if self._config.mode is TrafficPolicyMode.MONITOR_ONLY:
            return linear, angular
        if state in ("FOLLOW", "APPROACH", "PROCEED"):
            # D-735: moving candidates keep curvature; stationary timed turns keep angular speed.
            return linear * scale, angular * (scale if linear != 0.0 else 1.0)
        return 0.0, 0.0

    def _verdict(self, now: float):
        observation = self._observation
        if observation is None or self._received_at is None:
            return "HOLD", "no_road_evidence", None, 0.0
        age = now - self._received_at
        if age < 0.0 or age > self._config.stale_after_s:
            return "HOLD", "road_evidence_stale", age, 0.0
        if observation.map_id != self._config.map_id:
            return "HOLD", "map_mismatch", age, 0.0
        if observation.scene_revision != self._config.scene_revision:
            return "HOLD", "scene_mismatch", age, 0.0
        if observation.signal_conflict:
            return "HOLD", "signal_conflict", age, 0.0
        if not observation.stop_line_visible:
            return "FOLLOW", "clear_road", age, 1.0
        if observation.stop_line_confidence < self._config.min_confidence:
            return "HOLD", "stop_line_low_confidence", age, 0.0
        distance = observation.stop_line_distance_m
        if distance is None:
            return "HOLD", "stop_distance_unavailable", age, 0.0
        if distance > self._config.approach_distance_m:
            return "FOLLOW", "stop_line_far", age, 1.0
        if distance > self._config.stop_distance_m:
            span = (
                self._config.approach_distance_m
                - self._config.stop_distance_m
            )
            progress = (distance - self._config.stop_distance_m) / span
            scale = max(APPROACH_MIN_SCALE, min(1.0, progress))
            return "APPROACH", "stop_line_approach", age, scale
        if self._stopped_at is None:
            self._stopped_at = now
            return "STOP_REQUIRED", "stop_dwell", age, 0.0
        if now - self._stopped_at < self._config.stop_dwell_s:
            return "STOP_REQUIRED", "stop_dwell", age, 0.0
        head = self._usable_signal_head(now)
        if self._config.junction_rule == "stop_and_go":
            if observation.signal_colour is None and head is None:
                return (
                    "PROCEED", "unsignalized_proceed", age,
                    self._config.proceed_speed_scale,
                )
            return "HOLD", "signal_unexpected", age, 0.0
        colour = observation.signal_colour
        if head is not None and head.colour is not None:
            if colour is None:
                if head.confidence < self._config.min_confidence:
                    return (
                        "WAIT_SIGNAL", "signal_low_confidence", age, 0.0)
                if head.colour == "GREEN":
                    return (
                        "PROCEED", "signal_green", age,
                        self._config.proceed_speed_scale,
                    )
                return (
                    "WAIT_SIGNAL",
                    f"signal_{head.colour.lower()}",
                    age,
                    0.0,
                )
            if head.colour != colour:
                return "HOLD", "signal_source_conflict", age, 0.0
        if colour is None:
            if head is not None:
                return "WAIT_SIGNAL", "signal_dark", age, 0.0
            return "WAIT_SIGNAL", "signal_unknown", age, 0.0
        confidence = observation.signal_confidence
        if head is not None and head.colour == colour:
            confidence = min(confidence, head.confidence)
        if confidence < self._config.min_confidence:
            return "WAIT_SIGNAL", "signal_low_confidence", age, 0.0
        if colour == "GREEN":
            return (
                "PROCEED", "signal_green", age,
                self._config.proceed_speed_scale,
            )
        return (
            "WAIT_SIGNAL",
            f"signal_{colour.lower()}",
            age,
            0.0,
        )

    def _usable_signal_head(
            self, now: float) -> Optional[SignalHeadEvidence]:
        """Fresh, stable, unfrozen, scene-bound measured light — or None."""
        head = self._signal_observation
        if head is None or self._signal_received_at is None:
            return None
        age = now - self._signal_received_at
        if age < 0.0 or age > self._config.stale_after_s:
            return None
        if head.frozen or not head.stable:
            return None
        if head.map_id != self._config.map_id \
                or head.scene_revision != self._config.scene_revision:
            return None
        return head

    def _set_status(self, state: str, reason: str,
                    age: Optional[float], scale: float,
                    now: Optional[float] = None) -> None:
        observation = self._observation
        current = self._clock() if now is None else now
        head = self._signal_observation
        head_age: Optional[float] = None
        head_frozen = False
        source_kind = "camera"
        if head is not None and self._signal_received_at is not None:
            head_age = max(0.0, current - self._signal_received_at)
            head_frozen = bool(head.frozen)
            if self._usable_signal_head(current) is not None:
                # D-337 §5: "fused" only while the measured light is usable.
                source_kind = "fused"
        self._status = TrafficPolicyStatus(
            mode=self._config.mode.value,
            state=state,
            reason=reason,
            enforced=self._config.mode is TrafficPolicyMode.ENFORCED,
            map_id=self._config.map_id or None,
            scene_revision=self._config.scene_revision or None,
            policy_revision=self._config.policy_revision,
            junction_rule=self._config.junction_rule,
            evidence_revision=self._evidence_revision,
            age_s=None if age is None else round(max(0.0, age), 3),
            stop_line_visible=bool(
                observation and observation.stop_line_visible),
            stop_line_distance_m=(
                observation.stop_line_distance_m if observation else None),
            crosswalk_visible=bool(
                observation and observation.crosswalk_visible),
            signal_colour=(observation.signal_colour if observation else None),
            signal_confidence=(
                observation.signal_confidence if observation else 0.0),
            signal_conflict=bool(
                observation and observation.signal_conflict),
            signal_source_kind=source_kind,
            signal_head_age_s=(
                None if head_age is None else round(head_age, 3)),
            signal_head_frozen=head_frozen,
            linear_scale=float(scale),
        )
