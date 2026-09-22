"""Secret redaction for diagnostics that leave the device (D-175).

Standard library only; installed beside the native runtime. Every diagnostic
layer (boot-partition black box, collected bundles) passes text through
``redact`` and consults ``is_denied_path`` before reading a file. The black box
lands on a FAT32 partition anyone holding the card can read, so the rules err
toward removing too much.
"""

from __future__ import annotations

import re


# The repository secret scanner treats <...> as a placeholder, so redacted output
# passes it without an exception list.
REDACTED = "<redacted>"

# Files that are never read into a diagnostic, whatever their content.
DENIED_PATH_PARTS = (
    "/etc/NetworkManager/system-connections",
    "/boot/firmware/rosy-provision",
    "/etc/rosy/fleet-bootstrap.json",
    "/etc/ssh/ssh_host_",
    "/var/lib/rosy/secrets",
)
DENIED_NAME_WORDS = ("token", "secret", "password", "credential", ".key", "private")

_PEM = re.compile(
    r"-----BEGIN (?P<kind>[A-Z0-9 ]*PRIVATE KEY)-----.*?(?:-----END (?P=kind)-----|\Z)",
    re.DOTALL,
)
_AUTHORIZATION = re.compile(r"(?i)\b(authorization\s*[:=]\s*)(?:bearer|basic|token)?\s*\S+")
_ASSIGNMENT = re.compile(
    r"(?i)\b(?P<key>[\w.-]*(?:psk|password|passphrase|passwd|secret|token|api[_-]?key|"
    r"credential|private[_-]?key|pairing[_-]?credential)[\w.-]*)"
    r"(?P<sep>\s*[=:]\s*|\"\s*:\s*\")(?P<quote>[\"']?)(?P<value>[^\s\"',}]+)"
)
# Long opaque tokens (base64/url-safe). Pure hex is kept: digests, boot ids and
# unit hashes are what makes a report useful, and no ROSY secret is logged as hex.
_OPAQUE = re.compile(r"(?<![\w/+=-])(?=[A-Za-z0-9+/_-]*[A-Z])(?=[A-Za-z0-9+/_-]*[a-z])"
                     r"(?=[A-Za-z0-9+/_-]*\d)[A-Za-z0-9+/_-]{32,}={0,2}(?![\w/+=-])")


def redact(text: str) -> str:
    text = _PEM.sub(f"{REDACTED} private key", text)
    text = _AUTHORIZATION.sub(lambda m: m.group(1) + REDACTED, text)
    text = _ASSIGNMENT.sub(
        lambda m: f"{m.group('key')}{m.group('sep')}{m.group('quote')}{REDACTED}", text
    )
    return _OPAQUE.sub(REDACTED, text)


def is_denied_path(path: str) -> bool:
    normalized = "/" + path.replace("\\", "/").lstrip("/")
    if any(part in normalized for part in DENIED_PATH_PARTS):
        return True
    name = normalized.rsplit("/", 1)[-1].lower()
    return any(word in name for word in DENIED_NAME_WORDS)
