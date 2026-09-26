"""통역기. "이렇게 해"를 로봇 일 또는 현장 명령으로 바꾼다.

ROS 토픽 이름은 받지 않는다. 기본 API(/api/v1/..., /api/fleet/...)는 그대로다.
이 모듈은 그 주소를 고를 뿐이고, 실행은 각 서버가 한다.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass

FORBIDDEN_KEYS = frozenset({"cmd_vel", "image", "twist"})
MAX_STEPS = 8


class IntentError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Call:
    verb: str
    method: str
    path: str
    body: dict
    kind: str | None
    scope: str
    robot: str | None


@dataclass(frozen=True)
class _Verb:
    scope: str
    method: str
    path: str
    kind: str | None
    fields: frozenset[str]


_VERBS: dict[str, _Verb] = {
    "navigate": _Verb("robot", "POST", "/api/v1/navigation/goal", "NAVIGATE",
                      frozenset({"x", "y", "yaw", "waypoint"})),
    "home": _Verb("robot", "POST", "/api/v1/navigation/home", "RETURN_HOME", frozenset()),
    "cancel": _Verb("robot", "POST", "/api/v1/navigation/cancel", None, frozenset()),
    "stop": _Verb("robot", "POST", "/api/v1/safety/stop", None, frozenset()),
    "move": _Verb("robot", "POST", "/api/v1/teleop", "MOVE", frozenset({"linear", "angular"})),
    "follow": _Verb("robot", "POST", "/api/v1/swarm/follow", "FOLLOW",
                    frozenset({"target_robot_id", "distance", "lateral", "max_speed",
                               "stream_timeout_ms", "source"})),
    "follow_cancel": _Verb("robot", "POST", "/api/v1/swarm/cancel", None, frozenset()),
    "dock": _Verb("robot", "POST", "/api/v1/docking/dock", "DOCK", frozenset({"dock"})),
    "undock": _Verb("robot", "POST", "/api/v1/docking/undock", "DOCK", frozenset()),
    "formation_start": _Verb("site", "POST", "/api/fleet/formation/start", None,
                             frozenset({"leader", "formation", "spacing", "max_speed", "members"})),
    "formation_stop": _Verb("site", "POST", "/api/fleet/formation/stop", None, frozenset()),
    "formation_resume": _Verb("site", "POST", "/api/fleet/formation/resume", None, frozenset()),
    "estop": _Verb("site", "POST", "/api/fleet/estop", None, frozenset()),
}

_FIELD_SCHEMAS = {
    "x": {"type": "number"},
    "y": {"type": "number"},
    "yaw": {"type": "number"},
    "waypoint": {"type": "string"},
    "linear": {"type": "number"},
    "angular": {"type": "number"},
    "target_robot_id": {"type": "string"},
    "distance": {"type": "number"},
    "lateral": {"type": "number"},
    "max_speed": {"type": "number"},
    "stream_timeout_ms": {"type": "integer"},
    "source": {"type": "string"},
    "dock": {"type": "string"},
    "leader": {"type": "string"},
    "formation": {"type": "string"},
    "spacing": {"type": "number"},
    "members": {"type": "array", "items": {"type": "string"}},
    "robot": {"type": "string"},
}


def verbs() -> tuple[str, ...]:
    return tuple(_VERBS)


def request_schema() -> dict:
    """Return the OpenAPI schema for the JSON intent grammar accepted by interpret()."""
    unknown_fields = set().union(*(spec.fields for spec in _VERBS.values())) - set(_FIELD_SCHEMAS)
    if unknown_fields:
        raise RuntimeError(f"intent fields lack OpenAPI types: {', '.join(sorted(unknown_fields))}")

    variants = []
    for verb, spec in _VERBS.items():
        properties = {
            "do": {"type": "string", "const": verb},
            "robot": deepcopy(_FIELD_SCHEMAS["robot"]),
        }
        properties.update({field: deepcopy(_FIELD_SCHEMAS[field]) for field in spec.fields})
        variant = {
            "type": "object",
            "properties": properties,
            "required": ["do"],
            "additionalProperties": False,
        }
        if verb == "navigate":
            variant["anyOf"] = [{"required": ["x", "y"]}, {"required": ["waypoint"]}]
        elif verb == "follow":
            variant["required"].append("target_robot_id")
        elif verb == "formation_start":
            variant["required"].append("leader")
        variants.append(variant)

    step_schema = {"oneOf": variants}
    sequence_schema = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": deepcopy(step_schema),
                "minItems": 1,
                "maxItems": MAX_STEPS,
            },
        },
        "required": ["steps"],
        "additionalProperties": False,
    }
    return {
        "title": "FleetIntentRequest",
        "description": "A single intent or an ordered sequence interpreted by Fleet.",
        "oneOf": [step_schema, sequence_schema],
    }


def loads(text: str) -> dict:
    """JSON 또는 YAML 문서를 같은 딕셔너리로 읽는다."""
    stripped = text.strip()
    if not stripped:
        raise IntentError("EMPTY", "empty document")
    if stripped[0] in "{[":
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise IntentError("MALFORMED", "document is not JSON") from exc
    else:
        try:
            import yaml
        except ImportError as exc:
            raise IntentError("YAML_UNAVAILABLE", "YAML parser is not installed") from exc
        data = yaml.safe_load(stripped)
    if not isinstance(data, dict):
        raise IntentError("NOT_A_DOCUMENT", "document must be an object")
    return data


def interpret(document: dict) -> list[Call]:
    if not isinstance(document, dict):
        raise IntentError("NOT_A_DOCUMENT", "document must be an object")
    if "steps" in document:
        steps = document["steps"]
        if not isinstance(steps, list) or not steps:
            raise IntentError("EMPTY", "steps must be a non-empty list")
        if len(steps) > MAX_STEPS:
            raise IntentError("TOO_LONG", f"at most {MAX_STEPS} steps")
        extra = set(document) - {"steps"}
        if extra:
            raise IntentError("UNKNOWN_FIELD", ", ".join(sorted(extra)))
        return [_one(step) for step in steps]
    return [_one(document)]


def _one(step: object) -> Call:
    if not isinstance(step, dict):
        raise IntentError("NOT_A_STEP", "each step is an object")
    if FORBIDDEN_KEYS & {str(key).lower() for key in step}:
        raise IntentError("FORBIDDEN", "cmd_vel, image, and twist are not a request")
    verb = step.get("do")
    spec = _VERBS.get(verb) if isinstance(verb, str) else None
    if spec is None:
        raise IntentError("UNKNOWN_VERB", f"unknown do: {verb}")
    unknown = set(step) - {"do", "robot"} - spec.fields
    if unknown:
        raise IntentError("UNKNOWN_FIELD", ", ".join(sorted(str(item) for item in unknown)))
    body = {key: step[key] for key in spec.fields if key in step}
    _require(verb, body)
    robot = step.get("robot")
    if "robot" in step:
        _validate_value("robot", robot)
    for field, value in body.items():
        _validate_value(field, value)
    return Call(verb, spec.method, spec.path, body, spec.kind, spec.scope, robot)


def _require(verb: str, body: dict) -> None:
    if verb == "navigate":
        has_point = body.get("x") is not None and body.get("y") is not None
        if not has_point and not body.get("waypoint"):
            raise IntentError("MISSING", "navigate needs x and y, or a waypoint")
        if has_point:
            for field in ("x", "y", "yaw"):
                if field not in body:
                    continue
                value = body[field]
                if isinstance(value, bool) or not isinstance(value, (int, float)) \
                        or not math.isfinite(value):
                    raise IntentError("INVALID_NUMBER", f"{field} must be a finite number")
    if verb == "follow" and not body.get("target_robot_id"):
        raise IntentError("MISSING", "follow needs target_robot_id")
    if verb == "follow" and body.get("source") == "peer":
        raise IntentError("FORBIDDEN", "peer follow is not scatterable")
    if verb == "formation_start" and not body.get("leader"):
        raise IntentError("MISSING", "formation_start needs leader")


def _validate_value(field: str, value: object) -> None:
    expected = _FIELD_SCHEMAS[field]
    field_type = expected["type"]
    if field_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise IntentError("INVALID_NUMBER", f"{field} must be a finite number")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise IntentError("INVALID_NUMBER", f"{field} must be a finite number")
    elif field_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise IntentError("INVALID_FIELD_TYPE", f"{field} must be an integer")
    elif field_type == "string":
        if not isinstance(value, str):
            raise IntentError("INVALID_FIELD_TYPE", f"{field} must be a string")
    elif field_type == "array":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise IntentError("INVALID_FIELD_TYPE", f"{field} must be an array of strings")
