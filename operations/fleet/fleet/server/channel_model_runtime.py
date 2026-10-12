"""Compatibility alias; implementation belongs to fleet.server.channel."""

import sys
from .channel import model_runtime as _implementation

sys.modules[__name__] = _implementation
