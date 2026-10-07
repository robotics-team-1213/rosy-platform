"""Rebuild the eight small LCD face loops: python make_faces.py."""

from math import cos, pi, sin
from pathlib import Path

from PIL import Image, ImageDraw


SIZE = (320, 240)
SCALE = 3
PINK = "#ee4fcb"
BLACK = "#000000"
NAMES = ("hello", "basic", "angry", "bored", "fun", "happy", "interest", "sad")


def frame(name: str, phase: int) -> Image.Image:
    """One face; small motion keeps the silhouette stable at walking distance."""
    image = Image.new("RGB", (SIZE[0] * SCALE, SIZE[1] * SCALE), BLACK)
    draw = ImageDraw.Draw(image)
    motion = sin(2 * pi * phase / 20)
    bob = round(2 * motion)
    flex = round(4 * motion)
    sway = round(4 * cos(2 * pi * phase / 20))

    def box(coords):
        return tuple(round(value * SCALE) for value in coords)

    def ellipse(coords):
        draw.ellipse(box(coords), fill=PINK)

    def polygon(points):
        draw.polygon([(round(x * SCALE), round(y * SCALE)) for x, y in points], fill=PINK)

    def round_rect(coords, radius):
        draw.rounded_rectangle(box(coords), radius=radius * SCALE, fill=PINK)

    def eye(x, y=105, wide=31, high=35):
        ellipse((x - wide, y - high + bob, x + wide, y + high + bob))

    def stroke(points, width=13):
        draw.line([(round(x * SCALE), round((y + bob) * SCALE)) for x, y in points],
                  fill=PINK, width=width * SCALE, joint="curve")

    if name in ("basic", "hello"):
        eye(97, high=35 + flex)
        eye(223, high=35 + flex)
        if name == "basic":
            ellipse((151 + sway, 170 + bob - flex, 169 + sway, 188 + bob + flex))
        else:
            stroke([(116 + sway, 168), (136 + sway, 181), (160 + sway, 186 + flex),
                    (184 + sway, 181), (204 + sway, 168)], 14)
            stroke([(270, 66), (282, 53), (292, 67)], 8)
    elif name == "interest":
        polygon([(43, 111 + bob), (95, 59 + bob - flex), (151, 111 + bob),
                 (95, 163 + bob + flex)])
        eye(224, y=112, wide=11, high=35 + flex)
        stroke([(199, 58), (222, 48 - flex), (247, 58)], 9)
        stroke([(139 + sway, 175), (160 + sway, 180), (181 + sway, 175)], 11)
    elif name == "happy":
        stroke([(57, 122), (74, 101), (96, 91 - flex), (118, 101), (135, 122)], 17)
        stroke([(185, 122), (202, 101), (224, 91 - flex), (246, 101), (263, 122)], 17)
        stroke([(100 + sway, 160), (126 + sway, 183), (160 + sway, 191 + flex),
                (194 + sway, 183), (220 + sway, 160)], 17)
    elif name == "fun":
        eye(95, y=103, wide=29, high=33)
        stroke([(186, 111), (216, 102 + flex), (249, 111)], 17)
        stroke([(85 + sway, 157), (118 + sway, 188), (160 + sway, 202 + flex),
                (202 + sway, 188), (235 + sway, 157)], 20)
    elif name == "bored":
        round_rect((61, 103 + bob, 133, 122 + bob + flex), radius=9)
        round_rect((187, 103 + bob, 259, 122 + bob + flex), radius=9)
        stroke([(138 + sway, 177), (182 + sway, 177)], 11)
    elif name == "sad":
        eye(97, y=113, wide=25, high=29)
        eye(223, y=113, wide=25, high=29)
        stroke([(60, 80), (124, 65)], 10)
        stroke([(196, 65), (260, 80)], 10)
        stroke([(116 + sway, 191), (137 + sway, 177), (160 + sway, 172 - flex),
                (183 + sway, 177), (204 + sway, 191)], 14)
    elif name == "angry":
        stroke([(62, 73), (131, 99)], 17)
        stroke([(189, 99), (258, 73)], 17)
        ellipse((73, 106 + bob, 128, 143 + bob))
        ellipse((192, 106 + bob, 247, 143 + bob))
        stroke([(122 + sway, 188), (160 + sway, 174), (198 + sway, 188)], 14)
    else:
        raise ValueError(name)
    return image.resize(SIZE, Image.Resampling.LANCZOS)


def main() -> None:
    assets = Path(__file__).resolve().parent / "emotion"
    for name in NAMES:
        frames = [frame(name, phase) for phase in range(20)]
        frames[0].save(assets / f"{name}.gif", save_all=True, append_images=frames[1:],
                       duration=100, loop=0, optimize=False)


if __name__ == "__main__":
    main()
