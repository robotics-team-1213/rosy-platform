"""Double-encoding (mojibake) check for operator-facing text at trust boundaries.

Pure: standard library only. A Korean name that went UTF-8 -> cp1252 text -> UTF-8 arrives as
Latin-1 looking text such as the mangled form of a Korean word; this finds exactly those strings.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

# runs of non-ASCII characters that a cp1252 decode of UTF-8 bytes can produce
_RUN = re.compile(r"[^\x00-\x7f]+")
# UTF-8 sequences whose invisible C1 bytes were dropped in transit (0x81 of a Hangul syllable)
_LEAD_TAIL = re.compile(rb"[\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{1,2}")


def _cp1252_bytes(run: str) -> bytes | None:
    out = bytearray()
    for ch in run:
        try:
            out += ch.encode("cp1252")
        except UnicodeEncodeError:
            if 0x80 <= ord(ch) <= 0x9F:  # cp1252 holes (0x81 0x8d 0x8f 0x90 0x9d) survive as C1 controls
                out.append(ord(ch))
            else:
                return None
    return bytes(out)


def looks_double_encoded(text: str) -> bool:
    """True when a non-ASCII run re-reads as UTF-8 non-ASCII text after a cp1252 round trip."""
    for run in _RUN.findall(text):
        raw = _cp1252_bytes(run)
        if raw is None:
            continue
        try:
            fixed = raw.decode("utf-8")
        except UnicodeDecodeError:
            if len(_LEAD_TAIL.findall(raw)) >= 2:  # shortcut: two broken pairs, a lone one may be real Latin
                return True
            continue
        # a lone 2-byte result is real Latin punctuation too often (a times sign + middle dot)
        if fixed != run and (len(fixed) >= 2 or ord(fixed) >= 0x800):
            return True
    return False


def double_encoded_paths(value: Any, path: str = "") -> Iterator[str]:
    """Paths (``places.3.name``) of every string inside JSON-like data that looks double encoded."""
    if isinstance(value, str):
        if looks_double_encoded(value):
            yield path or "."
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from double_encoded_paths(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from double_encoded_paths(item, f"{path}.{index}" if path else str(index))
