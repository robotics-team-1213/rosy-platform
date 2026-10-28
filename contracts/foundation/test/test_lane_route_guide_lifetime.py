"""D-769 rev 3: a route prior lives at most three seconds from its source (1 s from Fleet; 3 s for a slow sim)."""
import pytest

from core_common.protocol.lane_route_guide import AuthorityRouteGuide, SelectedRoutePrior

GUIDE = dict(map_id="m", map_revision=1, heading_here_deg=0., heading_ahead_deg=10., ahead_m=.25, s_m=.5,
             off_route_m=.01)


@pytest.mark.parametrize("age,ok", [(1., True), (3., True), (3.01, False)])
def test_the_authority_hint_age_is_bounded_by_three_seconds(age, ok):
    if ok:
        assert AuthorityRouteGuide(max_age_s=age, **GUIDE).max_age_s == age
    else:
        with pytest.raises(ValueError):
            AuthorityRouteGuide(max_age_s=age, **GUIDE)


@pytest.mark.parametrize("life,ok", [(1., True), (3., True), (3.01, False)])
def test_the_selected_prior_lifetime_is_bounded_by_three_seconds(life, ok):
    fields = dict(leg_id="leg", authority_seq=1, source_stamp_s=10., valid_until_s=10. + life, **GUIDE)
    if ok:
        assert SelectedRoutePrior(**fields).valid_until_s == 10. + life
    else:
        with pytest.raises(ValueError):
            SelectedRoutePrior(**fields)
