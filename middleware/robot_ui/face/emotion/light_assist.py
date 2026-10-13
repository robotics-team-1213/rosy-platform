"""White LCD illumination card, rendered by the existing face owner."""

from PIL import Image, ImageDraw


def render_light_assist(size=(320, 240)):
    """White fill and a bulb symbol; no claim of camera recognition."""
    from .info_screen import _BG, _fit

    width, height = size
    image = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(image)
    cx, cy = width // 2, height // 2 - 24
    draw.ellipse((cx - 25, cy - 30, cx + 25, cy + 20), outline=_BG, width=4)
    draw.rectangle((cx - 12, cy + 18, cx + 12, cy + 36), outline=_BG, width=3)
    for dx, dy in ((-42, 0), (42, 0), (0, -47)):
        draw.line((cx + dx, cy + dy, cx + dx * 1.2, cy + dy * 1.2), fill=_BG, width=3)
    font, text = _fit(draw, "LIGHT ASSIST", 22, width - 32)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - box[2]) // 2, height - 52), text, font=font, fill=_BG)
    return image
