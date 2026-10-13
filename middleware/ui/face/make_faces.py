"""Rebuild the eight LCD faces of one character: python make_faces.py.

D-504 keeps the eight names, 20 frames at 100 ms, and no blink or flash.
Life is a slow breath and a slow look. Each mood is one face: the mouth
sits about one eye-height under the eyes, and both eyes share one shape.
Same eye spacing. Pink on black, drawn at 3x and scaled to 320x240.

The 32x24 glance test only sees thick pink. The operating moods therefore
keep their mass on different rows: a high attentive face, a lifted smile,
resting disks, a two-eye laugh, and low waiting lids.
"""

from math import cos, pi, sin
from pathlib import Path

from PIL import Image, ImageDraw


SIZE = (320, 240)
SCALE = 3
PINK = (238, 79, 203)  # #ee4fcb
BLACK = (0, 0, 0)
CATCH = (255, 236, 248)
NAMES = ("hello", "basic", "angry", "bored", "fun", "happy", "interest", "sad")
EYE_L = 108
EYE_R = 212


def frame(name: str, phase: int) -> Image.Image:
    """One face. Breath and gaze are large enough for the 32x24 motion check."""
    image = Image.new("RGB", (SIZE[0] * SCALE, SIZE[1] * SCALE), BLACK)
    draw = ImageDraw.Draw(image)
    breath = sin(2 * pi * phase / 20)
    bob = 8 * breath
    look = 9 * cos(2 * pi * phase / 20)
    openness = 0.90 + 0.10 * breath

    def sc(value: float) -> int:
        return int(round(value * SCALE))

    def ellipse(box, fill) -> None:
        draw.ellipse(tuple(sc(value) for value in box), fill=fill)

    def stroke(points, width: float) -> None:
        draw.line(
            [(sc(x), sc(y)) for x, y in points],
            fill=PINK, width=max(1, sc(width)), joint="curve")

    def bow(cx: float, cy: float, half: float, drop: float, n: int = 15):
        points = []
        for index in range(n):
            along = index / (n - 1)
            x = cx - half + 2 * half * along
            y = cy + drop * (1 - (2 * along - 1) ** 2)
            points.append((x, y))
        return points

    def open_eye(cx: float, cy: float, rx: float, ry: float,
                 pdx: float, pdy: float) -> None:
        cy += bob
        height = max(16.0, ry * openness)
        ellipse((cx - rx, cy - height, cx + rx, cy + height), PINK)
        prx = max(7.0, min(rx * 0.30, 10.0))
        pry = min(height * 0.40, prx * 1.05)
        px = min(cx + rx - prx - 4, max(cx - rx + prx + 4, cx + pdx))
        py = min(cy + height - pry - 4, max(cy - height + pry + 4, cy + pdy))
        ellipse((px - prx, py - pry, px + prx, py + pry), BLACK)
        ellipse((px - prx * 0.28, py - pry * 0.42,
                 px + prx * 0.22, py - pry * 0.42 + 5.2), CATCH)

    def filled_smile(half: float, depth: float, y: float, up: bool = True) -> None:
        """Thick U. The bottom band stays about 18 px so the glance test sees it."""
        depth *= 1 + 0.12 * breath
        cy = y + bob
        wall = 18.0
        if up:
            top = cy - depth * 0.08
            bot = cy + depth
            ellipse((160 - half, top, 160 + half, bot), PINK)
            ellipse((160 - half + wall, top - depth,
                     160 + half - wall, bot - wall), BLACK)
        else:
            top = cy - depth
            bot = cy + depth * 0.08
            ellipse((160 - half, top, 160 + half, bot), PINK)
            ellipse((160 - half + wall, top + wall,
                     160 + half - wall, bot + depth), BLACK)

    def heavy_frown(end_y: float, sag: float, half: float, up: float, down: float) -> None:
        """Thick frown. The center is higher than the corners."""
        count = 33
        upper, lower = [], []
        for index in range(count):
            t = -1 + 2 * index / (count - 1)
            x = 160 + half * t
            mid = end_y + bob - sag * (1 - t * t)
            upper.append((sc(x), sc(mid - up)))
            lower.append((sc(x), sc(mid + down)))
        draw.polygon(upper + lower[::-1], fill=PINK)
        for sign in (-1, 1):
            x = 160 + sign * half
            y = end_y + bob
            rad = max(up, down)
            ellipse((x - rad, y - up, x + rad, y + down), PINK)

    def smile_eye(cx: float, y: float) -> None:
        """Squinting eye with the pupil still in the pink."""
        cy = y + bob
        lift = 18 * (0.90 + 0.10 * breath)
        ellipse((cx - 32, cy - lift, cx + 32, cy + 10), PINK)
        ellipse((cx - 22, cy - lift + 17, cx + 22, cy + 26), BLACK)
        px = cx + look * 0.25
        py = cy - lift * 0.42
        ellipse((px - 6.2, py - 5.2, px + 6.2, py + 4.6), BLACK)
        ellipse((px - 2.4, py - 3.0, px + 1.3, py - 0.2), CATCH)

    def laugh_eye(cx: float, y: float) -> None:
        """Both eyes the same high arch, thick enough to survive the glance test."""
        cy = y + bob
        lift = 22 * (0.92 + 0.08 * breath)
        ellipse((cx - 34, cy - lift, cx + 34, cy + 8), PINK)
        ellipse((cx - 20, cy - 2, cx + 20, cy + 26), BLACK)
        px = cx + look * 0.15
        py = cy - lift * 0.48
        ellipse((px - 5.2, py - 4.2, px + 5.2, py + 3.6), BLACK)
        ellipse((px - 1.8, py - 2.4, px + 1.1, py + 0.2), CATCH)

    def heavy_eye(cx: float, y: float) -> None:
        """Solid low lid. A small pupil stays in the lid; the lid is the mass."""
        cy = y + bob
        ellipse((cx - 40, cy - 11, cx + 40, cy + 9), PINK)
        px = cx + look * 0.16
        ellipse((px - 6, cy + 0, px + 6, cy + 8), BLACK)
        ellipse((px - 2.0, cy + 1.2, px + 1.2, cy + 4.2), CATCH)

    if name == "basic":
        open_eye(EYE_L, 108, 28, 26, look * 0.45, 1)
        open_eye(EYE_R, 108, 28, 26, look * 0.45, 1)
        filled_smile(36, 18, 152)
    elif name == "hello":
        open_eye(EYE_L, 100, 30, 26, -5 + look * 0.25, -2)
        open_eye(EYE_R, 100, 30, 26, 5 + look * 0.25, -2)
        filled_smile(52, 26, 158)
    elif name == "interest":
        # Round eyes, not tall ovals. The pupil and the brow do the looking up.
        open_eye(EYE_L, 68, 27, 24, look * 0.55, -8)
        open_eye(EYE_R, 68, 27, 24, look * 0.55, -8)
        stroke(bow(EYE_L, 40 + bob, 18, -5), 8)
        stroke(bow(EYE_R, 40 + bob, 18, -5), 8)
        filled_smile(34, 18, 122)
    elif name == "happy":
        smile_eye(EYE_L, 98)
        smile_eye(EYE_R, 98)
        filled_smile(58, 22, 108)
    elif name == "fun":
        laugh_eye(EYE_L, 164)
        laugh_eye(EYE_R, 164)
        filled_smile(50, 26, 176)
    elif name == "bored":
        # Low lids, then a thick frown under them. The lower edge stays above y=224.
        heavy_eye(EYE_L, 176)
        heavy_eye(EYE_R, 176)
        heavy_frown(204, 8, 62, 7, 10)
    elif name == "sad":
        open_eye(EYE_L, 116, 24, 22, look * 0.15, 7)
        open_eye(EYE_R, 116, 24, 22, look * 0.15, 7)
        stroke([(EYE_L - 22, 86 + bob), (EYE_L + 16, 100 + bob)], 8)
        stroke([(EYE_R - 16, 100 + bob), (EYE_R + 22, 86 + bob)], 8)
        filled_smile(36, 16, 170, up=False)
    elif name == "angry":
        stroke([(EYE_L - 24, 78 + bob), (EYE_L + 16, 96 + bob)], 9)
        stroke([(EYE_R - 16, 96 + bob), (EYE_R + 24, 78 + bob)], 9)
        open_eye(EYE_L, 114, 22, 18, 6, 1)
        open_eye(EYE_R, 114, 22, 18, -6, 1)
        stroke([(128, 166 + bob), (192, 166 + bob)], 14)
    else:
        raise ValueError(name)
    return image.resize(SIZE, Image.Resampling.LANCZOS)


def main() -> None:
    assets = Path(__file__).resolve().parent / "emotion"
    for name in NAMES:
        frames = [frame(name, phase) for phase in range(20)]
        frames[0].save(
            assets / f"{name}.gif", save_all=True, append_images=frames[1:],
            duration=100, loop=0, optimize=False)


if __name__ == "__main__":
    main()
