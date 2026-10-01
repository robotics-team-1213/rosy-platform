"""Typed reads of parsed YAML for the recipe and cell loaders. Each failure names the field."""

from __future__ import annotations

import math

import yaml


class FieldError(ValueError):
    """One malformed field; the message starts with the field name."""


def parse(text: str, what: str) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise FieldError(f"{what} is not valid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise FieldError(f"{what} must be a mapping")
    return data


def key_problems(value: dict, field: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> list[str]:
    problems = [f"{field}.{k} is not a known field" for k in value if k not in required and k not in optional]
    return problems + [f"{field}.{k} is missing" for k in required if k not in value]


def mapping(value: object, field: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict:
    if not isinstance(value, dict):
        raise FieldError(f"{field} must be a mapping")
    problems = key_problems(value, field, required, optional)
    if problems:
        raise FieldError("; ".join(problems))
    return value


def entries(value: object, field: str) -> list:
    if not isinstance(value, list):
        raise FieldError(f"{field} must be a list")
    return value


def text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise FieldError(f"{field} must be a string, got {value!r}")
    return value


def flag(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise FieldError(f"{field} must be true or false, got {value!r}")
    return value


def number(value: object, field: str) -> float:
    # bool is an int subclass; YAML `yes`/`true` must not become 1.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FieldError(f"{field} must be a number, got {value!r}")
    try:
        n = float(value)
    except OverflowError:  # an int beyond float range (YAML `1000...0`)
        raise FieldError(f"{field} is too large to be a number") from None
    if not math.isfinite(n):
        raise FieldError(f"{field} must be finite, got {value!r}")
    return n


def positive(value: object, field: str) -> float:
    n = number(value, field)
    if n <= 0:
        raise FieldError(f"{field} must be positive, got {n!r}")
    return n


def non_negative(value: object, field: str) -> float:
    n = number(value, field)
    if n < 0:
        raise FieldError(f"{field} must be non-negative, got {n!r}")
    return n


def point(value: object, field: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise FieldError(f"{field} must be a list of three numbers")
    return (number(value[0], f"{field}[0]"), number(value[1], f"{field}[1]"), number(value[2], f"{field}[2]"))
