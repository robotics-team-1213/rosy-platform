"""Compatibility alias; implementation belongs to fleet.server.channel."""

import sys
from .channel import missions as _implementation

sys.modules[__name__] = _implementation
