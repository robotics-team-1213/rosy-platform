"""The procedural character: determinism, mood differentiation and the D-504 no-blink guard."""

from itertools import combinations

from emotion.character import BLUSH, NAMES, PINK, frame

EYE_CY = {"hello": 100, "basic": 108, "angry": 114, "bored": 176, "fun": 164,
          "happy": 98, "interest": 68, "sad": 116, "doze": 92, "scan": 94,
          "lost": 92, "worry": 84, "lowbat": 144, "cheer": 84, "thinking": 56,
          "searching": 128}
WARM = ("hello", "happy", "fun", "doze", "cheer")


def _mask(name):
    grey = frame(name, 0).convert("L").resize((32, 24))
    return grey.point(lambda value: 255 if value > 90 else 0).tobytes()


def _pixels(image):
    data = image.convert("RGB").tobytes()
    return [tuple(data[i:i + 3]) for i in range(0, len(data), 3)]


def test_frames_are_deterministic():
    for name in NAMES:
        for phase in (0, 3, 9, 15):
            assert frame(name, phase).tobytes() == frame(name, phase).tobytes(), name
            steered = frame(name, phase, gaze_x=3.0, resting=0.6)
            assert steered.tobytes() == frame(name, phase, gaze_x=3.0, resting=0.6).tobytes(), name


def test_every_pair_of_moods_renders_a_different_face():
    masks = {name: _mask(name) for name in NAMES}
    for left, right in combinations(NAMES, 2):
        cells = sum(a != b for a, b in zip(masks[left], masks[right]))
        assert cells > 7, f"{left} and {right} share {1 - cells / 768:.1%} of the glance mask"


def test_eyelids_move_but_never_close():
    for name in NAMES:
        cy = EYE_CY[name]
        band = (60, cy - 42, 260, cy + 42)
        counts = [sum(1 for pixel in _pixels(frame(name, phase).crop(band))
                      if pixel == PINK or pixel[0] > 190) for phase in range(20)]
        assert min(counts) > 0, f"{name}'s eyes shut at phase {counts.index(min(counts))}"
        assert max(counts) - min(counts) > 4, f"{name}'s eyes never move"


def test_warm_moods_blush_and_the_others_do_not():
    for name in NAMES:
        blushing = sum(1 for pixel in _pixels(frame(name, 5)) if pixel == BLUSH)
        if name in WARM:
            assert blushing > 20, f"{name} has no warm cheeks"
        else:
            assert blushing == 0, f"{name} blushes without cause"
