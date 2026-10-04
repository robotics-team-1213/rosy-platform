"""Visible lane hypotheses explain evidence without assigning a new driving lane."""
import pytest
from control.sensing.perception.lane_topology import lane_hypotheses


def boundary(y, selected=False, heading=0, start=.12, end=.40):
    return dict(y_at_side_x_m=y, heading_deg=heading, selected=selected,
                ends_m=[[start, y], [end, y]], ends_px=[[20, 180], [80, 70]])


def test_three_lane_candidates_distinguish_current_and_adjacent_without_changing_target():
    records = [boundary(.2775), boundary(.0925, True),
               boundary(-.0925, True), boundary(-.2775)]
    keep = dict(strategy='both', lane_width_m=.185, boundaries=records)
    lanes = lane_hypotheses(keep)
    assert [lane['relation'] for lane in lanes] == ['left', 'current', 'right']
    assert [lane['selected'] for lane in lanes] == [False, True, False]
    assert len(keep['boundaries']) == 4


def test_one_visible_boundary_does_not_invent_a_lane_pair():
    assert lane_hypotheses(dict(strategy='left_only', lane_width_m=.185,
                                boundaries=[boundary(.0925, True)])) == []


@pytest.mark.parametrize('other', [boundary(-.4), boundary(-.0925, heading=40),
                                     boundary(-.0925, start=.41, end=.5)])
def test_wrong_spacing_direction_or_nonoverlap_cannot_become_a_lane(other):
    assert lane_hypotheses(dict(strategy='both', lane_width_m=.185,
                                boundaries=[boundary(.0925), other])) == []


def test_fragmented_paint_is_not_counted_as_an_extra_lane():
    lanes = lane_hypotheses(dict(strategy='both', lane_width_m=.185, boundaries=[
        boundary(.0925, True), boundary(.10), boundary(-.0925, True)]))
    assert len(lanes) == 1 and lanes[0]['selected']


def test_hold_can_show_candidates_but_cannot_claim_a_selected_lane():
    lanes = lane_hypotheses(dict(strategy='none', lane_width_m=.185, boundaries=[
        boundary(.0925, True), boundary(-.0925, True)]))
    assert len(lanes) == 1 and not lanes[0]['selected']


@pytest.mark.parametrize('width', [None, 0, True, float('nan')])
def test_missing_or_invalid_lane_width_cannot_invent_topology(width):
    assert lane_hypotheses(dict(strategy='both', lane_width_m=width, boundaries=[
        boundary(.0925), boundary(-.0925)])) == []
