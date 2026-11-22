"""Update progress card renderer (D-433 row 3), pure PIL with passed D-82 palette."""

from __future__ import annotations

from PIL import Image, ImageDraw

from .lcd_primitives import _fit, _font

_STEP_LABELS = {
    "download": "Downloading",
    "unpack": "Unpacking",
    "verify": "Verifying",
    "activate": "Activating",
    "core-release-check": "Checking CORE",
    "image-layer-sync": "Syncing files",
    "restart": "Restarting",
    "health": "Health check",
    "rollback": "Rolling back",
}


def render_update(
    release: str | None,
    current: str | None,
    *,
    step: str | None = None,
    percent: int | None = None,
    size: tuple[int, int] = (320, 240),
    frame: int = 0,
    palette: tuple[tuple[int, int, int], ...],
    dim,
) -> Image.Image:
    """Draw the robot update card with progress bar, percentage ('--' when unknown), and step."""
    bg, fg, muted, warn = palette
    width, _height = size
    image = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(image)
    is_rollback = step == "rollback"
    title_text = "Rolling back" if is_rollback else "Updating"
    valid_pct = type(percent) is int and 0 <= percent <= 100
    pct_text = f"{percent}%" if valid_pct else "--"
    pct_font = _font(28)
    pct_w = int(draw.textlength(pct_text, font=pct_font))
    title_font, title_fit = _fit(draw, title_text, 30, max(48, width - 32 - pct_w - 12))
    draw.text((16, 20), title_fit, font=title_font, fill=dim(fg) if frame % 2 else fg)
    draw.text((width - 16, 20), pct_text, font=pct_font, fill=fg if valid_pct else muted, anchor="ra")

    bar = (16, 76, width - 16, 104)
    draw.rounded_rectangle(bar, radius=6, outline=muted, width=2)
    if valid_pct and percent > 0:
        inner_max = bar[2] - bar[0] - 8
        fill_w = max(4, int(inner_max * percent / 100))
        fill_color = warn if is_rollback else fg
        draw.rounded_rectangle((bar[0] + 4, bar[1] + 4, bar[0] + 4 + fill_w, bar[3] - 4), radius=3, fill=fill_color)

    caption = _STEP_LABELS.get(step or "", "")
    if caption:
        cap_font, cap_fit = _fit(draw, caption, 20, width - 32)
        draw.text((16, 122), cap_fit, font=cap_font, fill=fg)

    for idx, line in enumerate((f"to {release or '?'}", f"now {current or '?'}")):
        line_font, line_fit = _fit(draw, line, 18, width - 32)
        draw.text((16, 162 + idx * 28), line_fit, font=line_font, fill=muted)
    return image
