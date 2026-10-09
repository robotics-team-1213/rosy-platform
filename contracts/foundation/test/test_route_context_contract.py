"""D-531 route hints are short-lived evidence, never an instruction to drive."""
import pytest
from pydantic import ValidationError

from core_common.protocol.route_context import RouteContext
from core_common.protocol.schemas import LineFollowStatus


def test_ring_context_has_bounded_lifetime_and_curvature():
    value = RouteContext(v=1, seq=7, place_id="ring_s", map_id="track-v1",
                         stamp_s=10.0, valid_until_s=10.5, kind="ring", curvature_1pm=3.0)
    assert value.message()["curvature_1pm"] == 3.0
    assert RouteContext(v=1, seq=None).message() == {"v": 1, "seq": None}


@pytest.mark.parametrize("override", [
    {"valid_until_s": 11.01}, {"valid_until_s": 9.9},
    {"curvature_1pm": 0.1}, {"curvature_1pm": float("nan")},
    {"seq": True}, {"place_id": ""}, {"kind": "unknown"},
])
def test_bad_or_unbounded_context_is_rejected(override):
    fields = dict(v=1, seq=7, place_id="ring_s", map_id="track-v1",
                  stamp_s=10.0, valid_until_s=10.5, kind="ring", curvature_1pm=3.0)
    fields.update(override)
    with pytest.raises(ValidationError):
        RouteContext(**fields)


def test_clear_message_cannot_carry_a_stale_place():
    with pytest.raises(ValidationError):
        RouteContext(v=1, seq=None, place_id="ring_s", map_id="track-v1",
                     stamp_s=10.0, valid_until_s=10.5, kind="ring", curvature_1pm=3.0)


def test_bend_phase_is_bounded_to_an_active_bend():
    fields = dict(v=1, seq=7, place_id="bend", map_id="track-v1",
                  stamp_s=10.0, valid_until_s=10.5, kind="bend")
    assert RouteContext(**fields, bend_phase="reacquiring").message()["bend_phase"] == "reacquiring"
    for change in (dict(kind="junction", bend_phase="bending"),
                   dict(bend_phase="armed")):
        with pytest.raises(ValidationError):
            RouteContext(**(fields | change))
    with pytest.raises(ValidationError):
        RouteContext(v=1, seq=None, bend_phase="reacquiring")


def test_line_follow_status_reports_published_context():
    context = RouteContext(v=1, seq=7, place_id="ring_s", map_id="track-v1",
                           stamp_s=10.0, valid_until_s=10.5, kind="ring", curvature_1pm=3.0)
    status = LineFollowStatus(route_context=context, route_context_published_at_s=10.0)
    assert status.model_dump()["route_context"]["seq"] == 7
