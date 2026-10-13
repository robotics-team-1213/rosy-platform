"""Stable import path; implementation belongs to providers.cli."""
from .providers.cli import (
    json as json, math as math, re as re, asdict as asdict, canonical as canonical, identifier as identifier,
    opinion as opinion, _argv as _argv, _decode_result as _decode_result, CliProvider as CliProvider,
)
