#!/usr/bin/env python3
"""Keep Picamera2's NULL preview usable when Ubuntu has no pykms binding.

The source archive is hash pinned before this exact three-line file is changed.
DRM preview remains explicitly unavailable; capture and the ROS JPEG preview
use Picamera2's NULL preview and do not need KMS or a display server.
"""

from pathlib import Path
import sys


ORIGINAL = (
    "from .drm_preview import DrmPreview\n"
    "from .null_preview import NullPreview\n"
    "from .qt_previews import QtGlPreview, QtPreview\n"
)
HEADLESS = (
    "from .null_preview import NullPreview\n"
    "try:\n"
    "    from .drm_preview import DrmPreview\n"
    "except ModuleNotFoundError as exc:\n"
    "    if exc.name not in ('kms', 'pykms'):\n"
    "        raise\n"
    "    class DrmPreview:\n"
    "        def __init__(self, *args, **kwargs):\n"
    "            raise RuntimeError('DRM preview is unavailable in the headless ROSY image')\n"
    "from .qt_previews import QtGlPreview, QtPreview\n"
)


def apply(path: Path) -> None:
    if path.read_text(encoding="utf-8") != ORIGINAL:
        raise ValueError("pinned Picamera2 preview imports changed; review the source")
    path.write_text(HEADLESS, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-picamera2-headless.py PREVIEWS_INIT")
    apply(Path(sys.argv[1]))
