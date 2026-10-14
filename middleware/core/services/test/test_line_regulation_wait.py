"""D-760 rev 3 item 9: ``line_follow.regulation_wait`` names the regulation that stands the robot,
from the same judgement as the 2b clock helper (crosswalk/gate.py)."""
from dataclasses import replace

import pytest

from core_common.protocol.schemas import LineFollowStatus
from test_line_junction import Rig


def _authority(rig, required=True):
    rig.m._config = replace(rig.m.config, authority_required=required)


def _crosswalk(rig, state, **status):
    rig.m._xwalk.status = lambda now: {'state': state, **status}


def _signal_waiting(rig):
    rig.m._config = replace(rig.m.config, junction_signal_enabled=True)
    rig.step(junction=True)
    assert rig.m.junction_signal_request() is not None


def test_driving_freely_is_null():
    rig = Rig()
    decision, status = rig.step(dx=.004)
    assert decision.linear > 0
    assert status.regulation_wait is None
    assert rig.m._regulation_wait(rig.now) is None


def test_off_is_null_even_with_a_regulation():
    rig = Rig(authority_required=True)
    rig.m.stop()
    assert rig.m.status().regulation_wait is None


def test_authority_hold():
    rig = Rig()
    _authority(rig)
    decision, status = rig.step()
    assert (decision.linear, status.reason) == (0., 'authority_none')
    assert status.regulation_wait == 'authority'


def test_signal_wait_until_the_robot_enters():
    rig = Rig()
    _signal_waiting(rig)
    decision, status = rig.step(junction=True)
    assert decision.linear == decision.angular == 0
    assert status.regulation_wait == 'signal'
    request = rig.m.junction_signal_request()
    rig.m.junction_signal_answer(dict(request_id=request, lamp='red', may_enter=False, reason='test'))
    assert rig.step(junction=True)[1].regulation_wait == 'signal'
    rig.m.junction_signal_answer(dict(request_id=request, lamp='green', may_enter=True, reason='test'))
    assert rig.step(junction=True)[1].regulation_wait is None


def test_green_selected_but_not_entered_is_not_a_signal_wait():
    """Safety-Review: once green+may_enter selects the turn, the junction leaves `waiting`; before
    _signal_committed marks it entered (a later stop zeroed the twist) nothing regulatory holds."""
    rig = Rig()
    _signal_waiting(rig)
    request = rig.m.junction_signal_request()
    rig.m.junction_signal_answer(dict(request_id=request, lamp='green', may_enter=True, reason='test'))
    rig.step(junction=True)
    s = rig.m._junction_signal
    s.pop('entered', None)                    # as if a later stop zeroed the twist this tick
    s['state'] = 'green'
    assert rig.m._junction['state'] in ('armed', 'approaching', 'turning', 'advancing')
    assert rig.m._regulation_wait(rig.now) is None
    assert rig.m._regulated_wait_share(rig.now, .05, .1) == 0.


def test_junction_wait_without_the_signal_is_not_a_regulation():
    rig = Rig()
    decision, status = rig.step(junction=True)
    assert status.junction.state == 'waiting' and decision.linear == 0
    assert status.regulation_wait is None


@pytest.mark.parametrize('xw,want', [
    (dict(state='looking', look_progress=.2), 'crosswalk_look'),
    (dict(state='waiting', look_progress=0.), 'crosswalk_wait'),
    (dict(state='crossing', look_progress=.4), 'crosswalk_held'),
    (dict(state='crossing', look_progress=None), None),
    (dict(state='approaching', look_progress=None), None),
    (dict(state='armed', look_progress=None), None),
])
def test_crosswalk_states(xw, want):
    rig = Rig()
    _crosswalk(rig, **xw)
    assert rig.m._regulation_wait(rig.now) == want
    assert rig.m.status().regulation_wait == want


def test_precedence_authority_signal_crosswalk():
    rig = Rig()
    _signal_waiting(rig)
    _crosswalk(rig, 'waiting', look_progress=0.)
    assert rig.m.status().regulation_wait == 'signal'
    _authority(rig)
    assert rig.m.status().regulation_wait == 'authority'
    _authority(rig, False)
    rig.m._junction_signal = None
    assert rig.m.status().regulation_wait == 'crosswalk_wait'


@pytest.mark.parametrize('xw', [dict(state='looking'), dict(state='waiting'),
                                dict(state='crossing', look_progress=.1)])
def test_the_clock_helper_reads_the_same_judgement(xw):
    """The 2b helper credits only a sustained regulation across adjacent ticks."""
    rig = Rig()
    assert rig.m._regulated_wait_share(rig.now, .05, .1) == 0.
    _crosswalk(rig, **xw)
    assert rig.m._regulation_wait(rig.now) is not None
    assert rig.m._regulated_wait_share(rig.now, .05, .1) == 0.
    assert rig.m._regulated_wait_share(rig.now + .05, .05, .1) == 0.
    assert rig.m._regulated_wait_share(rig.now + .10, .05, .1) == pytest.approx(.05)


def test_old_fields_unchanged_and_field_is_optional():
    assert LineFollowStatus().regulation_wait is None
    assert 'regulation_wait' not in LineFollowStatus.model_validate({'mode': 'OFF'}).model_fields_set
    rig = Rig()
    _authority(rig)
    status = rig.step()[1]
    assert (status.state, status.reason, status.linear) == ('HOLD', 'authority_none', 0.)
    dumped = rig.m.status().model_dump()
    assert dumped['regulation_wait'] == 'authority' and 'crosswalk' in dumped and 'junction' in dumped
    with pytest.raises(ValueError):
        LineFollowStatus(regulation_wait='parking')
