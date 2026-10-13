"""Compatibility identity for the observation projection now owned by World."""

import sys

from rosy.world.state.projections import map_pose

sys.modules[__name__] = map_pose
