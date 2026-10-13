"""The shipped LCD faces remain readable after conversion to the panel size."""

from itertools import combinations
from pathlib import Path

from PIL import Image, ImageChops


ASSETS = Path(__file__).resolve().parents[1] / "emotion"
FACES = ("hello", "basic", "angry", "bored", "fun", "happy", "interest", "sad")
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


def test_panel_edges_have_intermediate_colours():
    for name in FACES:
        with Image.open(ASSETS / f"{name}.gif") as gif:
            colours = {rgb for _count, rgb in gif.convert("RGB").getcolors(320 * 240)}
        assert len(colours) > 2, f"{name} has hard pixel edges"
