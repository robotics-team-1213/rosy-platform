"""Scan release inputs for embedded secrets.

The ROSY OS v1 release contract forbids per-device secrets in anything that
ships: no shared password, no shared API token, no Wi-Fi PSK, no SSH private
key in the repository, the container images or the SD image
(see the image/release design, sections 2.7, 12.1 and 12.2).

This module is the single scanner behind both checks. The repository check
runs in CI over tracked files; the image check (WP-6) will run the same
matchers over a mounted image tree. Keeping one implementation means a
pattern added for one check protects the other.

The scanner is deliberately conservative about placeholders: a config
template that says ``password: <your-wifi-password>`` is the correct thing
for a repository to contain, and flagging it would train people to ignore
the scanner.
"""

from __future__ import annotations

import base64
import binascii
import csv
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    """One suspected secret."""

    path: str
    line_number: int
    kind: str
    excerpt: str

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.path}:{self.line_number}: {self.kind}: {self.excerpt}"


# A value that is obviously a stand-in rather than a live secret. These are
# what a template, an example config or a doc is supposed to contain.
_PLACEHOLDER = re.compile(
    r"""
    <[^>]*>                       # <your-password>
    | \$\{[^}]*\}                 # ${ROSY_WIFI_PSK}
    | \$[A-Z_][A-Z0-9_]*          # $ROSY_WIFI_PSK
    | CHANGE_?ME | REPLACE_?ME | YOUR_[A-Z0-9_]+ | EXAMPLE | PLACEHOLDER
    | TODO | FIXME | None | null | true | false
    | \s*
    | [x*.\-_]+                   # xxxxxxxx / ******** / --------
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Assignment of a literal value to a secret-ish name. Group "value" is the
# literal; quotes are stripped by the caller.
#
# The six-character floor is about literals: shorter than that and a bare value
# is a keyword, a number or a type name rather than a secret. It is not about
# calls, and applying it to them left a hole — `api_token = wrap(` never
# reached any matcher because `wrap(` is five characters, which made a short
# function name the shortest way past this gate. The "call" branch recognises
# a call or subscript head at any length and hands it to the same rules that
# already judge the long ones: excused when it closes on this line holding no
# literal, reported otherwise.
#
# The false positive to expect is i18n: `api_key = _("settings.api_key_label")`
# is a one-character call around a key longer than the argument floor, and the
# key usually contains the variable's name without equalling it. Recognise the
# shape rather than loosening the argument rule for it — the rule is what keeps
# a secret handed to a call visible.
_ASSIGNMENT = re.compile(
    r"""
    (?P<name>
        [A-Za-z0-9_.\-]*
        (?: passwo?rd | passwd | psk | passphrase | secret | api[_-]?key
          | api[_-]?token | auth[_-]?token | access[_-]?token | bearer )
        [A-Za-z0-9_.\-]*
    )
    \s* [:=] \s*
    (?:
        " (?P<quoted>[^"\n]{6,}) "     # "correct horse battery staple"
      | ' (?P<squoted>[^'\n]{6,}) '
      | (?P<value>[^"'\s#,;]{6,})     # bare, no spaces
      | (?P<call>[A-Za-z_][A-Za-z0-9_.]*[\(\[])   # wrap( , data[
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"
)

# wpa_supplicant.conf style, which does not always use a secret-ish name.
_WPA_PSK = re.compile(r"^\s*psk\s*=\s*(?P<value>\S+)", re.IGNORECASE | re.MULTILINE)

# A bare high-entropy token on its own, e.g. a leaked hex API token.
_BARE_TOKEN = re.compile(r"\b(?P<value>[A-Fa-f0-9]{40,}|[A-Za-z0-9+/]{50,}={0,2})\b")

# SubjectPublicKeyInfo for Ed25519 is public integrity material, not a secret.
# Validate the complete DER shape rather than ignoring arbitrary base64 between
# PEM-looking markers.
_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _is_ed25519_public_key_body(value: str) -> bool:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(decoded) == 44 and decoded.startswith(_ED25519_SPKI_PREFIX)

# Public references, stripped before entropy matching: a long documentation URL
# is indistinguishable from base64 to a character-class matcher.
_URL = re.compile(r"\b(?:https?|ftp|git|ssh)://\S+")

# A prose list of public paths can look like a base64 token when several
# slash-separated words are written without spaces. It is not a credential:
# release-delivery examples use this shape for the ordered test boundaries.
_PUBLIC_PATH_TOKEN = re.compile(
    r"(?i)^[a-z][a-z0-9_.-]*(?:/[a-z][a-z0-9_.-]*)+/?$"
)

# The absorption inventory intentionally records source and destination
# SHA-256 values. They are public provenance fields, not device credentials.
# Scrub only CSV columns 3 and 4 for that one known inventory format; other
# long hex values remain subject to the normal matcher.
_ABSORPTION_INVENTORY_SUFFIX = "docs/plans/2026-09-12-control-absorption-inventory.csv"

# A checksum manifest (sha256sum output: "<64-hex>  <file>" per line) is by
# definition a list of public integrity hashes, one per shipped file. The
# leading hash column is scrubbed before entropy matching; filenames stay
# visible to the matchers.
_CHECKSUM_MANIFEST_SUFFIX = ".sha256"
_SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")

# Lines whose long hex is public integrity data rather than a secret.
#
# Alpha boundaries rather than \b: an underscore is a word character, so \b
# does not fall inside SLLIDAR_COMMIT= and that pinned git revision read as a
# leaked token. These boundaries still keep "oid" out of avoid/void/android.
# "hash" is deliberately absent — it turns up in ordinary prose, where it
# would disable this matcher for the whole line.
_INTEGRITY_CONTEXT = re.compile(
    r"(?<![A-Za-z])(?:sha[-_]?256|sha[-_]?512|digest|revision|checksum|commit|oid|fingerprint)(?![A-Za-z])",
    re.IGNORECASE,
)

# A type annotation, not an assignment of a literal. "bearer: Optional[str]" in
# a function signature is code, not a credential.
_TYPE_EXPRESSION = re.compile(
    r"^(?:Optional|Union|List|Dict|Sequence|Any|Iterable|Mapping|Tuple|Set|Callable"
    r"|str|int|bool|float|bytes|dict|list|set|tuple)\b",
)

# A reference to a value rather than the value itself: psk=self.setup_psk,
# psk=request.psk, psk=generate_setup_psk(). Code that hands a secret around
# is what the scanner protects, not what it is looking for.
#
# Narrow on purpose. A passphrase shaped exactly like a dotted identifier or
# a no-argument call is vanishingly unlikely, and widening an exclusion is
# how a matcher goes quiet without anyone noticing.
_CODE_REFERENCE = re.compile(
    r"^(?:"
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+"
    r"|[A-Za-z_][A-Za-z0-9_]*\(\)"
    r")$"
)


# The head of a call or subscript expression, not a literal: prefs.getString(,
# created.json()[. The bare-value branch of _ASSIGNMENT stops at the first
# quote, so a value ending in an opener means code started, never a secret.
#
# Excusing the shape alone would hide password = wrap("hunter2swordfish"), so
# _call_holds_no_literal checks what the call was handed. Widening an exclusion
# is how a matcher goes quiet; this one stays narrow by asking that question.
_CODE_EXPRESSION = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    r"(?:\(\))*"
    r"[\(\[]$"
)

#: A quoted argument long enough to be a secret rather than a slot name.
#:
#: Deliberately higher than _ASSIGNMENT's six. In argument position the short
#: literals are overwhelmingly keys — "secret", "x-token", "psk" — and a
#: release gate that reports response.headers.get("x-token") teaches everyone
#: to skim past it, which costs more than the six- and seven-character secrets
#: it would catch one bracket deep. Directly assigned, those are still caught.
_ARGUMENT_LITERAL = re.compile(r"""["']([^"'\n]{8,})["']""")


def _closes_on_this_line(rest: str) -> bool:
    """True when the bracket the call opened with is closed in ``rest``."""
    depth = 1
    for char in rest:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
            if depth == 0:
                return True
    return False


def _call_holds_no_literal(line: str, start: int, name: str) -> bool:
    """True when the call opening at ``start`` was handed no secret.

    This is what keeps the call-head exclusion from silencing the matcher:
    `password = decrypt_value("hunter2swordfish")` still reports.

    Two things are not secrets here. A literal that repeats the name being
    assigned is a slot to read from, not a value — `prefs.getString("secret")`.
    And the call must **close on this line**: when it does not, its arguments
    are somewhere we cannot see, and excusing what we have not read is how a
    formatter wrapping one line silently disarms this matcher.

    Closure is counted, not looked for. A bracket anywhere in the remainder is
    not the call closing — `_decode(  # base64 (D-30)` supplies one from a
    comment, and parenthesised ADR references are this repository's house
    style, so presence would hand the hole straight back.
    """
    rest = line[start:]
    if not _closes_on_this_line(rest):
        return False
    lowered = name.lower()
    return not any(
        not _is_placeholder(m.group(1)) and m.group(1).lower() != lowered
        for m in _ARGUMENT_LITERAL.finditer(rest)
    )


# This module's own matchers would flag their own source. Nothing else is
# exempt by name: excluding a file makes it the one safe place to hide a
# secret, and a test file is exactly where one gets pasted "temporarily".
DEFAULT_EXCLUDED_NAMES = frozenset({"secret_scan.py"})

#: Invented credential strings that appear in tests as deliberate fixtures.
#:
#: Applied only to files under FIXTURE_ROOT, and deliberately holding no PEM
#: header: listing "-----BEGIN OPENSSH PRIVATE KEY-----" here disarmed the
#: private-key matcher for the whole repository, which is the one artifact
#: the design is most explicit about keeping out. Tests that need a header
#: assemble it at runtime so no literal reaches the source.
KNOWN_FIXTURES = frozenset({
    "hunter2swordfish",
    "SuperSecretSitePsk99",
    "deadbeefcafebabe0123456789abcdef01234567",
    "Sk8rBoi9Delta",
    "correcthorsebattery",
    "correct horse battery staple",
    "sk_live_9182aeb27c4d",
    "Tr0ub4dor3xyz",
    "site-passphrase-not-to-be-kept",
    "liveEXAMPLEkey9182aeb27c4d",
    "MyEXAMPLEpass99",
    "notCHANGEMEreally123",
    "xxPLACEHOLDERxx9182aeb27",
    # An invented base64 blob used as a key body in the planted fixture.
    # Safe to excuse: it is a specific literal, not a matcher signal.
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW",
    # The network.connect fixture PSK used by the host-agent and host-card
    # tests. Deliberately invented; never a value a real device holds.
    "supersecretpsk",
    "fixture-pass-9384",
    "fixture-one-time-pairing-credential",
    "fixture-one-time-credential",
    "fixture-reusable-token",
    "must-never-ship",
})

#: Fixture values are only excused here. Anywhere else they are secrets.
FIXTURE_ROOT = "test/"

DEFAULT_EXCLUDED_SUFFIXES = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".pyc",
        ".stl", ".dae",
        # RViz layouts are serialised Qt window geometry — long hex runs that
        # look like tokens, in a file type that holds no credentials.
        ".rviz",
    }
)


def _is_placeholder(value: str) -> bool:
    """True when the whole value is a stand-in, not merely contains one.

    ``search`` dismissed any value holding a ``$`` followed by uppercase, so
    a real password like ``xK9$Qm2Lpz`` read as a template variable and was
    never reported. The alternatives above stay unwidened for the same
    reason: matching EXAMPLE as a substring dismissed
    ``liveEXAMPLEkey9182aeb27c4d``, which is a credential with a word in it.
    """
    return bool(_PLACEHOLDER.fullmatch(value.strip()))


def scan_text(path: str, text: str) -> list[Finding]:
    """Return every suspected secret in ``text``.

    Split out from file walking so tests can prove the matchers fire on a
    planted sample — a scanner that only ever returns an empty list passes
    every repository check while protecting nothing.
    """
    findings: list[Finding] = []

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        if _PRIVATE_KEY.search(line):
            findings.append(Finding(path, number, "private-key", stripped[:120]))
            continue

        wpa = _WPA_PSK.match(line)
        if (
            wpa
            and not _is_placeholder(wpa.group("value"))
            # A wpa_supplicant.conf never says psk=self.setup_psk; source that
            # passes a passphrase along must not read as one.
            and not _CODE_REFERENCE.match(wpa.group("value").rstrip(","))
        ):
            findings.append(Finding(path, number, "wifi-psk", stripped[:120]))
            continue

        matched_assignment = False
        for match in _ASSIGNMENT.finditer(line):
            value = (match.group("quoted") or match.group("squoted")
                     or match.group("value") or match.group("call"))
            if (
                _is_placeholder(value)
                or _TYPE_EXPRESSION.match(value)
                or _CODE_REFERENCE.match(value)
                or (_CODE_EXPRESSION.match(value)
                    and _call_holds_no_literal(line, match.end(), match.group("name")))
            ):
                continue
            # A reference to another variable or a path is not a literal secret.
            if value.startswith(("/", "./", "~", "@")):
                continue
            kind = "wifi-psk" if re.search(r"psk|passphrase", match.group("name"), re.IGNORECASE) else "credential"
            findings.append(Finding(path, number, kind, stripped[:120]))
            matched_assignment = True
        if matched_assignment:
            continue

        entropy_line = _URL.sub(" ", line)
        if path.replace("\\", "/").endswith(_ABSORPTION_INVENTORY_SUFFIX):
            try:
                fields = next(csv.reader([line]))
            except (csv.Error, StopIteration):
                fields = []
            if len(fields) >= 4:
                # Keep all non-provenance columns visible to the scanner.
                for index in (2, 3):
                    if _SHA256.fullmatch(fields[index] or ""):
                        fields[index] = ""
                entropy_line = ",".join(fields)
        elif path.replace("\\", "/").endswith(_CHECKSUM_MANIFEST_SUFFIX):
            fields = line.split(None, 1)
            if len(fields) == 2 and _SHA256.fullmatch(fields[0]):
                entropy_line = fields[1]

        for match in _BARE_TOKEN.finditer(entropy_line):
            value = match.group("value")
            if _PUBLIC_PATH_TOKEN.fullmatch(value):
                continue
            if _is_ed25519_public_key_body(value):
                continue
            # sha256 digests and git revisions are public integrity data, not
            # secrets, and the release manifest is full of them. Word-bounded:
            # unanchored, "oid" matched inside avoid/void/android and "hash"
            # inside any prose mentioning it, silently disabling this matcher.
            if _INTEGRITY_CONTEXT.search(line):
                continue
            findings.append(Finding(path, number, "high-entropy-token", stripped[:120]))
            break

    return findings


_TRANSIENT_SECRET_PATHS = frozenset({
    "/network/wpa_psk",
    "/fleet/pairing_credential",
})
_SECRET_FIELD = re.compile(
    r"(?:passwo?rd|passphrase|private[_-]?key|reusable[_-]?token|api[_-]?token|access[_-]?token|wpa[_-]?psk|pairing[_-]?credential)",
    re.IGNORECASE,
)


def _payload_items(value: object, path: str = "") -> Iterator[tuple[str, str, object]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}/{key}"
            yield child_path, str(key), child
            yield from _payload_items(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _payload_items(child, f"{path}/{index}")


def _payload_finding(path: str, kind: str, reason: str) -> Finding:
    # Never include the rejected value. This object is safe to render in logs.
    return Finding(path or "payload", 0, kind, reason)


def validate_transient_card_bundle(payload: Mapping[str, object]) -> list[Finding]:
    """Allow only the schema-scoped raw PSK and one-time Fleet credential."""
    findings: list[Finding] = []
    for path, key, value in _payload_items(payload):
        if isinstance(value, str) and _PRIVATE_KEY.search(value):
            findings.append(_payload_finding(path, "private-key", "private key material is forbidden"))
            continue
        if not _SECRET_FIELD.search(key):
            continue
        if path not in _TRANSIENT_SECRET_PATHS:
            findings.append(_payload_finding(path, "credential", "secret field is not permitted here"))
        elif path == "/network/wpa_psk" and (
            not isinstance(value, str) or not _SHA256.fullmatch(value)
        ):
            findings.append(_payload_finding(path, "wifi-psk", "PSK must be raw 64-hex output"))
        elif path == "/fleet/pairing_credential" and (
            not isinstance(value, str) or not 16 <= len(value) <= 512
        ):
            findings.append(_payload_finding(path, "credential", "one-time credential shape is invalid"))
    return findings


def validate_redacted_payload(payload: Mapping[str, object], *, path: str) -> list[Finding]:
    """Reject every secret-bearing path from receipts and log records."""
    findings: list[Finding] = []
    for item_path, key, value in _payload_items(payload):
        if _SECRET_FIELD.search(key):
            findings.append(_payload_finding(f"{path}{item_path}", "credential", "secret fields are forbidden"))
        elif isinstance(value, str) and _PRIVATE_KEY.search(value):
            findings.append(_payload_finding(f"{path}{item_path}", "private-key", "private key material is forbidden"))
    return findings


def scan_files(
    paths: Iterable[Path],
    *,
    root: Path,
    excluded_names: Sequence[str] = (),
) -> list[Finding]:
    """Scan each readable text file, reporting paths relative to ``root``."""
    excluded = set(DEFAULT_EXCLUDED_NAMES) | set(excluded_names)
    findings: list[Finding] = []

    for path in paths:
        if path.name in excluded or path.suffix.lower() in DEFAULT_EXCLUDED_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary: nothing to match against
        except OSError as exc:
            # Silently skipping made an unreadable file vacuously clean.
            findings.append(
                Finding(
                    str(path.relative_to(root)).replace("\\", "/"),
                    0,
                    "unscannable",
                    f"could not be read, so it was never checked: {exc}",
                )
            )
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        # Fixture values are excused inside test trees wherever they live —
        # repo-root test/ and the per-package test/ directories of the
        # domain-grouped workspace. Anywhere else they are secrets.
        in_fixtures = relative.startswith(FIXTURE_ROOT) or "/test/" in f"/{relative}"
        findings.extend(
            f for f in scan_text(relative, text)
            if not (in_fixtures and any(fixture in f.excerpt for fixture in KNOWN_FIXTURES))
        )

    return findings


def iter_tracked_files(root: Path) -> Iterator[Path]:
    """Yield files git tracks under ``root``.

    Tracked files are the right scope: an untracked scratch file is not
    shipped, and .gitignore already keeps build output out.
    """
    import subprocess

    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    for name in result.stdout.decode("utf-8").split("\0"):
        if not name:
            continue
        path = root / name
        if path.is_file():
            yield path
