"""Stable import path; implementation belongs to providers.cli."""
from .providers.cli import (
    CliProvider as CliProvider,
    _argv as _argv,
    _decode_result as _decode_result,
)
