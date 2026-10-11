"""Measured base, arm and payload footprint profiles.

The profile is deliberately strict: an unmeasured state can be represented for
planning, but it cannot be selected for Nav2.  No dimensions are invented in
this module; the measured polygon, payload centre of gravity and MoveIt scene
revision must come from the commissioning record.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


def _number(name: str, value: Any, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or (number < 0.0 if allow_zero else number <= 0.0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be a finite {qualifier} number")
    return number


def _coordinate(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _point_list(value: Any, *, required: bool) -> tuple[tuple[float, float], ...]:
    if value is None and not required:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("footprint must be a list of [x, y] points")
    points: list[tuple[float, float]] = []
    for index, point in enumerate(value):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"footprint point {index} must contain x and y")
        points.append(
            (
                _coordinate(f"footprint[{index}].x", point[0]),
                _coordinate(f"footprint[{index}].y", point[1]),
            )
        )
    if required and len(points) < 3:
        raise ValueError("a measured footprint requires at least three points")
    return tuple(points)


def _cog(value: Any, *, required: bool) -> tuple[float, float, float] | None:
    if value is None and not required:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("payload.center_of_gravity_m must contain x, y and z")
    return tuple(
        _coordinate(f"payload.center_of_gravity_m[{index}]", item)
        for index, item in enumerate(value)
    )  # type: ignore[return-value]


@dataclass(frozen=True)
class FootprintProfile:
    """One measured configuration of the mobile manipulator."""

    state: str
    measured: bool
    footprint: tuple[tuple[float, float], ...]
    clearance_m: float | None
    payload_mass_kg: float | None
    payload_cog_m: tuple[float, float, float] | None
    max_linear_mps: float | None
    max_angular_rps: float | None
    moveit_scene_revision: str | None

    @classmethod
    def from_mapping(cls, state: str, values: Mapping[str, Any]) -> "FootprintProfile":
        if not isinstance(state, str) or not state.strip():
            raise ValueError("footprint state must be a non-empty string")
        if not isinstance(values, Mapping):
            raise ValueError(f"footprint profile {state!r} must be a mapping")
        measured = values.get("measured", False)
        if not isinstance(measured, bool):
            raise ValueError("footprint profile measured must be boolean")

        payload = values.get("payload", {})
        if payload is None and not measured:
            payload = {}
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be a mapping")
        required = measured
        mass = payload.get("mass_kg")
        cog = payload.get("center_of_gravity_m")
        if required and mass is None:
            raise ValueError("a measured profile requires payload.mass_kg")
        mass_value = None if mass is None else _number("payload.mass_kg", mass, allow_zero=True)
        cog_value = _cog(cog, required=required)

        clearance = values.get("clearance_m")
        if required and clearance is None:
            raise ValueError("a measured profile requires clearance_m")
        clearance_value = None if clearance is None else _number("clearance_m", clearance)

        linear = values.get("max_linear_mps")
        angular = values.get("max_angular_rps")
        if required and (linear is None or angular is None):
            raise ValueError("a measured profile requires motion limits")
        linear_value = None if linear is None else _number("max_linear_mps", linear)
        angular_value = None if angular is None else _number("max_angular_rps", angular)

        scene = values.get("moveit_scene_revision", "")
        if not isinstance(scene, str):
            raise ValueError("moveit_scene_revision must be a string")
        if required and not scene.strip():
            raise ValueError("a measured profile requires moveit_scene_revision")

        return cls(
            state=state.strip(),
            measured=measured,
            footprint=_point_list(values.get("footprint"), required=required),
            clearance_m=clearance_value,
            payload_mass_kg=mass_value,
            payload_cog_m=cog_value,
            max_linear_mps=linear_value,
            max_angular_rps=angular_value,
            moveit_scene_revision=scene.strip() or None,
        )

    @property
    def operational(self) -> bool:
        """Whether this profile is complete enough to select for Nav2."""

        return (
            self.measured
            and len(self.footprint) >= 3
            and self.moveit_scene_revision is not None
        )


def load_footprint_profile(path: str | Path, state: str) -> FootprintProfile:
    """Load a named profile from ``motion_profiles.profiles``."""

    if not isinstance(state, str) or not state.strip():
        raise ValueError("footprint state must be a non-empty string")
    profile_path = Path(path)
    try:
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ValueError(f"cannot read footprint profile: {profile_path}") from exc
    if not isinstance(data, Mapping):
        raise ValueError("footprint profile file must be a YAML mapping")
    root = data.get("motion_profiles", data)
    if not isinstance(root, Mapping):
        raise ValueError("motion_profiles must be a YAML mapping")
    profiles = root.get("profiles", {})
    if not isinstance(profiles, Mapping) or state not in profiles:
        raise ValueError(f"unknown footprint state: {state!r}")
    return FootprintProfile.from_mapping(state, profiles[state])
