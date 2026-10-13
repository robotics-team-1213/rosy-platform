"""Compatibility identity for the existing incident vision assessment."""

import sys

from .incidents import vision

sys.modules[__name__] = vision
