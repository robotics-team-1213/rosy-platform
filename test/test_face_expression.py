# D-922 native expression smoothing, expiry and card precedence.
from test_rosy_face import ROOT, WALL, _display, _face_inputs, _face_loop, _status


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


def test_native_character_keeps_the_situation_face_over_cores_face_and_its_expiry(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, face="bored", battery_charging=True, expression={"gaze_x": 0., "resting": True})
    display, _, clock, _, _, _ = _face_loop(module, tmp_path)
    names = []
    display._faces._render = lambda name, phase, gaze_x, resting: names.append(name) or b"panel"
    display.step()
    display.tick()
    assert names[-1] == "doze"
    display._wall = lambda: WALL + 1  # the resting intent has expired; a situation face does not
    clock.now += .1
    display.tick()
    assert names[-1] == "doze"
    _face_inputs(tmp_path, face="happy", activity_kind="CALIBRATING")
    display.step()
    clock.now += .1
    display.tick()
    assert names[-1] == "scan"


def test_every_face_name_has_a_shipped_asset():
    from core_common.face_screen import FACES

    assets = ROOT / "middleware/robot_ui/face/emotion"
    assert {path.stem for path in assets.glob("*.gif")} == set(FACES)


def test_native_character_draws_the_lamp_filtered_face_not_cores_cheerful_one(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, robot_mode="NAVIGATION", nav_state="BLOCKED", face="cheer",
                 expression={"gaze_x": 4., "resting": False})
    display, _, clock, _, _, _ = _face_loop(module, tmp_path)
    names = []
    display._faces._render = lambda name, phase, gaze_x, resting: names.append(name) or b"panel"
    display.step()
    display.tick()
    assert display.animating[0] == "sad" and names[-1] == "sad"  # a blocked (amber) lamp keeps no grin


def test_native_character_keeps_searching_through_the_recovery_hold(tmp_path):
    module = _display()
    _status(tmp_path, "CORE_READY", runtime_mode="hardware")
    _face_inputs(tmp_path, robot_mode="NAVIGATION", recovery="return", face="happy")
    display, _, clock, _, _, _ = _face_loop(module, tmp_path)
    names = []
    display._faces._render = lambda name, phase, gaze_x, resting: names.append(name) or b"panel"
    display.step()
    display.tick()
    assert names[-1] == "searching"
    _face_inputs(tmp_path, robot_mode="NAVIGATION", recovery=None, face="happy")
    clock.now += .5  # inside the 1.5 s hold: the bar still says recovering
    display.step()
    display.tick()
    assert names[-1] == "searching"
