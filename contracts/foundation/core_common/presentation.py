"""What the robot shows, says and lights, decided once (D-433 amendment of 2026-10-09).

``rosy-face`` owns the LCD, the buzzer and the lamp. Before this module the lamp
(``robot_state.lamp_pattern``) and the screen (``face_screen.screen_for``) each
read the inputs on their own, so they could disagree: an e-stop latched without
the EMERGENCY mode drew the STOPPED card under a navigating lamp, and a CORE
caution code drew an amber strip under a ready lamp. ``present`` folds the same
inputs into one ``Presentation``; rosy-face lights the lamp, draws the status bar
and the expression, and picks the sound from that one record in the same tick.

Priority, highest first (D-546 extends D-380/D-381): FAILED > EMERGENCY (or a
latched e-stop) > RECOVERING > CAUTION (a health caution, or a CORE caution code)
> BOOTING > DOCKING > BLOCKED > NAVIGATING > MANUAL > READY. ``status_level`` is
the severity of the winning lamp pattern, so lamp, bar colour and expression can
never name different severities.

Standard library only, like ``robot_state``: rosy-face loads it from the
release's site-packages. Unknown or missing inputs are never guessed (D-385 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from core_common import robot_state

OK, CAUTION, DANGER = "ok", "caution", "danger"
LEVELS = (OK, CAUTION, DANGER)

#: Severity of each lamp pattern. ``bridging`` is the soft D-476 bridge (lamp only, no LCD cue).
LAMP_LEVEL = {
    "failed": DANGER, "emergency": DANGER,
    "recovering": CAUTION, "caution": CAUTION, "blocked": CAUTION,
    "bridging": OK, "booting": OK, "docking": OK, "navigating": OK, "manual": OK, "ready": OK,
    "illumination": OK,
}

#: The CORE-chosen face (D-385 vocabulary) a severity may keep. A cheerful face under an
#: amber lamp is the disagreement this table removes; ``sad``/``angry`` are the replacements.
FACE_BY_LEVEL = {
    OK: None,  # any face CORE chose
    CAUTION: ("basic", "interest", "sad", "bored", "angry"),
    DANGER: ("sad", "angry"),
}
FALLBACK_FACE = {CAUTION: "sad", DANGER: "angry"}

#: Health state -> buzzer sound on a state change (D-260 2). The e-stop alarm replaces it (D-381).
SOUNDS = {robot_state.READY: "ready", robot_state.READY_HELD: "ready",
          robot_state.FAILED: "failed", robot_state.CAUTION: "caution"}

#: ASCII status-bar text for the screens that are cards (the font has no Hangul).
CARD_TEXT = {
    "failed": "Boot failed", "update": "Updating", "ap": "Wi-Fi setup", "booting": "Booting",
    "core_missing": "CORE not responding", "login": "Login code", "peer_request": "Pair request",
    "light": "Light", "standby": "Standby", "shutdown": "Shutting down",
}
READY_TEXT = "Ready"


@dataclass(frozen=True)
class Presentation:
    """One tick's answer for lamp, bar, expression and sound.

    ``state``: the health state after CORE's caution codes (``robot_state`` names);
    ``lamp``: a ``lamp_pattern`` name; ``expression``: a face name, None when a
    card owns the screen; ``status_text``/``status_level``: the status bar;
    ``battery_percent``/``battery_charging``: None is unknown, never 0;
    ``sound``: the state sound (a rosy-face BUZZER_PATTERNS key) or None;
    ``reversing``: the D-546 reversing beep is due.
    """

    state: str
    lamp: str
    expression: Optional[str]
    status_text: str
    status_level: str
    battery_percent: Optional[float]
    battery_charging: Optional[bool]
    sound: Optional[str]
    reversing: bool


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def present(*, state: Any, robot_mode: Any = None, nav_state: Any = None,
            core: Optional[Mapping[str, Any]] = None, screen: Optional[Mapping[str, Any]] = None,
            battery_percent: Any = None) -> Presentation:
    """The one record. ``state``/``robot_mode``/``nav_state``/``battery_percent`` are the files'
    view (boot-status, the battery ADC); ``core`` is ``validate_face_inputs``' answer, None
    when CORE is missing or stale, and wins over the view when present; ``screen`` is
    ``screen_for``'s answer (without it only lamp, level and sound are meaningful)."""
    state = state if state in robot_state.STATES else robot_state.BOOTING
    estop = bool(core and core.get("estop"))
    if core:
        mode, nav = core.get("robot_mode"), core.get("nav_state")
        recovery = core.get("recovery") if not estop else None
        if state not in (robot_state.FAILED, robot_state.BOOTING) and core.get("caution"):
            state = robot_state.CAUTION  # a CORE caution code is a caution, not just an amber strip
    else:
        mode, nav, recovery = robot_mode, nav_state, None
    if estop:
        mode = "EMERGENCY"
    kind = screen.get("kind") if screen else None
    lamp = "illumination" if kind == "light" else robot_state.lamp_pattern(state, mode, nav, recovery)
    level = LAMP_LEVEL.get(lamp, OK)

    percent = core.get("battery_percent") if core else None
    percent = percent if percent is not None else battery_percent
    charging = core.get("battery_charging") if core else None

    expression = text = None
    if screen:
        if kind == "face":
            expression = _expression(screen.get("face"), level)
            text = _text(screen.get("strip")) or READY_TEXT
        elif kind == "stopped":
            text = _text(screen.get("cause")) or "Emergency stop"
        else:
            text = _text(screen.get("line")) or CARD_TEXT.get(screen.get("row"), READY_TEXT)
    sound = "emergency" if lamp == "emergency" else SOUNDS.get(state)
    return Presentation(state=state, lamp=lamp, expression=expression, status_text=text or READY_TEXT,
                        status_level=level, battery_percent=percent, battery_charging=charging,
                        sound=sound, reversing=bool(core) and core.get("estop") is False
                        and lamp == "recovering" and core.get("recovery") == "retrace")


def _expression(face: Any, level: str) -> Optional[str]:
    allowed = FACE_BY_LEVEL[level]
    if allowed is None or face in allowed:
        return face
    return FALLBACK_FACE[level]
