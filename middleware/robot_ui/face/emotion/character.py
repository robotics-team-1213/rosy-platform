"""Rebuild the LCD faces of one character: python make_faces.py.

D-504 keeps 20 frames at 100 ms and calm motion without alarm-like flashing.
Life is a slow breath and a slow look with no blink (D-504), dual catchlights, and distinct
brow/eye/mouth expressions. Pink on black, drawn at 3x and scaled to 320x240.

The 32x24 glance test only sees thick pink (luma > 90). Operating and
situation moods keep their primary mass on distinct rows while subtle blush
accents add warmth on the 320x240 panel without altering the glance silhouette.
"""

from math import cos, pi, sin

from PIL import Image, ImageDraw


SIZE = (320, 240)
SCALE = 3
PINK = (238, 79, 203)  # #ee4fcb
BLUSH = (132, 36, 108)  # warm rose cheek accent (luma ~73, below 32x24 threshold)
BLACK = (0, 0, 0)
CATCH = (255, 236, 248)
NAMES = ("hello", "basic", "angry", "bored", "fun", "happy", "interest", "sad",
         # Situation faces: face_screen.situation_face picks them; cheer is a group greeting.
         "doze", "scan", "lost", "worry", "lowbat", "cheer", "thinking", "searching")
EYE_L = 108
EYE_R = 212


def frame(name: str, phase: float, *, gaze_x: float | None = None,
          resting: float = 0.0) -> Image.Image:
    """One face. Breath and gaze stay legible at 320x240 and 32x24; the lids never blink."""
    image = Image.new("RGB", (SIZE[0] * SCALE, SIZE[1] * SCALE), BLACK)
    draw = ImageDraw.Draw(image)
    angle = 2 * pi * phase / 20
    breath = sin(angle)
    resting = max(0.0, min(1.0, float(resting)))
    gaze_x = None if gaze_x is None else max(-6.0, min(6.0, float(gaze_x)))
    bob = (8 - 6 * resting) * breath
    look = 9 * cos(angle)
    openness = 0.90 + 0.10 * breath

    def sc(value: float) -> int:
        return int(round(value * SCALE))

    def ellipse(box, fill) -> None:
        draw.ellipse(tuple(sc(value) for value in box), fill=fill)

    def stroke(points, width: float, fill=PINK) -> None:
        draw.line(
            [(sc(x), sc(y)) for x, y in points],
            fill=fill, width=max(1, sc(width)), joint="curve")

    def bow(cx: float, cy: float, half: float, drop: float, n: int = 15):
        return [
            (cx - half + 2 * half * i / (n - 1), cy + drop * (1 - (2 * i / (n - 1) - 1) ** 2))
            for i in range(n)
        ]

    def cheeks(y: float, rx: float = 13.0, ry: float = 6.5) -> None:
        cy = y + bob * 0.7
        pulse = 1.0 + 0.06 * breath
        for cx in (66, 254):
            ellipse((cx - rx * pulse, cy - ry * pulse, cx + rx * pulse, cy + ry * pulse), BLUSH)

    def open_eye(cx: float, cy: float, rx: float, ry: float, pdx: float, pdy: float,
                 *, top_lid: float = 0.0, slant: float = 0.0,
                 sparkle: bool = False, watery: bool = False) -> None:
        cy += bob
        height = max(16.0, ry * openness)
        ellipse((cx - rx, cy - height, cx + rx, cy + height), PINK)
        if top_lid > 0.0 or slant != 0.0:
            # Clip upper lid gently for narrowed or slanted expressions.
            lid_y = cy - height + height * top_lid
            sl = slant * height * 0.45
            draw.polygon([
                (sc(cx - rx - 2), sc(cy - height - 2)),
                (sc(cx + rx + 2), sc(cy - height - 2)),
                (sc(cx + rx + 2), sc(lid_y + sl)),
                (sc(cx - rx - 2), sc(lid_y - sl)),
            ], fill=BLACK)
        prx = max(7.0, min(rx * 0.30, 10.0))
        pry = min(height * 0.40, prx * 1.05)
        px = min(cx + rx - prx - 4, max(cx - rx + prx + 4, cx + (pdx if gaze_x is None else gaze_x)))
        min_py = cy - height + pry + 4 + max(0.0, top_lid * height * 0.55)
        py = min(cy + height - pry - 4, max(min_py, cy + pdy))
        ellipse((px - prx, py - pry, px + prx, py + pry), BLACK)
        c_scale = 1.25 if sparkle else 1.0
        ellipse((px - prx * 0.30 * c_scale, py - pry * 0.45 * c_scale,
                 px + prx * 0.24 * c_scale, py - pry * 0.45 * c_scale + 5.2 * c_scale), CATCH)
        # Secondary lower specular glint moves with pupil center.
        ellipse((px + prx * 0.14, py + pry * 0.18,
                 px + prx * 0.42, py + pry * 0.18 + (3.2 if sparkle else 2.4)), CATCH)
        if watery:
            ellipse((px - prx * 0.55, cy + height * 0.34,
                     px - prx * 0.15, cy + height * 0.34 + 3.0), CATCH)

    def filled_smile(half: float, depth: float, y: float, up: bool = True) -> None:
        """Thick U. The bottom band stays about 18 px so the glance test sees it."""
        depth *= 1 + 0.12 * breath
        cy = y + bob
        wall = 18.0
        if up:
            top, bot = cy - depth * 0.08, cy + depth
            ellipse((160 - half, top, 160 + half, bot), PINK)
            ellipse((160 - half + wall, top - depth, 160 + half - wall, bot - wall), BLACK)
        else:
            top, bot = cy - depth, cy + depth * 0.08
            ellipse((160 - half, top, 160 + half, bot), PINK)
            ellipse((160 - half + wall, top + wall, 160 + half - wall, bot + depth), BLACK)

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
            x, y, rad = 160 + sign * half, end_y + bob, max(up, down)
            ellipse((x - rad, y - up, x + rad, y + down), PINK)

    def smile_eye(cx: float, y: float, *, brow_y: float | None = None) -> None:
        """Squinting eye with pupil and catchlights still in the pink."""
        cy = y + bob
        lift = 18 * (0.90 + 0.10 * breath)
        ellipse((cx - 32, cy - lift, cx + 32, cy + 10), PINK)
        ellipse((cx - 22, cy - lift + 17, cx + 22, cy + 26), BLACK)
        px = cx + (look * 0.25 if gaze_x is None else gaze_x)
        py = cy - lift * 0.42
        ellipse((px - 6.2, py - 5.2, px + 6.2, py + 4.6), BLACK)
        ellipse((px - 2.4, py - 3.0, px + 1.3, py - 0.2), CATCH)
        ellipse((px + 1.1, py + 0.4, px + 3.1, py + 2.2), CATCH)
        if brow_y is not None:
            stroke(bow(cx, brow_y + bob, 18, -5), 6.5)

    def laugh_eye(cx: float, y: float) -> None:
        """Both eyes the same high arch, thick enough to survive the glance test."""
        cy = y + bob
        lift = 22 * (0.92 + 0.08 * breath)
        ellipse((cx - 34, cy - lift, cx + 34, cy + 8), PINK)
        ellipse((cx - 20, cy - 2, cx + 20, cy + 26), BLACK)
        px = cx + (look * 0.15 if gaze_x is None else gaze_x)
        py = cy - lift * 0.48
        ellipse((px - 5.2, py - 4.2, px + 5.2, py + 3.6), BLACK)
        ellipse((px - 1.8, py - 2.4, px + 1.1, py + 0.2), CATCH)

    def heavy_eye(cx: float, y: float) -> None:
        """Solid low lid. A small pupil stays in the lid; the lid is the mass."""
        cy = y + bob
        ellipse((cx - 40, cy - 11, cx + 40, cy + 9), PINK)
        px = cx + (look * 0.16 if gaze_x is None else gaze_x)
        ellipse((px - 6, cy + 0, px + 6, cy + 8), BLACK)
        ellipse((px - 2.0, cy + 1.2, px + 1.2, cy + 4.2), CATCH)

    if name == "basic":
        stroke(bow(EYE_L, 74 + bob, 16, -3), 5.5)
        stroke(bow(EYE_R, 74 + bob, 16, -3), 5.5)
        open_eye(EYE_L, 108, 28, 26, look * 0.45, 1)
        open_eye(EYE_R, 108, 28, 26, look * 0.45, 1)
        filled_smile(36, 18, 152)
    elif name == "hello":
        cheeks(132)
        stroke(bow(EYE_L, 64 + bob, 19, -5.5), 6.5)
        stroke(bow(EYE_R, 64 + bob, 19, -5.5), 6.5)
        open_eye(EYE_L, 100, 30, 26, -5 + look * 0.25, -2, sparkle=True)
        open_eye(EYE_R, 100, 30, 26, 5 + look * 0.25, -2, sparkle=True)
        filled_smile(52, 26, 158)
    elif name == "interest":
        # Asymmetric curious brows; mouth stays independent of gaze_x for D-922 tests.
        open_eye(EYE_L, 68, 27, 24, look * 0.55, -8, sparkle=True)
        open_eye(EYE_R, 68, 27, 24, look * 0.55, -8, sparkle=True)
        stroke(bow(EYE_L, 38 + bob, 18, -6.0), 7.5)
        stroke(bow(EYE_R, 42 + bob, 18, -3.5), 7.5)
        filled_smile(34, 18, 122)
    elif name == "happy":
        cheeks(124)
        smile_eye(EYE_L, 98, brow_y=68)
        smile_eye(EYE_R, 98, brow_y=68)
        filled_smile(58, 22, 108)
    elif name == "fun":
        cheeks(182)
        laugh_eye(EYE_L, 164)
        laugh_eye(EYE_R, 164)
        filled_smile(50, 26, 176)
    elif name == "bored":
        # Low lids, droopy brows, thick frown. Lower edge stays above y=224.
        stroke([(EYE_L - 22, 155 + bob), (EYE_L + 18, 159 + bob)], 6)
        stroke([(EYE_R - 18, 159 + bob), (EYE_R + 22, 155 + bob)], 6)
        heavy_eye(EYE_L, 176)
        heavy_eye(EYE_R, 176)
        heavy_frown(204, 8 - 12 * resting, 62 - 26 * resting, 7, 10)
    elif name == "sad":
        open_eye(EYE_L, 116, 24, 22, look * 0.15, 7, watery=True)
        open_eye(EYE_R, 116, 24, 22, look * 0.15, 7, watery=True)
        stroke([(EYE_L - 22, 86 + bob), (EYE_L + 16, 100 + bob)], 8)
        stroke([(EYE_R - 16, 100 + bob), (EYE_R + 22, 86 + bob)], 8)
        filled_smile(36, 16, 170, up=False)
    elif name == "angry":
        open_eye(EYE_L, 114, 22, 18, 6, 1, top_lid=0.18, slant=0.45)
        open_eye(EYE_R, 114, 22, 18, -6, 1, top_lid=0.18, slant=-0.45)
        stroke([(EYE_L - 24, 78 + bob), (EYE_L + 16, 96 + bob)], 9)
        stroke([(EYE_R - 16, 96 + bob), (EYE_R + 24, 78 + bob)], 9)
        stroke([(128, 166 + bob), (192, 166 + bob)], 14)
    # Eight situation faces keep >= 6% 32x24 silhouette distance from every other face.
    elif name == "doze":
        # Eyes shut to two slow arcs; only breath moves them. No pupils to steer.
        cheeks(122, rx=14.0, ry=7.0)
        stroke(bow(EYE_L, 92 + bob, 34.5, -17.25), 20.8)
        stroke(bow(EYE_R, 92 + bob, 34.5, -17.25), 20.8)
        filled_smile(30, 14, 174)
    elif name == "scan":
        # Narrow tall eyes sweeping with `look`, over a segmented measure bar.
        stroke([(EYE_L - 18, 48 + bob), (EYE_L + 18, 48 + bob)], 6.5)
        stroke([(EYE_R - 18, 48 + bob), (EYE_R + 18, 48 + bob)], 6.5)
        open_eye(EYE_L, 94, 23.4, 36.8, look * 0.9, 0)
        open_eye(EYE_R, 94, 23.4, 36.8, look * 0.9, 0)
        pulse = 4.0 * sin(2 * angle)
        stroke([(124 - pulse, 140 + bob), (196 + pulse, 140 + bob)], 15.6)
    elif name == "lost":
        # Wide short eyes hunting with asymmetric brows and a zigzag mouth.
        stroke(bow(EYE_L, 62 + bob, 20, -6), 7.5)
        stroke([(EYE_R - 18, 66 + bob), (EYE_R + 20, 62 + bob)], 7.5)
        open_eye(EYE_L, 92, 36.8, 20.8, look * 0.6, -2)
        open_eye(EYE_R, 92, 36.8, 20.8, look * 0.6, -2)
        wobble = 2.0 * sin(angle)
        stroke([(112 + 24 * k, 156 + bob + (-8 if k % 2 else 8) + wobble * (1 if k % 2 else -1))
                for k in range(5)], 16.9)
    elif name == "worry":
        # Inner-raised brows over eyes that look down with a gentle nervous micro-shift.
        quiver = 0.9 * sin(2 * angle)
        open_eye(EYE_L, 84, 28.75, 27.6, look * 0.3 + quiver, 4)
        open_eye(EYE_R, 84, 28.75, 27.6, look * 0.3 + quiver, 4)
        stroke([(EYE_L - 24, 60 + bob), (EYE_L + 20, 46 + bob)], 12.8)
        stroke([(EYE_R - 20, 46 + bob), (EYE_R + 24, 60 + bob)], 12.8)
        stroke(bow(160, 172 + bob, 24, -8), 19.2)
    elif name == "lowbat":
        # Tired but awake: squinting low with droopy brows and a weak thin mouth.
        stroke([(EYE_L - 20, 114 + bob), (EYE_L + 16, 120 + bob)], 6)
        stroke([(EYE_R - 16, 120 + bob), (EYE_R + 20, 114 + bob)], 6)
        smile_eye(EYE_L, 144)
        smile_eye(EYE_R, 144)
        stroke([(128, 202 + bob), (192, 202 + bob)], 10)
    elif name == "cheer":
        # Raised brows, sparkling wide eyes, rosy cheeks, wide grin.
        cheeks(114)
        open_eye(EYE_L, 84, 27, 24, look * 0.45, -6, sparkle=True)
        open_eye(EYE_R, 84, 27, 24, look * 0.45, -6, sparkle=True)
        stroke(bow(EYE_L, 52 + bob, 18, -6), 8)
        stroke(bow(EYE_R, 52 + bob, 18, -6), 8)
        filled_smile(58, 24, 136)
    elif name == "thinking":
        # High eyes with lifted pupils, pondering asymmetric brows, shifting round mouth.
        brow_bob = bob * 0.45
        open_eye(EYE_L, 56, 23, 20, look * 0.35, -7)
        open_eye(EYE_R, 56, 23, 20, look * 0.35, -7)
        stroke(bow(EYE_L, 29 + brow_bob, 16, -3.5), 7.8)
        stroke(bow(EYE_R, 33 + brow_bob, 16, -1.5), 7.8)
        shift = 2.0 * sin(angle)
        ellipse((140.5 + shift, 138.5 + bob, 179.5 + shift, 177.5 + bob), PINK)
        ellipse((154 + shift, 152 + bob, 166 + shift, 164 + bob), BLACK)
    elif name == "searching":
        # Brows up, pupils dropped to the floor, active horizontal hunt, flat mouth.
        stroke(bow(EYE_L, 80 + bob, 20, -6), 10.4)
        stroke(bow(EYE_R, 80 + bob, 20, -6), 10.4)
        open_eye(EYE_L, 128, 29.9, 27.6, look * 0.35, 10)
        open_eye(EYE_R, 128, 29.9, 27.6, look * 0.35, 10)
        stroke([(136, 180 + bob), (184, 180 + bob)], 13)
    else:
        raise ValueError(name)
    return image.resize(SIZE, Image.Resampling.LANCZOS)
