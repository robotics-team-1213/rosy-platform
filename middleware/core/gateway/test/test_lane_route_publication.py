"""CORE route publications carry explicit clears and nonrenewable source budgets."""

from core.bridge.lane_route import RouteGuidePublication
from core_common.protocol.lane_route_guide import LaneRouteGuide, SelectedRoutePrior
from control.lane_route_guide_input import LaneRouteGuideInput
import json


def prior(source=10., seq=1):
    return SelectedRoutePrior(leg_id='leg', authority_seq=seq, map_id='map', map_revision=1,
        source_stamp_s=source, valid_until_s=source+.8, heading_here_deg=0.,
        heading_ahead_deg=20., ahead_m=.25, s_m=1., off_route_m=0.)


def test_first_active_publication_announces_epoch_with_clear_then_active():
    pub = RouteGuidePublication(clock=lambda: 1.)
    messages = [LaneRouteGuide.model_validate(m) for m in pub.messages(prior(), 10.1)]
    assert len(messages) == 2 and messages[0].guide is None
    assert messages[1].guide == prior()
    assert messages[0].publisher_epoch == messages[1].publisher_epoch
    assert messages[0].seq < messages[1].seq
    assert pub.messages(prior(), 10.15) == []


def test_loss_is_an_immediate_ordered_clear():
    pub = RouteGuidePublication(clock=lambda: 1.)
    active = pub.messages(prior(), 10.1)[-1]
    cleared = pub.messages(None, 10.11)
    assert len(cleared) == 1 and cleared[0]['guide'] is None
    assert cleared[0]['seq'] > active['seq']


def test_paused_source_clock_cannot_renew_prior_even_after_clear():
    wall = [1.]
    pub = RouteGuidePublication(clock=lambda: wall[0])
    pub.messages(prior(), 10.1)
    wall[0] = 1.1
    pub.messages(None, 10.1)
    wall[0] = 1.8
    assert all(m['guide'] is None for m in pub.messages(prior(), 10.1))


def test_clock_rewind_announces_new_epoch_before_new_source():
    pub = RouteGuidePublication(clock=lambda: 1.)
    old = pub.messages(prior(), 10.1)[-1]
    reset = pub.messages(prior(source=2.), 2.1)
    assert reset[0]['guide'] is None
    assert reset[0]['publisher_epoch'] != old['publisher_epoch']
    assert reset[-1]['guide']['source_stamp_s'] == 2.


def test_future_expired_and_regressing_source_are_cleared():
    pub = RouteGuidePublication(clock=lambda: 1.)
    assert all(m['guide'] is None for m in pub.messages(prior(), 9.9))
    pub.messages(prior(), 10.1)
    assert pub.messages(prior(source=9.9), 10.2)[-1]['guide'] is None
    assert all(m['guide'] is None for m in pub.messages(prior(), 10.8))


def test_clock_rewind_cannot_resurrect_monotonic_expired_source():
    wall = [1.]
    pub = RouteGuidePublication(clock=lambda: wall[0])
    pub.messages(prior(), 10.5)
    wall[0] = 2.
    assert all(m['guide'] is None for m in pub.messages(prior(), 10.2))


def test_rewind_cannot_extend_receiver_budget_while_clear_is_delayed():
    wall = [1.]
    pub, inbox = RouteGuidePublication(clock=lambda: wall[0]), LaneRouteGuideInput(clock=lambda: wall[0])
    for message in pub.messages(prior(), 10.5):
        inbox.receive(json.dumps(message), 10.5)
    assert inbox.for_frame(10.5) is not None
    wall[0] = 1.25
    for message in pub.messages(prior(), 10.2):
        inbox.receive(json.dumps(message), 10.2)
    assert inbox.for_frame(10.2) is not None
    wall[0] = 1.31  # Do not deliver a subsequent publisher clear.
    assert inbox.for_frame(10.2) is None
