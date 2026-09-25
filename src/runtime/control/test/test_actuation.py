"""Final candidate calibration, caps and hardware sign without ROS."""
import pytest

from control.control.actuation import prepare_command


def prepared(v, w, **changes):
    args = dict(requested_angular=w, linear_gains=(1.25, .75), angular_gains=(.75, 1.25),
                profile_caps=(.2, .8), limited_caps=None, linear_sign=1.)
    return prepare_command(v, w, **(args | changes))


def test_gain_domains_and_direction_are_preserved():
    assert prepared(.014, 0.).linear == pytest.approx(.0175)
    assert prepared(-.014, 0.).linear == pytest.approx(-.0105)
    assert prepared(.015, 0.).linear == .015
    assert prepared(.01, .001).linear == .01
    assert prepared(0., .06).angular == pytest.approx(.045)
    assert prepared(0., -.06).angular == pytest.approx(-.075)
    assert prepared(0., .061).angular == .061


def test_removing_turn_does_not_reclassify_legacy_recovery_as_calibrated_straight():
    assert prepared(-.003, 0., requested_angular=.1).linear == -.003


def test_common_scale_preserves_arc_and_limited_sensor_caps():
    command = prepared(.1, .4, profile_caps=(.05, .8))
    assert (command.linear, command.angular) == pytest.approx((.05, .2))
    limited = prepared(.01, 0., limited_caps=(.005, .05))
    assert limited.linear == pytest.approx(.005)
    assert prepared(.1, .4, limited_caps=(0., 0.)).linear == 0.


def test_sweep_candidate_is_distinct_from_signed_motor_command():
    command = prepared(.01, 0., linear_sign=-1.)
    assert command.linear == pytest.approx(.0125)
    assert command.motor_linear == pytest.approx(-.0125)
    assert command.angular == 0.


def test_actual_node_publishes_the_prepared_sign_even_if_later_state_changes():
    import ast
    from pathlib import Path
    from types import SimpleNamespace as NS
    source = Path(__file__).parents[1] / 'control/safety/node.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n, ast.ClassDef))
    tick = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == 'tick')
    start = next(i for i, n in enumerate(tick.body) if isinstance(n, ast.Assign)
                 and ast.unparse(n.targets[0]) == 'lease_now')
    wrapper = ast.parse('def run():\n    pass').body[0]
    wrapper.body = tick.body[start:]
    calls, published, recorded = [], [], []
    def lease(value):
        def read(now):
            calls.append(now)
            return value
        return read
    robot = NS(calibration_lease=NS(gains=lease((1.25, .75)), angular_gains=lease((1., 1.)),
               motion_limits=lease(None)), profile=NS(max_linear=.2, max_angular=.8),
               last_cmd=NS(linear=NS(x=.01), angular=NS(z=0.)), cmd_linear_sign=-1.,
               pub=NS(publish=lambda cmd: published.append((cmd.linear.x, cmd.angular.z))))
    def record(v, w, reason):
        recorded.append((v, w))
        robot.cmd_linear_sign = 1.
    robot.record_decision = record
    scope = dict(self=robot, cmd=NS(linear=NS(x=.01), angular=NS(z=0.)),
                 bounded_motion=False, time=NS(monotonic=lambda: 10.), prepare_command=prepare_command)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])), str(source), 'exec'), scope)
    scope['run']()
    assert calls == [10., 10., 10.]
    assert recorded == [(pytest.approx(.0125), 0.)]
    assert published == [(pytest.approx(-.0125), 0.)]


@pytest.mark.parametrize('changes', [
    {'linear_gains': (0., 1.)}, {'angular_gains': (1., float('nan'))},
    {'profile_caps': (-1., .8)}, {'limited_caps': (.1, float('inf'))},
    {'linear_sign': 0.}, {'linear_sign': True}, {'requested_angular': float('nan')},
])
def test_invalid_preparation_inputs_do_not_produce_a_command(changes):
    with pytest.raises(ValueError):
        prepared(.01, 0., **changes)
