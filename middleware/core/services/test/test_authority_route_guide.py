"""A selected route prior shares the exact accepted authority pose and lifetime."""

import pytest

from core_features.line_follow.model import LineFollowMode
from test_line_authority import Rig, WALL


def hint(**changes):
    return dict(map_id='map-a', map_revision=2, heading_here_deg=10., heading_ahead_deg=20.,
                ahead_m=.25, s_m=.5, off_route_m=.01, max_age_s=.8, **changes)


def test_guide_uses_exact_echoed_source_pose_and_authority_identity():
    rig = Rig()
    rig.step()
    source = rig.now
    rig.step()
    assert rig.send(1., seq=4, stamp=WALL + source, route_guide=hint())['accepted']
    guide = rig.m.route_guide()
    assert guide.leg_id == 'L1' and guide.authority_seq == 4
    assert guide.source_stamp_s == pytest.approx(source)
    assert guide.valid_until_s == pytest.approx(source + .8)


@pytest.mark.parametrize('change', ['no_seq', 'inexact', 'old', 'shrink', 'absent', 'mode', 'expire'])
def test_unusable_or_removed_authority_cannot_leave_a_route_prior(change):
    rig = Rig()
    rig.step()
    rig.send(1., seq=1, route_guide=hint())
    assert rig.m.route_guide() is not None
    if change == 'no_seq':
        rig.send(1., leg='L2', route_guide=hint())
    elif change == 'inexact':
        rig.send(1., seq=2, stamp=WALL + rig.now + .001, route_guide=hint())
    elif change == 'old':
        source = rig.now
        for _ in range(17):
            rig.step()
        rig.send(1., seq=2, stamp=WALL + source, route_guide=hint())
    elif change == 'shrink':
        rig.send(0., seq=2, shrink=True, route_guide=hint())
    elif change == 'absent':
        rig.send(1., seq=2)
    elif change == 'mode':
        rig.m.set_mode(LineFollowMode.OFF)
    else:
        for _ in range(17):
            rig.step()
    assert rig.m.route_guide() is None


def test_same_source_republication_cannot_extend_guide_deadline():
    rig = Rig()
    rig.step()
    source = rig.now
    rig.send(1., seq=1, ttl_s=.2, route_guide=hint())
    deadline = rig.m.route_guide().valid_until_s
    rig.step()
    rig.send(1., seq=2, stamp=WALL + source, ttl_s=2., route_guide=hint())
    assert rig.m.route_guide().valid_until_s == deadline


def test_stale_request_cannot_replace_current_guide():
    rig = Rig()
    rig.step()
    rig.send(1., seq=2, route_guide=hint())
    original = rig.m.route_guide()
    assert not rig.send(1., seq=1, route_guide=None)['accepted']
    assert rig.m.route_guide() == original


def test_sub_ulp_ros_source_lifetime_drops_only_the_guide():
    from core_features.line_follow.route_guide import bind_guide

    base = (WALL, ('epoch', 'odom'), 1_800_000_000_000_000_000, 0., 0., 0., 1.)
    binding, _ = bind_guide({**hint(), 'max_age_s': 1e-8}, base=base, exact=True,
                           leg_id='leg', seq=1, now=1., ttl_s=1., shrink=False, budget=None)
    assert binding is None


def test_clear_does_not_replenish_same_source_budget():
    rig = Rig()
    rig.step()
    source = rig.now
    rig.send(1., seq=1, ttl_s=.2, route_guide=hint())
    deadline = rig.m.route_guide().valid_until_s
    rig.send(1., seq=2)
    rig.step()
    rig.send(1., seq=3, stamp=WALL + source, route_guide=hint())
    assert rig.m.route_guide().valid_until_s == deadline


def test_an_extend_ignored_as_short_still_renews_the_route_prior_but_not_the_grant():
    """v2 lap r48b/r49a: Fleet's map metres ran behind CORE's odom path; each such extend dropped the prior."""
    rig = Rig()
    rig.step()
    rig.send(1., seq=1, ttl_s=.52, route_guide=hint())
    end = rig.authority()['remaining_m']
    rig.step()
    answer = rig.send(.3, seq=2, route_guide={**hint(), 'heading_ahead_deg': 30.})
    assert answer['accepted'] is False and answer['reason'] == 'shrink'
    assert rig.m.route_guide().heading_ahead_deg == 30. and rig.m.route_guide().authority_seq == 2
    assert rig.authority()['remaining_m'] <= end                 # the held end and its ttl stay as they were
    for _ in range(10):
        rig.step()
    assert rig.step().linear == 0. and rig.authority()['state'] == 'EXPIRED' and rig.m.route_guide() is None
