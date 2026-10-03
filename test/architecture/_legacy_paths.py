"""Old-path scan for D-427 step B moves (wave 0 item 4 of the migration plan).

A moved root records its old location as ``legacy``. ``LegacyScan`` finds text
that still points there in four forms:

- slash: ``src/site/fleet`` starting at a path-segment boundary, also after ``/``
  (``$WORKSPACE/src/...``, ``/repo/src/...``). Install paths are exempt: the token
  around the match (split on whitespace, quotes, ``= : , ; ( ) [ ] { }``) starts
  with ``/opt/``, ``/usr/`` or ``/etc/``.
- join: the segments as separate strings, ``"src" / "site" / "fleet"``,
  ``os.path.join("src", "site", ...)``, ``Path("src/site", "fleet")``.
- relative: ``../`` strings resolved from the file's folder and from each ancestor
  up to the repository root (covers gradle ``rootProject.file``).
"""

import posixpath
import re
from pathlib import PurePosixPath

#: D-226 history and decision records keep old paths on purpose.
HISTORY_DIRS = ("docs/adr/", "docs/plans/", "docs/validation/")
HISTORY_NAMES = {"logs.md", "progress.md"}
#: Identity-hash inputs: their bytes, comments included, must not change.
FROZEN_BYTES = {"deploy/robot/pinky_pro/image/device-python-requirements.txt"}
#: The manifest records ``legacy`` itself.
RECORDS = {"tools/harness/platform_parts.yaml"}
ROOT_FILES = {"env.sh", ".dockerignore", ".gitattributes", "AGENTS.md", "README.md"}
CURRENT_NOTES = {"AGENTS.md", "README.md"}
INSTALL_PREFIXES = ("/opt/", "/usr/", "/etc/")

_TOKEN_BREAK = re.compile(r"""[\s'"`=:,;()\[\]{}]""")
_RELATIVE = re.compile(r"(?:\.\./)+[\w./-]+")
_SEPARATOR = r"""(?:/|["']\s*[/,]\s*["'])"""
_START = r"(?<![\w.-])"
_END = r"(?![\w-]|\.\w)"


def in_scope(path: str) -> bool:
    pure = PurePosixPath(path)
    if path in FROZEN_BYTES or path in RECORDS or pure.name in HISTORY_NAMES:
        return False
    if path.startswith(HISTORY_DIRS):
        return False
    if len(pure.parts) == 1:
        return path in ROOT_FILES or path.endswith(".dockerignore")
    return pure.suffix.lower() != ".md" or pure.name in CURRENT_NOTES


def under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


class LegacyScan:
    """Precompiled per-legacy patterns. Each form is tried only when a cheap
    substring check says it can match: Python's ``re`` does not skip ahead on a
    lookbehind-anchored alternation, which costs seconds on the 40 MB meshes."""

    def __init__(self, legacies):
        self.legacies = sorted(set(legacies), key=len, reverse=True)
        self._slash = [
            (legacy, re.compile(f"{_START}{re.escape(legacy)}{_END}")) for legacy in self.legacies
        ]
        self._join = [
            (legacy, legacy.split("/"),
             re.compile(_START + _SEPARATOR.join(map(re.escape, legacy.split("/"))) + _END))
            for legacy in self.legacies if "/" in legacy
        ]

    def _legacy_of(self, path: str) -> str | None:
        return next((legacy for legacy in self.legacies if under(path, legacy)), None)

    def findings(self, path: str, text: str) -> list[tuple[str, str, str]]:
        """``(form, matched text, legacy root)`` for every old-path reference in ``text``.
        A slash match reports its whole path token."""
        # Every form names the legacy's last segment: a ../ string can only resolve
        # into legacy without it from a folder inside legacy, and such a file is
        # already reported as left behind.
        if not any(legacy.rsplit("/", 1)[-1] in text for legacy in self.legacies):
            return []
        found, starts = [], set()
        for legacy, pattern in self._slash:
            at = text.find(legacy)
            while at != -1:
                if at not in starts and pattern.match(text, at):
                    starts.add(at)
                    start, end = at, at + len(legacy)
                    while start > 0 and not _TOKEN_BREAK.match(text, start - 1):
                        start -= 1
                    while end < len(text) and not _TOKEN_BREAK.match(text, end):
                        end += 1
                    if not text.startswith(INSTALL_PREFIXES, start):
                        found.append(("slash", text[start:end], legacy))
                at = text.find(legacy, at + 1)
        for legacy, segments, pattern in self._join:
            if not all(segment in text for segment in segments):
                continue
            for match in pattern.finditer(text):
                if "'" in match.group(0) or '"' in match.group(0):
                    found.append(("join", match.group(0), legacy))
        if "../" in text:
            folders = PurePosixPath(path).parent.parts
            bases = ["/".join(folders[:depth]) for depth in range(len(folders), -1, -1)]
            for match in _RELATIVE.finditer(text):
                relative = re.sub(r"(?<=\w)\.$", "", match.group(0))
                for base in bases:
                    resolved = posixpath.normpath(posixpath.join(base, relative))
                    legacy = None if resolved.startswith("..") else self._legacy_of(resolved)
                    if legacy is not None:
                        found.append(("relative", match.group(0), legacy))
                        break
        return found
