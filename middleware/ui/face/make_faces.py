"""Rebuild the eight small LCD face loops: python make_faces.py."""

from math import cos, pi, sin
from pathlib import Path

from PIL import Image, ImageDraw


SIZE = (320, 240)
PINK = "#ee4fcb"
BLACK = "#000000"
NAMES = ("hello", "basic", "angry", "bored", "fun", "happy", "interest", "sad")


def frame(name: str, phase: int) -> Image.Image:
    """One face; small motion keeps the silhouette stable at walking distance."""
    image = Image.new("RGB", SIZE, BLACK)
    draw = ImageDraw.Draw(image)
    motion = sin(2 * pi * phase / 20)
    bob = round(2 * motion)
    flex = round(4 * motion)
    sway = round(4 * cos(2 * pi * phase / 20))

    def eye(x, y=105, wide=31, high=35):
        draw.ellipse((x - wide, y - high + bob, x + wide, y + high + bob), fill=PINK)

    def stroke(points, width=13):
        draw.line([(x, y + bob) for x, y in points], fill=PINK, width=width, joint="curve")

    if name in ("basic", "hello"):
        eye(97, high=35 + flex)
        eye(223, high=35 + flex)
        if name == "basic":
            draw.ellipse((151 + sway, 170 + bob - flex, 169 + sway, 188 + bob + flex), fill=PINK)
        else:
            stroke([(116 + sway, 168), (136 + sway, 181), (160 + sway, 186 + flex),
                    (184 + sway, 181), (204 + sway, 168)], 14)
            stroke([(270, 66), (282, 53), (292, 67)], 8)
    elif name == "interest":
        draw.polygon([(43, 111 + bob), (95, 59 + bob - flex), (151, 111 + bob),
                      (95, 163 + bob + flex)], fill=PINK)
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
        stroke([(95 + sway, 159), (123 + sway, 184), (160 + sway, 195 + flex),
                (197 + sway, 184), (225 + sway, 159)], 20)
    elif name == "bored":
        draw.rounded_rectangle((61, 103 + bob, 133, 122 + bob + flex), radius=9, fill=PINK)
        draw.rounded_rectangle((187, 103 + bob, 259, 122 + bob + flex), radius=9, fill=PINK)
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
        draw.ellipse((73, 106 + bob, 128, 143 + bob), fill=PINK)
        draw.ellipse((192, 106 + bob, 247, 143 + bob), fill=PINK)
        stroke([(122 + sway, 188), (160 + sway, 174), (198 + sway, 188)], 14)
    else:
        raise ValueError(name)
    return image


def main() -> None:
    assets = Path(__file__).resolve().parent / "emotion"
    for name in NAMES:
        frames = [frame(name, phase) for phase in range(20)]
        frames[0].save(assets / f"{name}.gif", save_all=True, append_images=frames[1:],
                       duration=100, loop=0, optimize=False)


if __name__ == "__main__":
    main()
