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
import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class Finding:
    """One suspected secret."""

    path: str
    line_number: int
    kind: str
    excerpt: str

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.path}:{self.line_number}: {self.kind}: {self.excerpt}"


from secret_scan_syntax import (
    _PLACEHOLDER,
    _SECRET_NAME_WORDS,
    _ASSIGNMENT,
    _PYTEST_NODE_ID,
    _PRIVATE_KEY,
    _WPA_PSK,
    _WIFI_QR,
    _BARE_TOKEN,
    _PEER_VECTOR_PATH,
    _PEER_PUBLIC_VECTOR_VALUES,
    _CAMERA_PEER_VECTOR_PATH,
    _CAMERA_PEER_PUBLIC_VECTOR_VALUES,
    _is_public_account_vector,
    _is_public_peer_vector,
    _ED25519_SPKI_PREFIX,
    _is_ed25519_public_key_body,
    _URL,
    _PUBLIC_PATH_TOKEN,
    _PATH_WORD,
    _ABSORPTION_INVENTORY_SUFFIX,
    _CHECKSUM_MANIFEST_SUFFIX,
    _SHA256,
    _INTEGRITY_CONTEXT,
    _SECRET_WORD,
    _TYPE_EXPRESSION,
    _CODE_REFERENCE,
    _NUMERIC_CODE_CALL,
    _is_unclosed_fragment,
    _ENV_NAME,
    _ENV_LOOKUP,
    _ARGUMENT_LITERAL,
    _EXPRESSION_TEXT,
    _closes_on_this_line,
    _call_holds_no_literal,
    DEFAULT_EXCLUDED_NAMES,
    KNOWN_FIXTURES,
    KNOWN_PROSE_QUOTES,
    FIXTURE_ROOT,
    DEFAULT_EXCLUDED_SUFFIXES,
    _is_placeholder,
    _BARE_IDENTIFIER,
    _HEX_ONLY,
    _reads_the_environment,
    _is_a_passed_reference,
)


def load_public_provenance(path: Path) -> frozenset[tuple[str, str, str]]:
    """Load explicitly reviewed repository integrity tuples; malformed policy raises.

    No automatic discovery: image/runtime scans retain their default strict policy.
    Every tuple binds one token to one exact UTF-8 line and repository path.
    """
    doc = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(doc, dict) or set(doc) != {"schema", "records"}
            or doc["schema"] != "rosy.public-provenance/1"
            or not isinstance(doc["records"], list)):
        raise ValueError("invalid public provenance inventory")
    result = set()
    records = set()
    for record in doc["records"]:
        if not isinstance(record, dict) or set(record) != {"path", "line_sha256", "values", "reason"}:
            raise ValueError("invalid public provenance record")
        name, line_hash = record["path"], record["line_sha256"]
        if (not isinstance(name, str) or not name or "\\" in name or ":" in name
                or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                or PurePosixPath(name).as_posix() != name
                or not isinstance(line_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", line_hash)
                or not isinstance(record["reason"], str) or not record["reason"].strip()
                or not isinstance(record["values"], list) or not record["values"]):
            raise ValueError("invalid public provenance binding")
        if (name, line_hash) in records:
            raise ValueError("duplicate public provenance line")
        records.add((name, line_hash))
        for value in record["values"]:
            if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
                raise ValueError("public provenance requires exact hex digest")
            item = (name, line_hash, value)
            if item in result:
                raise ValueError("duplicate public provenance token")
            result.add(item)
    return frozenset(result)


def scan_text(path: str, text: str, *,
              public_provenance: frozenset[tuple[str, str, str]] = frozenset()) -> list[Finding]:
    """Return every suspected secret in ``text``.

    Split out from file walking so tests can prove the matchers fire on a
    planted sample — a scanner that only ever returns an empty list passes
    every repository check while protecting nothing.
    """
    findings: list[Finding] = []
    # Publisher added-line scans omit EOF newlines; bind the complete reviewed public certificate.
    public_os_cms_sha256 = 'c9b715ef42497e1e1f746529a882604e7159f7957f652d25977d56f49d9104a1'
    public_os_cms = (path == 'deploy/robot/pinky_pro/release/public-keys/rosy-os-cms-2026-01.pem'
                     and hashlib.sha256((text.rstrip('\r\n') + '\n').encode('utf-8')).hexdigest() == public_os_cms_sha256)
    lines = text.splitlines()
    sha_table: tuple[int, int] | None = None

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        cells = None
        if path.lower().endswith(".md") and stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped[1:-1].split("|")]
            if "SHA-256" in cells and number < len(lines):
                separator = lines[number].strip()
                if separator.startswith("|") and separator.endswith("|"):
                    parts = [part.strip() for part in separator[1:-1].split("|")]
                    if len(parts) == len(cells) and all(re.fullmatch(r":?-{3,}:?", part) for part in parts):
                        sha_table = (len(cells), cells.index("SHA-256"))
            elif sha_table and len(cells) != sha_table[0]:
                sha_table = None
        else:
            sha_table = None

        if _PRIVATE_KEY.search(line):
            findings.append(Finding(path, number, "private-key", stripped[:120]))
            continue

        wpa = _WPA_PSK.match(line)
        if (
            wpa
            and not _is_placeholder(wpa.group("value"))
            # A wpa_supplicant.conf never says psk=self.setup_psk; source that
            # passes a passphrase along must not read as one.
            and not _CODE_REFERENCE.match(wpa.group("value").rstrip(",}"))
        ):
            findings.append(Finding(path, number, "wifi-psk", stripped[:120]))
            continue

        qr = _WIFI_QR.search(line)
        if qr and not _is_placeholder(qr.group("value")):
            findings.append(Finding(path, number, "wifi-qr", stripped[:120]))
            continue

        node_id = (_PYTEST_NODE_ID.match(line)
                   if path.replace("\\", "/").endswith("test/known_failures.txt") else None)
        assignment_line = line[node_id.end():] if node_id else line
        if path.replace('\\', '/').endswith('.kt'):
            # Remove only a nullable String annotation before an assignment.
            # Keep its actual default visible: a quoted credential still reports.
            assignment_line = re.sub(
                rf'\b([A-Za-z0-9_]*(?:{_SECRET_NAME_WORDS})[A-Za-z0-9_]*)\s*:\s*String\??\s*=',
                r'\1 =', assignment_line, flags=re.IGNORECASE | re.VERBOSE)
        matched_assignment = False
        for match in _ASSIGNMENT.finditer(assignment_line):
            value = (match.group("quoted") or match.group("squoted")
                     or match.group("value") or match.group("call"))
            if (
                _is_placeholder(value)
                or (not (match.group('quoted') or match.group('squoted'))
                    and _is_placeholder(value.rstrip(')]},:')))
                or _TYPE_EXPRESSION.match(value)
                or _CODE_REFERENCE.match(value.rstrip(",}"))
                or ("(" not in value and _CODE_REFERENCE.match(value.rstrip("),}")))
                or (not (match.group('quoted') or match.group('squoted'))
                    and _NUMERIC_CODE_CALL.fullmatch(value))
                or (_is_unclosed_fragment(value)
                    and _call_holds_no_literal(assignment_line, match.end(), match.group("name")))
                or _reads_the_environment(value, assignment_line, match.end())
                or _is_a_passed_reference(assignment_line, match, value)
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
        if sha_table and cells and len(cells) == sha_table[0]:
            checksum = cells[sha_table[1]].strip("`")
            if _SHA256.fullmatch(checksum):
                cells[sha_table[1]] = ""
                entropy_line = _URL.sub(" ", "|".join(cells))
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
            if _is_public_peer_vector(path, line, value) or _is_public_account_vector(path, line, value):
                continue
            # Only this exact reviewed token is excused. Earlier private-key,
            # credential, PSK and QR checks remain active even on the same line.
            if (path, hashlib.sha256(line.encode("utf-8")).hexdigest(), value) in public_provenance:
                continue
            if _PUBLIC_PATH_TOKEN.fullmatch(value):
                continue
            # The base64 class has no "_", "." or "-", so it cuts a path such as
            # middleware/robot_ui/pilot/... at the underscore and resumes at the
            # next "/". Judge the whole path word the fragment sits in. A path
            # head never excuses a token: a piece of 32+ characters that holds a
            # digit or is all hex (robot_ui/<revision>, auth/v1/<JWT>) reports.
            head = re.search(_PATH_WORD + "$", entropy_line[:match.start("value")]).group(0)
            word = head + value + re.match(_PATH_WORD, entropy_line[match.end("value"):]).group(0)
            if _PUBLIC_PATH_TOKEN.fullmatch(word) and not any(
                    len(piece) >= 32 and (not piece.isalpha() or _HEX_ONLY.fullmatch(piece))
                    for piece in re.split(r"[/_.-]", word)):
                continue
            if _is_ed25519_public_key_body(value) or public_os_cms:
                continue
            # A run of letters that long is an identifier, not base64: base64
            # of any real payload lands on a digit or a "+/" well inside fifty
            # characters (P ~ 3e-5 for a letters-only run that long), while
            # missingPairingStillStartsCameraPreviewWithoutSendingFrames is a
            # Kotlin test name that needs no such luck. Hex is exempt — a
            # revision or digest written only with a-f is still integrity data.
            if value.isalpha() and not _HEX_ONLY.fullmatch(value):
                continue
            # A value this line also links to. URL bodies are outside this loop
            # entirely (_URL removes them), so a dependency pinned as
            # `https://host/o/r/tree/<sha>/path | <sha>` left the bare copy
            # looking unattributed. A secret is not its own link target.
            if any(value in url.group(0) for url in _URL.finditer(line)):
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
    public_provenance: frozenset[tuple[str, str, str]] = frozenset(),
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
        prose_quotes = KNOWN_PROSE_QUOTES.get(relative, frozenset())
        findings.extend(
            f for f in scan_text(relative, text, public_provenance=public_provenance)
            if not (in_fixtures and any(fixture in f.excerpt for fixture in KNOWN_FIXTURES))
            and not any(quote in f.excerpt for quote in prose_quotes)
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
