"""The shipped LCD faces remain readable after conversion to the panel size."""

from itertools import combinations
from pathlib import Path

from PIL import Image, ImageChops


ASSETS = Path(__file__).resolve().parents[1] / "emotion"
SITUATION = ("doze", "scan", "lost", "worry", "lowbat", "cheer", "thinking", "searching")
FACES = ("hello", "basic", "angry", "bored", "fun", "happy", "interest", "sad", *SITUATION)
OPERATING = ("basic", "interest", "happy", "fun", "bored")


def _silhouette(name):
    with Image.open(ASSETS / f"{name}.gif") as gif:
        assert gif.size == (320, 240)
        assert gif.n_frames == 20
        for index in range(gif.n_frames):
            gif.seek(index)
            assert gif.info["duration"] == 100
        gif.seek(0)
        first = gif.convert("L").resize((32, 24))
        gif.seek(gif.n_frames // 4)
        middle = gif.convert("L").resize((32, 24))
    assert first.getbbox(), f"{name} starts blank"
    assert ImageChops.difference(first, middle).getbbox(), f"{name} does not move"
    return first.point(lambda value: 255 if value > 90 else 0).tobytes()


def test_faces_are_visible_and_distinct_at_a_glance():
    masks = {name: _silhouette(name) for name in FACES}
    for left, right in combinations(OPERATING, 2):
        difference = sum(a != b for a, b in zip(masks[left], masks[right])) / len(masks[left])
        assert difference >= 0.06, f"{left} and {right} differ by only {difference:.1%}"



def test_every_situation_face_is_distinct_from_every_other_face():
    masks = {name: _silhouette(name) for name in FACES}
    for left in SITUATION:
        for right in FACES:
            if right == left:
                continue
            difference = sum(a != b for a, b in zip(masks[left], masks[right])) / len(masks[left])
            assert difference >= 0.06, f"{left} and {right} differ by only {difference:.1%}"


def test_assets_are_the_renderer_names():
    from emotion.character import NAMES

    assert NAMES == FACES
    assert {path.stem for path in ASSETS.glob("*.gif")} == set(FACES)


def test_situation_faces_with_pupils_follow_the_gaze():
    from emotion.character import frame

    for name in SITUATION:
        moved = ImageChops.difference(frame(name, 0, gaze_x=-6), frame(name, 0, gaze_x=6)).getbbox()
        assert (moved is None) == (name == "doze"), name  # doze has its eyes shut


def test_panel_edges_have_intermediate_colours():
    for name in FACES:
        with Image.open(ASSETS / f"{name}.gif") as gif:
            colours = {rgb for _count, rgb in gif.convert("RGB").getcolors(320 * 240)}
        assert len(colours) > 2, f"{name} has hard pixel edges"


def test_directional_gaze_moves_pupils_without_moving_the_mouth():
    from emotion.character import frame

    left = frame("interest", 0, gaze_x=-6)
    right = frame("interest", 0, gaze_x=6)
    difference = ImageChops.difference(left, right)
    assert difference.getbbox() is not None
    assert difference.crop((0, 112, 320, 240)).getbbox() is None
    # The pupil catchlights follow direction in both eyes.
    for center in (108, 212):
        def catchlight_x(image):
            points = [(x, y) for x in range(center - 20, center + 20)
                      for y in range(40, 90) if min(image.getpixel((x, y))) > 190]
            return sum(x for x, _ in points) / len(points)
        assert catchlight_x(right) > catchlight_x(left) + 8


def test_resting_is_a_quiet_slow_face_and_still_has_open_eyes():
    from emotion.character import frame

    normal = frame("bored", 0)
    resting = frame("bored", 0, gaze_x=0, resting=1.0)
    assert resting.size == (320, 240)
    assert ImageChops.difference(normal, resting).getbbox()
    for center in (108, 212):
        assert resting.crop((center - 35, 160, center + 35, 190)).getbbox()
