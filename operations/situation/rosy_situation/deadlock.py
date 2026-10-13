"""Compatibility identity for the traffic analyzer."""

import sys

from .analyzers import traffic_watch

sys.modules[__name__] = traffic_watch
