"""What the robot's LCD draws, decided once for every reader (D-433).

``rosy-face`` (native, no ROS, user rosy-display) owns the LCD, buzzer and lamp
for the robot's whole life; ``emotion_server`` (sim/bench ROS adapter) and
CORE's bridge use the same rules. They all import this module, so the screen
cannot be decided two ways. Standard library only, like ``robot_state``: the
native program loads it from the release's site-packages.

Three parts:

* ``screen_for`` - the situation table (D-433 decision 2). Rows 1-8 are status
  cards that hide the face; rows 9-17 keep the face and lay a strip or a card
  over it; row 18 puts the panel to sleep.
* the drive card cadence (D-394), moved here from ``core.bridge.display`` so the
  bridge and the face agree on it;
* the ``face-inputs.json`` hand-over (D-433 decision 3): CORE writes it every
  second, rosy-face reads it strictly and treats anything older than
  ``FACE_INPUTS_FRESH_S`` as absent - a dead CORE's last mode never lingers.

Unknown values are never guessed (D-385 decision 1): an unknown face is the
default face, an unknown mode is no mode.
"""

from __future__ import annotations

from datetime import datetime
import json
import math
import os
import stat
from typing import Any, Mapping, Optional

from core_common import robot_state

# --- the hand-over ------------------------------------------------------------

FACE_INPUTS_FILE = "/run/rosy/face-inputs.json"
FACE_INPUTS_SCHEMA = 1
#: CORE writes at least this often (and on every change at its 5 Hz tick).
FACE_INPUTS_PERIOD_S = 1.0
#: Three missed writes and the hand-over is gone: the screen goes back to the status card.
FACE_INPUTS_FRESH_S = 3.0
#: A clock that steps back a little (NTP) must not drop a good file.
FACE_INPUTS_FUTURE_S = 5.0
MAX_FACE_INPUTS_BYTES = 16 * 1024
MAX_NAME = 64
MAX_CARD_KEYS = 32

#: The emotion package's GIF vocabulary (D-385); set_emotion and rosy-face know these.
FACES = frozenset({"hello", "basic", "angry", "bored", "fun", "happy", "interest", "sad"})
DEFAULT_FACE = "basic"
POWER_MODES = frozenset({"active", "idle", "standby"})
DOCK_STATES = frozenset({"UNDOCKED", "DOCKING", "DOCKED", "CHARGING", "UNDOCKING", "DOCK_FAILED"})

#: Degradations only CORE knows, as codes; the LCD text is fixed here (ASCII: the card font has no Hangul).
CAUTION_TEXT = {
    "line_follow_hold": "Line follow holding: line lost",
    "dock_failed": "Docking failed: check the dock",
}

# --- the drive card cadence (D-394) ----------------------------------------------

DRIVE_EVERY_S = 20.0
DRIVE_HOLD_S = 5.0


def drive_due(mode: Any, now: float, last_pub: Optional[float],
              every_s: float = DRIVE_EVERY_S) -> bool:
    """Show the drive card on this tick? Only while operating, and slowly.

    IDLE belongs to the face (a face is a mood, a card is work). EMERGENCY is
    operating too: while stopped, what it stopped on must read at once.
    """
    if mode is None or mode == "IDLE":
        return False
    return last_pub is None or (now - last_pub) >= every_s


def drive_card_visible(mode: Any, since: Optional[float], now: float,
                       every_s: float = DRIVE_EVERY_S, hold_s: float = DRIVE_HOLD_S) -> bool:
    """The same cadence as a window: from ``since`` (the operating mode began), hold_s of every every_s."""
    if robot_state.valid_robot_mode(mode) not in robot_state.OPERATING_MODES or since is None:
        return False
    elapsed = now - since
    return elapsed >= 0 and (elapsed % every_s) < hold_s


# --- reading the hand-over ----------------------------------------------------------


def _name(value: Any, allowed: Optional[frozenset] = None) -> Optional[str]:
    if not isinstance(value, str) or not value or len(value) > MAX_NAME:
        return None
    if allowed is not None and value not in allowed:
        return None
    return value


def _flag(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _card(value: Any) -> Optional[dict]:
    """A flat card body: short string keys, scalar values only. Anything else drops the card."""
    if not isinstance(value, Mapping) or len(value) > MAX_CARD_KEYS:
        return None
    card: dict = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > MAX_NAME:
            return None
        if item is None or isinstance(item, bool):
            card[key] = item
        elif isinstance(item, (int, float)):
            if not math.isfinite(item):
                return None
            card[key] = item
        elif isinstance(item, str) and len(item) <= MAX_NAME:
            card[key] = item
        else:
            return None
    return card


def validate_face_inputs(data: Any, now: datetime) -> Optional[dict]:
    """The hand-over as the table reads it, or None (wrong schema, no time, stale, not an object).

    Envelope faults drop the whole file; a bad field is only that field's None
    (D-380 decision 6 rule: an unknown mode does not throw away a good card).
    """
    if not isinstance(data, Mapping):
        return None
    schema = data.get("schema")
    if type(schema) is not int or schema != FACE_INPUTS_SCHEMA:
        return None
    try:
        written = datetime.fromisoformat(str(data.get("written_at")))
    except ValueError:
        return None
    if written.tzinfo is None:
        return None
    age = (now - written).total_seconds()
    if not -FACE_INPUTS_FUTURE_S <= age <= FACE_INPUTS_FRESH_S:
        return None
    percent = _number(data.get("battery_percent"))
    caution = data.get("caution")
    codes = [code for code in caution if code in CAUTION_TEXT] if isinstance(caution, list) else []
    wake = _card(data.get("wake"))
    return {
        # When CORE wrote it: a reader may keep this hand-over until it is FACE_INPUTS_FRESH_S old.
        "written_ts": written.timestamp(),
        "robot_mode": robot_state.valid_robot_mode(data.get("robot_mode")),
        "nav_state": robot_state.valid_nav_state(data.get("nav_state")),
        "estop": _flag(data.get("estop")),
        "face": _name(data.get("face"), FACES),
        "power_mode": _name(data.get("power_mode"), POWER_MODES),
        "activity_kind": _name(data.get("activity_kind")),
        "docking_state": _name(data.get("docking_state"), DOCK_STATES),
        "battery_percent": percent if percent is not None and 0.0 <= percent <= 100.0 else None,
        "battery_charging": _flag(data.get("battery_charging")),
        "line_follow_mode": _name(data.get("line_follow_mode")),
        "line_follow_state": _name(data.get("line_follow_state")),
        "caution": sorted(set(codes)),
        "drive": _card(data.get("drive")),
        "wake": wake,
    }


def read_face_inputs(path: str, now: datetime, owner_uid: Optional[int] = None) -> Optional[dict]:
    """Read CORE's hand-over strictly: no link, no FIFO, a regular file of at most 16 KiB,
    owned by ``owner_uid`` when given, then ``validate_face_inputs``. Any fault is None.

    CORE is less trusted than the display (D-260 M1), so the reader never follows
    what CORE could point it at and never reads more than the bound.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FACE_INPUTS_BYTES:
            return None
        if owner_uid is not None and info.st_uid != owner_uid:
            return None
        raw = os.read(descriptor, MAX_FACE_INPUTS_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    if len(raw) > MAX_FACE_INPUTS_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return validate_face_inputs(data, now)


# --- the situation table ----------------------------------------------------------

SHUTDOWN = "shutdown"
STATUS = "status"
UPDATE = "update"
STOPPED = "stopped"
FACE = "face"
SLEEP = "sleep"
KINDS = (SHUTDOWN, STATUS, UPDATE, STOPPED, FACE, SLEEP)

#: D-433 table rows by the ``row`` the answer carries (tests walk every one).
ROWS = {
    "shutdown": 1, "failed": 2, "update": 3, "stopped": 4, "ap": 5, "booting": 6,
    "core_missing": 7, "login": 8, "standby": 18, "face": 17,
}
#: The backlight per CORE power mode (emotion_server's PWR-003 parameters).
BACKLIGHT = {"active": 100, "idle": 30, "standby": 0}
CALIBRATING_STRIP = "CALIBRATING - keep clear"
CORE_MISSING_LINE = "CORE not responding"
STOP_RELEASE = "Release: dashboard > E-stop reset"


def _stopped_cause(core: Mapping[str, Any]) -> str:
    """The STOPPED card's cause line (Q1). The snapshot carries the latch, not who pulled it."""
    if core.get("estop"):
        return "E-stop latched"
    return "Emergency stop"


def screen_for(*, stage: Any = None, state: Any = None, todo: Optional[str] = None,
               ap_mode: bool = False, login: Optional[str] = None,
               core: Optional[Mapping[str, Any]] = None, update: Optional[Mapping[str, Any]] = None,
               test: Optional[str] = None, shutting_down: bool = False,
               drive_since: Optional[float] = None, now: float = 0.0) -> dict:
    """The one answer for the LCD (D-433 decision 2). Higher rows win.

    ``stage``: boot-status stage; ``state``: ``robot_state.evaluate``'s state;
    ``todo``: its most urgent LCD todo; ``ap_mode``: the AP fallback is up and
    its key is readable; ``login``: ``"code"`` (an unused one-time code),
    ``"burned"`` or None; ``core``: ``validate_face_inputs`` output, None when
    missing or stale; ``update``: ``{"release": ...}`` while an update or an
    activation runs; ``test``: ``"buzzer"``/``"lamp"`` while a D-247 test plays;
    ``drive_since``: when the current operating mode began (monotonic).

    The answer: ``kind`` (one of KINDS), ``row`` (the table row id), ``face``,
    ``overlay`` (``{"kind": "drive"|"wake", "payload": {...}}``), ``strip`` and
    ``strip_tone`` (``caution``/``info``), ``backlight`` (%), ``awake`` and, for
    a stopped card, ``cause``/``release``.
    """
    answer = {"kind": STATUS, "row": "", "face": None, "overlay": None, "strip": None,
              "strip_tone": None, "backlight": 100, "awake": True}
    kind = robot_state.stage_kind(stage)

    def status(row: str, **extra: Any) -> dict:
        return {**answer, "kind": STATUS, "row": row, **extra}

    # Rows 1-8: a status card hides the face; a person must read a fact.
    if shutting_down:
        return {**answer, "kind": SHUTDOWN, "row": "shutdown"}
    if state == robot_state.FAILED or kind == "FAILED":
        return status("failed")
    if update is not None:
        return {**answer, "kind": UPDATE, "row": "update", "release": update.get("release")}
    if core is not None and (core.get("estop") or core.get("robot_mode") == "EMERGENCY"):
        return {**answer, "kind": STOPPED, "row": "stopped", "cause": _stopped_cause(core),
                "release": STOP_RELEASE}
    if ap_mode:
        return status("ap")
    if kind != "CORE_READY":
        return status("booting")
    if core is None:
        return status("core_missing", line=CORE_MISSING_LINE)
    if login == "code":
        return status("login")

    # Rows 9-11: strips under the face. Caution (Q3) outranks a test and calibration.
    caution = [CAUTION_TEXT[code] for code in core.get("caution") or [] if code in CAUTION_TEXT]
    # Text and tone are assigned apart: a (text, "info") pair reads as an event emit
    # to the D-8 catalogue guard (test_event_catalogue.py).
    strip = tone = None
    if state == robot_state.CAUTION or caution:
        strip = todo or (caution[0] if caution else "Caution")
        tone = "caution"
    elif test in ("buzzer", "lamp"):
        strip = f"Testing {test}"
        tone = "info"
    elif core.get("activity_kind") == "CALIBRATING":
        strip = CALIBRATING_STRIP
        tone = "info"

    mode = core.get("robot_mode")
    wake = core.get("wake")
    power = core.get("power_mode") or "active"
    # Row 18: standby sleeps the panel unless a wake card or a caution must be seen.
    if power == "standby" and wake is None and tone != "caution":
        return {**answer, "kind": SLEEP, "row": "standby", "backlight": BACKLIGHT["standby"], "awake": False}

    face = core.get("face") if core.get("face") in FACES else DEFAULT_FACE
    if core.get("activity_kind") == "CALIBRATING":
        face = "interest"
    overlay = None
    row = "face"
    if wake is not None:  # Row 12: the PWR-003 wake card, as long as CORE keeps it open.
        overlay, row = {"kind": "wake", "payload": dict(wake)}, "wake"
    elif core.get("drive") is not None and drive_card_visible(mode, drive_since, now):
        overlay, row = {"kind": "drive", "payload": {**core["drive"], "kind": "drive"}}, "drive"  # rows 13-16
    if strip is None and mode == "IDLE" and core.get("battery_charging"):  # row 13, resting on the dock
        percent = core.get("battery_percent")
        strip = f"Charging {percent:.0f}%" if percent is not None else "Charging"
        tone = "info"
    return {**answer, "kind": FACE, "row": row, "face": face, "overlay": overlay, "strip": strip,
            "strip_tone": tone, "backlight": BACKLIGHT.get(power, 100) if overlay is None else 100}
