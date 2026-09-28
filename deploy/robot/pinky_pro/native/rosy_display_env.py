"""One reading of the boot display's switches (D-260 review L1).

``ROSY_BUZZER_ENABLED`` and ``ROSY_LAMP_ENABLED`` decide who owns the buzzer
line and the lamp node. rosy-boot-display reads them from its environment
(systemd applies /etc/rosy/boot-display.env), rosy-hw-test and rosy-hw-probe
from the file itself; all three must agree, so all three use this module.

Rules: surrounding whitespace and one pair of matching quotes are stripped;
exactly ``true`` or ``false`` counts; a missing key is the default (both are
on since D-260); anything else is off, and ``valid`` says so for a log line.
Standard library only.
"""

from __future__ import annotations

ENV_FILE = "etc/rosy/boot-display.env"
BUZZER_KEY = "ROSY_BUZZER_ENABLED"
LAMP_KEY = "ROSY_LAMP_ENABLED"
DEFAULTS = {BUZZER_KEY: True, LAMP_KEY: True}


def unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text


def parse_env(text: str) -> dict[str, str]:
    """KEY=VALUE lines as systemd's EnvironmentFile reads them (comments and blanks skipped)."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")) or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = unquote(value)
    return values


def flag(values: dict[str, str], key: str) -> tuple[bool, bool]:
    """(enabled, valid) for ``key``: missing -> the default; not exactly true/false -> off, invalid."""
    if key not in values:
        return DEFAULTS[key], True
    text = unquote(values[key])
    if text == "true":
        return True, True
    if text == "false":
        return False, True
    return False, False
