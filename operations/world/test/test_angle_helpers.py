"""World/Fleet wrapping keeps the existing [-pi, pi) endpoint convention."""

import math

import pytest

from rosy.world.state.projections import map_pose


@pytest.mark.parametrize('angle, expected', [(0, 0), (math.pi, -math.pi),
                                           (-math.pi, -math.pi), (3 * math.pi, -math.pi)])
def test_public_wrap_angle_preserves_endpoints(angle, expected):
    assert map_pose.wrap_angle(angle) == pytest.approx(expected)
    assert map_pose._wrap(angle) == map_pose.wrap_angle(angle)
