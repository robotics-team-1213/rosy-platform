# D-922 native expression smoothing, expiry and card precedence.
from test_rosy_face import WALL, _display, _face_inputs, _face_loop, _status


def test_directional_face_frames_smooth_the_pupils_and_can_return_to_neutral(tmp_path):
    module = _display()
    drawn = []
    faces = module.FaceFrames(
        tmp_path, opener=lambda _: None, convert=lambda image: image,
        log=module.Log(lambda _: None),
        render=lambda name, phase, gaze_x, resting: drawn.append((name, gaze_x, resting)) or drawn[-1])
    faces.next("interest", expression={"gaze_x": 6., "resting": False}, now=0.)
    faces.next("interest", expression={"gaze_x": 6., "resting": False}, now=.2)
    assert 0 < drawn[-1][1] < 6
    faces.next("interest", expression={"gaze_x": 6., "resting": False}, now=.4)
    assert drawn[-1][1] == 6
    faces.next("basic", expression={"gaze_x": 0., "resting": False}, now=.5)
    faces.next("basic", expression={"gaze_x": 0., "resting": False}, now=.9)
    assert abs(drawn[-1][1]) < 1e-6


def test_native_character_rendering_yields_to_estop_and_sleep(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, face="happy", expression={"gaze_x": 6., "resting": False})
    display, lcd, clock, _, _, _ = _face_loop(module, tmp_path)
    directions = []
    display._faces._render = lambda name, phase, gaze_x, resting: directions.append(gaze_x) or b"panel"
    display.step()
    display.tick()
    clock.now += .5
    display.tick()
    assert directions[-1] == 6
    _face_inputs(tmp_path, estop=True, expression={"gaze_x": 6., "resting": False})
    display.step()
    assert not display.tick()


def test_cached_core_does_not_extend_directional_intent_after_a_read_failure(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, face="happy", expression={"gaze_x": 6., "resting": False})
    display, _, clock, _, _, _ = _face_loop(module, tmp_path)
    directions = []
    display._faces._render = lambda name, phase, gaze_x, resting: directions.append(gaze_x) or b"panel"
    display.step()
    display.tick()
    clock.now += .5
    display.tick()
    assert directions[-1] == 6
    (tmp_path / "run/rosy/face-inputs.json").write_text("{", encoding="utf-8")
    display._wall = lambda: WALL + .5
    clock.now += .1
    display.tick()
    clock.now += .4
    display.tick()
    assert abs(directions[-1]) < 1e-6
    _face_inputs(tmp_path, power_mode="standby")
    display.step()
    assert not display.tick()
