"""Secret redaction for diagnostics that leave the device (D-175).

Standard library only; installed beside the native runtime. Every diagnostic
layer (boot-partition black box, collected bundles) passes text through
``redact`` and consults ``is_denied_path`` before reading a file. The black box
lands on a FAT32 partition anyone holding the card can read, so the rules err
toward removing too much. Every pattern is anchored and bounded so a hostile
48 KiB journal line redacts in linear time.
"""

from __future__ import annotations

import re


# The repository secret scanner treats <...> as a placeholder, so redacted output
# passes it without an exception list.
REDACTED = "<redacted>"
MAX_LINE = 4096

# Files that are never read into a diagnostic, whatever their content.
DENIED_PATH_PARTS = (
    "/etc/NetworkManager/system-connections",
    "/boot/firmware/rosy-provision",
    "/etc/rosy/fleet-bootstrap.json",
    "/etc/ssh/ssh_host_",
    "/var/lib/rosy/secrets",
)
DENIED_NAME_WORDS = ("token", "secret", "password", "credential", ".key", "private")

_SECRET_WORD = (r"(?:psk|password|passphrase|passwd|secret|token|api[_-]?key|credential|"
                r"private[_-]?key|cookie)")
_PEM = re.compile(
    r"-----BEGIN (?P<kind>[A-Z0-9 ]{0,40}PRIVATE KEY)-----.*?(?:-----END (?P=kind)-----|\Z)",
    re.DOTALL,
)
_AUTHORIZATION = re.compile(r"(?i)(?<![\w-])(authorization\s{0,8}[:=]\s{0,8})[^\n]{1,4096}")
_COOKIE = re.compile(r"(?i)(?<![\w-])((?:set-)?cookie\s{0,8}:\s{0,8})[^\n]{1,4096}")
_USERINFO = re.compile(r"(?i)(?<![\w+.-])([a-z][a-z0-9+.-]{0,15}://)[^\s/@:]{1,256}:[^\s/@]{1,256}@")
_CLI_ARGUMENT = re.compile(
    r"(?i)(?<![\w.-])((?:wifi-sec\.psk|802-11-wireless-security\.psk|--?(?:password|passphrase|token|psk))"
    r"\s{1,8})(\S{1,4096})"
)
# key[ sep ]value, where the key may be quoted (JSON, Python repr) and the value
# may be quoted (then it may contain spaces). Starts only at a token boundary and
# every repetition is bounded, which keeps the scan linear.
_ASSIGNMENT = re.compile(
    r"(?i)(?<![\w.-])(?P<key>['\"]?[\w.-]{0,40}" + _SECRET_WORD + r"[\w.-]{0,40}['\"]?)"
    r"(?P<sep>\s{0,8}[=:]\s{0,8})"
    r"(?P<value>\"[^\"\n]{0,4096}\"|'[^'\n]{0,4096}'|[^\s,;}\])'\"]{1,4096})"
)
# Long opaque tokens (base64/url-safe). Pure hex without a secret-ish key is kept:
# digests, boot ids and unit hashes make a report useful. A keyed hex WPA PSK is
# caught by the assignment rule above.
_OPAQUE = re.compile(r"(?<![\w/+=-])(?=[A-Za-z0-9+/_-]{0,4096}[A-Z])(?=[A-Za-z0-9+/_-]{0,4096}[a-z])"
                     r"(?=[A-Za-z0-9+/_-]{0,4096}\d)[A-Za-z0-9+/_-]{32,4096}={0,2}(?![\w/+=-])")


def _assignment(match: re.Match) -> str:
    value = match.group("value")
    quote = value[0] if value[:1] in {"'", '"'} and value[-1:] == value[:1] and len(value) > 1 else ""
    return f"{match.group('key')}{match.group('sep')}{quote}{REDACTED}{quote}"


def _redact_line(line: str) -> str:
    line = _AUTHORIZATION.sub(lambda m: m.group(1) + REDACTED, line)
    line = _COOKIE.sub(lambda m: m.group(1) + REDACTED, line)
    line = _USERINFO.sub(lambda m: m.group(1) + REDACTED + "@", line)
    line = _CLI_ARGUMENT.sub(lambda m: m.group(1) + REDACTED, line)
    line = _ASSIGNMENT.sub(_assignment, line)
    return _OPAQUE.sub(REDACTED, line)


def redact(text: str) -> str:
    """Redact secrets; lines longer than MAX_LINE are cut first."""
    text = _PEM.sub(f"{REDACTED} private key", text)
    return "\n".join(_redact_line(line[:MAX_LINE]) for line in text.split("\n"))


def is_denied_path(path: str) -> bool:
    normalized = "/" + path.replace("\\", "/").lstrip("/")
    if any(part in normalized for part in DENIED_PATH_PARTS):
        return True
    name = normalized.rsplit("/", 1)[-1].lower()
    return any(word in name for word in DENIED_NAME_WORDS)
