"""Compatibility identity for source-aware incident context."""

import sys

from .incidents import context

sys.modules[__name__] = context
