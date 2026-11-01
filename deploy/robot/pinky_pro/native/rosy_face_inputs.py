"""rosy-face inputs and panel plumbing: test hand-over, update marker, switches, face frames, LCD open (D-433; moved out of rosy-face.py by D-766)."""

from __future__ import annotations

import json
import os
import re
import rosy_display_env
import stat
from pathlib import Path
from typing import Callable

from rosy_face_parts import Log

CORE_USER = "rosy-core"
FACE_LOAD_SKIP = 1  # 320x240 authored frames match the 10 fps panel tick
FACE_SIZE = (320, 240)
#: D-433 row 3: the updater (root) writes two lines, step and release id, while it applies.
UPDATE_DISPLAY = "run/rosy-boot/update-display.txt"
UPDATE_MAX_AGE_S = 1800.0  # a marker an updater crash left behind stops counting
RELEASE_ID = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}")
LCD_ATTEMPTS = 6  # udev may still be applying the device groups at start
LCD_RETRY_S = 5.0
RP1_LABEL = "pinctrl-rp1"
GPIOCHIP = "/dev/gpiochip4"
# Header BCM lines nothing else owns (board.yaml boot_display.buzzer; checked
# against its header_bcm_owners): not I2C0/1 (0-3), SPI0 (7-11), UART4 motor
# (12/13), UART0 LiDAR (14/15), the LCD (18/25/27) or the bench lamp (19).
BUZZER_LINES = frozenset({4, 5, 6, 16, 17, 20, 21, 22, 23, 24, 26})
# The Pinky Pro buzzer (board.yaml boot_display.buzzer.bcm_line), heard on rosy_18 2026-09-26.
BUZZER_DEFAULT_LINE = 4
TEST_ACTIONS = ("buzzer", "lamp", "identify_blue", "identify_amber", "identify_blue_quiet", "identify_amber_quiet")
TEST_REQUEST_MAX_AGE_S = 30.0
#: D-472 4: Fleet's identity window is <= 6 s from its request. rosy-hw-test passes an identify
#: on within 1.5 s, this program must take the hand-over within IDENTIFY_REQUEST_MAX_AGE_S
#: (two polls) and ends the 3 s blink by IDENTIFY_MAX_S whatever the helper does.
IDENTIFY_REQUEST_MAX_AGE_S = 1.0
MAX_TEST_REQUEST_BYTES = 512
TEST_REQUEST_ID = re.compile(r"[0-9a-f]{16,64}")


def read_test_request(path: Path, now: float) -> dict | None:
    """rosy-hw-test's hand-over, strictly: regular file, no link, small, known keys, fresh."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
        | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_TEST_REQUEST_BYTES:
            return None
        raw = os.read(descriptor, MAX_TEST_REQUEST_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or set(data) != {"action", "request_id", "requested_at"}:
        return None
    if data["action"] not in TEST_ACTIONS or not isinstance(data["request_id"], str) \
            or not TEST_REQUEST_ID.fullmatch(data["request_id"]):
        return None
    requested = data["requested_at"]
    if isinstance(requested, bool) or not isinstance(requested, (int, float)):
        return None
    limit = IDENTIFY_REQUEST_MAX_AGE_S if data["action"].startswith("identify_") else TEST_REQUEST_MAX_AGE_S
    if not -5.0 <= now - float(requested) <= limit:
        return None
    return data


def write_test_result(path: Path, content: str) -> None:
    """The outcome, replaced atomically in this unit's own runtime directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(temporary, path)


def buzzer_settings(environ: dict[str, str], log: Log) -> tuple[bool, int]:
    """ROSY_BUZZER_ENABLED (exactly true/false, default true since D-260 2) and ROSY_BUZZER_PIN (BCM)."""
    enabled, valid = rosy_display_env.flag(environ, rosy_display_env.BUZZER_KEY)
    if not valid:
        log.once("buzzer-config", "ROSY_BUZZER_ENABLED must be true or false, got "
                                  f"{environ.get('ROSY_BUZZER_ENABLED')!r}; buzzer off")
    pin_text = rosy_display_env.unquote(environ.get("ROSY_BUZZER_PIN", str(BUZZER_DEFAULT_LINE)))
    if not pin_text.isdigit() or int(pin_text) not in BUZZER_LINES:
        log.once("buzzer-config", f"ROSY_BUZZER_PIN {pin_text!r} is not a free header BCM line "
                                  f"{sorted(BUZZER_LINES)}; buzzer off")
        return False, BUZZER_DEFAULT_LINE
    return enabled, int(pin_text)


def lamp_enabled(environ: dict[str, str], log: Log) -> bool:
    """ROSY_LAMP_ENABLED (exactly true/false, default true, D-260 3)."""
    enabled, valid = rosy_display_env.flag(environ, rosy_display_env.LAMP_KEY)
    if not valid:
        log.once("lamp-config", "ROSY_LAMP_ENABLED must be true or false, got "
                                f"{environ.get('ROSY_LAMP_ENABLED')!r}; lamp off")
    return enabled


def read_update(root: Path, wall: float) -> dict | None:
    """D-433 row 3: the update marker the updater (root) writes while it applies, or None.

    Two lines, ``<step>`` and the candidate release id; nothing secret. A marker
    older than UPDATE_MAX_AGE_S is ignored, so a crashed updater cannot pin the screen.
    """
    path = root / UPDATE_DISPLAY
    try:
        if path.is_symlink() or not path.is_file() or wall - path.stat().st_mtime > UPDATE_MAX_AGE_S:
            return None
        lines = path.read_text(encoding="utf-8")[:256].splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines or not re.fullmatch(r"[a-z-]{1,32}", lines[0]):
        return None
    release = lines[1] if len(lines) > 1 and RELEASE_ID.fullmatch(lines[1]) else None
    return {"step": lines[0], "release": release}


class FaceFrames:
    """The emotion GIFs as panel bytes, converted once and lazily (D-433 decision 4).

    A face's frames are converted one per call while it first plays (every
    FACE_LOAD_SKIP-th GIF frame), so no single tick pays for a whole GIF and a
    face that is never shown is never loaded. Afterwards the bytes replay.
    """

    def __init__(self, directory: Path, *, opener: Callable[[Path], object],
                 convert: Callable[[object], object], log: Log, skip: int = FACE_LOAD_SKIP) -> None:
        self._directory = directory
        self._open = opener
        self._convert = convert
        self._log = log
        self._skip = skip
        self._faces: dict[str, dict] = {}

    def frame_count(self, name: str) -> int:
        return len(self._faces.get(name, {}).get("frames", []))

    def next(self, name: str):
        """The next panel frame of ``name``, or None when that GIF cannot be read."""
        entry = self._faces.get(name)
        if entry is None:
            entry = {"frames": [], "image": None, "done": False, "source": 0, "position": -1}
            try:
                entry["image"] = self._open(self._directory / f"{name}.gif")
            except (OSError, ValueError) as exc:
                self._log.once(f"face-{name}", f"face {name!r} unavailable ({type(exc).__name__})")
                entry["done"] = True
            self._faces[name] = entry
        if not entry["done"]:
            image = entry["image"]
            try:
                image.seek(entry["source"])
                entry["frames"].append(self._convert(image))
                entry["source"] += self._skip
                entry["position"] = len(entry["frames"]) - 1
                return entry["frames"][-1]
            except EOFError:
                pass
            except (OSError, ValueError) as exc:
                self._log.once(f"face-{name}-frame", f"face {name!r} frame unreadable ({type(exc).__name__})")
            entry["done"] = True
            entry["image"] = None
            if hasattr(image, "close"):
                image.close()
        if not entry["frames"]:
            return None
        entry["position"] = (entry["position"] + 1) % len(entry["frames"])
        return entry["frames"][entry["position"]]


def chip_label(path: str = GPIOCHIP) -> str | None:
    """The kernel label of a GPIO chip (GPIO_GET_CHIPINFO_IOCTL), or None."""
    import fcntl
    import struct

    info = bytearray(68)  # struct gpiochip_info: name[32], label[32], u32 lines
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    try:
        fcntl.ioctl(descriptor, 0x8044B401, info)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    return struct.unpack_from("32s", info, 32)[0].split(b"\0", 1)[0].decode("ascii", "replace")


def open_lcd(factory: Callable[[], object], label: Callable[[], str | None], log: Log,
             sleep: Callable[[float], None], cleanup: Callable[[], None] = lambda: None,
             attempts: int = LCD_ATTEMPTS):
    """The LCD, or None after ``attempts`` tries; the first failure and the give-up are logged.

    The GPIO chip label is read on every attempt, before the panel is touched:
    unreadable (udev race, ioctl error) is retried like a failed open and never
    driven blind; readable but not RP1 is final.
    """
    for attempt in range(1, attempts + 1):
        found = label()
        if found is not None and found != RP1_LABEL:
            log.once("lcd", f"{GPIOCHIP} is {found!r}, not the RP1 header ({RP1_LABEL}); LCD not driven")
            return None
        if found is None:
            log.once("lcd-label", f"cannot read the {GPIOCHIP} label yet; retrying")
        else:
            try:
                return factory()
            except Exception as exc:  # noqa: BLE001 - spidev/GPIO raise several kinds
                log.once("lcd", f"LCD unavailable ({type(exc).__name__}: {exc}); retrying")
                try:
                    cleanup()
                except Exception:  # noqa: BLE001
                    pass
        if attempt < attempts:
            sleep(LCD_RETRY_S)
    log.once("lcd-give-up", f"no LCD after {attempts} attempts")
    return None


def face_converter(info_screen) -> Callable[[object], object]:
    """A GIF frame (any size) -> panel bytes, the reduction done once per frame (D-185)."""
    from PIL import Image

    def convert(frame):
        landscape = frame.convert("RGB").resize(FACE_SIZE, Image.LANCZOS, reducing_gap=3.0)
        return info_screen.to_panel(info_screen.compose_face(landscape))

    return convert


def bar_painter(info_screen) -> Callable[..., object]:
    """Lay the status bar over a panel frame; the bar and its mask are made once per content."""
    from PIL import Image

    cache: dict[tuple, tuple] = {}

    def paint(frame, text: str, level: str, percent=None, charging=None):
        key = (text, level, percent, charging)
        if key not in cache:
            band, mask = info_screen.render_bar(text, level, percent, charging)
            cache.clear()  # one bar at a time
            cache[key] = (info_screen.to_panel(band),
                          info_screen.to_panel(Image.merge("RGB", (mask, mask, mask)))[..., 0] != 0)
        panel, where = cache[key]
        out = frame.copy()
        out[where] = panel[where]
        return out

    return paint


def core_owner(log: Log) -> int | None:
    """rosy-core's uid: face-inputs.json from anyone else is not CORE's (D-433 decision 3)."""
    try:
        import pwd
        return pwd.getpwnam(CORE_USER).pw_uid
    except (ImportError, KeyError):
        log.once("core-user", f"no {CORE_USER} account; face-inputs.json owner not checked")
        return None
