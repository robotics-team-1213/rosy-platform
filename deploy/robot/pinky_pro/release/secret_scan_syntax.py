"""Literal matching and reference classification shared by release secret scans."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re


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
#: The words that make a name worth reporting, in one place so the name
#: matcher and the "is this value itself secret-named" rule below cannot
#: drift apart and quietly disagree about what a secret is called.
_SECRET_NAME_WORDS = (
    r"passwo?rd | passwd | psk | passphrase | secret | api[_-]?key"
    r" | api[_-]?token | auth[_-]?token | access[_-]?token | bearer"
)

_ASSIGNMENT = re.compile(
    rf"""
    (?P<name>
        [A-Za-z0-9_.\-]*
        (?: {_SECRET_NAME_WORDS} )
        [A-Za-z0-9_.\-]*
    )
    \s* [:=] \s*
    (?:
        " (?P<quoted>[^"\n]{{6,}}) "     # "correct horse battery staple"
      | ' (?P<squoted>[^'\n]{{6,}}) '
      | (?P<value>[^"'\s#,;]{{6,}})     # bare, no spaces
      | (?P<call>[A-Za-z_][A-Za-z0-9_.]*[\(\[])   # wrap( , data[
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Pytest node IDs in test/known_failures.txt are identifiers, not assignments.
# A test name can contain terms such as "api_token" or "credential" and its
# `::` delimiter otherwise looks like a key/value separator to _ASSIGNMENT.
_PYTEST_NODE_ID = re.compile(
    r"^\s*test/[A-Za-z0-9_./-]+::test_[A-Za-z0-9_]+(?=\s{2}#|\s*$)"
)

_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"
)

# wpa_supplicant.conf style, which does not always use a secret-ish name.
_WPA_PSK = re.compile(r"^\s*psk\s*=\s*(?P<value>\S+)", re.IGNORECASE | re.MULTILINE)

# A Wi-Fi join QR payload (WIFI:T:WPA;S:<ssid>;P:<psk>;;) carries the AP
# passphrase itself; the boot LCD draws one and nothing may write it down.
_WIFI_QR = re.compile(r"WIFI:[^\n]*?(?<![A-Za-z])P:(?P<value>(?:\\.|[^;\\\n])+)", re.IGNORECASE)

# A bare high-entropy token on its own, e.g. a leaked hex API token.
_BARE_TOKEN = re.compile(r"\b(?P<value>[A-Fa-f0-9]{40,}|[A-Za-z0-9+/]{50,}={0,2})\b")

# Public cross-language transcript fixtures. This excuses only the exact
# entropy token on its exact JSON field/path, never a credential or PEM finding.
_PEER_VECTOR_PATH = 'middleware/robot_ui/pilot/android/app/src/test/resources/peer-transcripts.json'
_PEER_PUBLIC_VECTOR_VALUES = {
    'nonce': frozenset({'01' * 32, '02' * 32}),
    'public_key': frozenset({
        'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEC+iypgREmR8DKZo+83oOFx+SKJCeAcQBoCudNggdrhVKK5pTjj9YuYOtsux1l0lXAaRhvo2w+jtiKSbGHVdllA'}),
    'signature': frozenset({
        'MEUCIGj28eNNnlw4zwNwo3EYK4npeSZkJQrymIxZ+E3drcBkAiEA92Meq6XZCsVLfodbqnmAqBSxvaMR2WJsFLXEN4HvX8w'}),
}
_CAMERA_PEER_VECTOR_PATH = 'operations/site_ui/cam/app/src/test/resources/camera-peer-transcripts.json'
_CAMERA_PEER_PUBLIC_VECTOR_VALUES = {
    'nonce': frozenset({'01' * 32, '02' * 32}),
    'signature': frozenset({
        'MEQCIB8WKmontsmONrEJCGMhZ+ioZLoH4cDiBfq6s6FlP99GAiBtnNpxoX+FyYb20FDkoCxWsDWlZ50nT7yzs6l+5v+VAw=='}),
}


def _is_public_account_vector(path: str, line: str, value: str) -> bool:
    # D-757 Python-to-Kotlin signature vector: example.test/site:test, exp=1300.
    # Public, expired in 1970, and no private key; bind exact bytes and field/path.
    if path.replace('\\', '/') != 'operations/site_ui/cam/app/src/test/resources/account-access-v1.json':
        return False
    field = re.fullmatch(r'\s*"token":\s*"([A-Za-z0-9_.-]+)"\s*,?\s*', line)
    return bool(field and value in field.group(1)
                and hashlib.sha256(field.group(1).encode()).hexdigest()
                == '053e414728003393c86f702bd095f6ed00367cede6eb5b7718b18a707f446f48')


def _is_public_peer_vector(path: str, line: str, value: str) -> bool:
    allowed = {_PEER_VECTOR_PATH: _PEER_PUBLIC_VECTOR_VALUES,
               _CAMERA_PEER_VECTOR_PATH: _CAMERA_PEER_PUBLIC_VECTOR_VALUES,
               'test/fixtures/protocol/camera-peer.v1.json': _CAMERA_PEER_PUBLIC_VECTOR_VALUES}.get(path.replace('\\', '/'))
    if allowed is None:
        return False
    field = re.fullmatch(r'\s*"(nonce|public_key|signature)":\s*"([A-Za-z0-9+/=]+)"\s*,?\s*', line)
    return bool(field and field.group(2).rstrip('=') == value.rstrip('=')
                and value.rstrip('=') in {item.rstrip('=') for item in allowed.get(field.group(1), frozenset())})

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
_PATH_WORD = r"[A-Za-z0-9_./-]*"


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
# `source` is admitted only when it introduces a code span. A journal entry
# cites the tree it was built from as "merged source `<40-hex>`", but the bare
# word would also excuse `source_token = <hex>`, and a word that dismisses a
# line by itself is how a matcher goes quiet without anyone noticing.
# `SHA` and `HEAD` follow the same rule: research notes pin an upstream tree as
# "고정 SHA `<40-hex>`" or "HEAD `<40-hex>`". Only the code-span form is
# excused, so `sha_token = <hex>` or a bare "head <hex>" is still reported.
_INTEGRITY_CONTEXT = re.compile(
    r"(?<![A-Za-z])(?:sha[-_]?256|sha[-_]?512|digest|revision|checksum|commit|oid"
    r"|fingerprint|(?:source|sha|head)(?=\s*`))(?![A-Za-z])",
    re.IGNORECASE,
)

#: The words _ASSIGNMENT keys on, matched on their own.
_SECRET_WORD = re.compile(
    rf"(?: {_SECRET_NAME_WORDS} )", re.IGNORECASE | re.VERBOSE
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
    # The trailing () covers credential_status.inner_text(): a method call is
    # the same thing psk=self.setup_psk is — a read, not a value — and the
    # alternation below already grants a bare generate_setup_psk() that, so
    # leaving it off a dotted name was an omission, not a decision.
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+(?:\(\))?"
    r"|[A-Za-z_][A-Za-z0-9_]*\(\)"
    r")$"
)

# Only unquoted code can call a generator with a bounded integer byte count.
# The same text inside quotes remains a possible literal credential.
_NUMERIC_CODE_CALL = re.compile(
    r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\([0-9]{1,4}\)\Z')


# The head of a call or subscript expression, not a literal: prefs.getString(,
# created.json()[. The bare-value branch of _ASSIGNMENT stops at the first
# quote, a space or a comma, so a captured value that still owes a bracket was
# cut out of the middle of code and cannot be a finished literal —
# `getattr(args` is what a call looks like once its comma is gone, and
# `sha256(digest.encode(` is where a quote stopped it.
#
# Excusing the shape alone would hide password = wrap("hunter2swordfish"), so
# _call_holds_no_literal checks what the call was handed. Widening an exclusion
# is how a matcher goes quiet; this one stays narrow by asking that question.
def _is_unclosed_fragment(value: str) -> bool:
    """True when ``value`` opens a bracket it never closes on its own."""
    depth = 0
    for char in value:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
    return depth > 0


#: An environment-variable name as it is written in source: ROSY_VISION_SECRET.
#: ALL-CAPS with underscores and digits, which a credential is not shaped like.
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{2,}")

#: Reading the process environment. The argument to these is the *name* of a
#: variable to look up, never the secret itself — that is the whole reason the
#: product reads credentials from the environment instead of the repository.
_ENV_LOOKUP = re.compile(r"(?:os\.)?(?:environ\.get|getenv)\(|(?:os\.)?environ\[")

#: A quoted argument long enough to be a secret rather than a slot name.
#:
#: Deliberately higher than _ASSIGNMENT's six. In argument position the short
#: literals are overwhelmingly keys — "secret", "x-token", "psk" — and a
#: release gate that reports response.headers.get("x-token") teaches everyone
#: to skim past it, which costs more than the six- and seven-character secrets
#: it would catch one bracket deep. Directly assigned, those are still caught.
#: Candidates holding brackets are not string contents at all: see
#: _call_holds_no_literal, which pairs quotes across code.
_ARGUMENT_LITERAL = re.compile(r"""["']([^"'\n]{8,})["']""")

#: Expression text, never a credential handed to a call.
_EXPRESSION_TEXT = re.compile(r"[()\[\]]")


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
    slot_names = {name.lower(), re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name).lower()}
    return not any(
        not _is_placeholder(m.group(1)) and m.group(1).lower() not in slot_names
        # A "literal" holding brackets is expression text the quote pairing
        # bridged across, not a credential: in `authorization[len("Bearer "):]
        # ... startswith("Bearer ")` the regex pairs the first string's closing
        # quote with the next string's opening one, spanning `):] if ... (`.
        # A credential handed to a call never holds ()[].
        and not _EXPRESSION_TEXT.search(m.group(1))
        for m in _ARGUMENT_LITERAL.finditer(rest)
    )


# The scanner and syntax matcher sources would flag their own definitions. Nothing else is
# exempt by name: excluding a file makes it the one safe place to hide a
# secret, and a test file is exactly where one gets pasted "temporarily".
DEFAULT_EXCLUDED_NAMES = frozenset({"secret_scan.py", "secret_scan_syntax.py"})

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
    # The ER 2 adapter tests pass an obviously invented key next to a mock
    # transport. Deliberately invented; never a value a real deployment holds.
    "test-secret",
    # D-395 loc-assist tests feed an invented payload through the redaction
    # path. Deliberately invented; never a value a real deployment holds.
    "SECRET-PAYLOAD-VALUE",
    # The device Python runtime id pinned by test_python_runtime_id.py (D-189):
    # the sha256 of the tracked device-python-requirements.txt, recomputed by
    # that test from the repository itself — a public digest, never a credential.
    "a66f224ab570cb08d1c474bdbb1f93899692625cd167a7f6f907fc99690f4176",
})

#: Fixture values are only excused here. Anywhere else they are secrets.
FIXTURE_ROOT = "test/"

#: Journal prose that quotes an invented fixture value while describing its
#: own removal (operations/fleet/logs.md, 2026-09-29: the entry that replaced
#: an ``api_key="fixture-secret"`` literal with the allowlisted key quotes the
#: old value). The code literal is gone; module logs are append-only, so the
#: quote cannot be reworded. Pinned to one exact path per entry — the same
#: value anywhere else, including that module's code, is still a finding.
KNOWN_PROSE_QUOTES: dict[str, frozenset[str]] = {
    "operations/fleet/logs.md": frozenset({"fixture-secret"}),
}

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


#: A bare identifier: the shape of a variable name. Used to tell a reference
#: (`vision_lease_secret=secret`) from a literal that merely looks like one.
_BARE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: 40+ hex with nothing else in it, i.e. a revision or a digest written with
#: only the letters a-f. Those must stay reportable even though a run of
#: letters alone is never base64.
_HEX_ONLY = re.compile(r"[A-Fa-f0-9]{40,}")


def _reads_the_environment(value: str, line: str, start: int) -> bool:
    """True when every literal this line holds is an environment variable *name*.

    ``preview_secret = os.environ.get("ROSY_VISION_PREVIEW_SECRET")`` carries
    only the name of a variable to read: the credential lives in the process
    environment, never in source, so there is nothing here to leak.

    The literals have to be env-shaped for that to hold. The same call handed a
    credential as a default — ``api_key = os.environ.get("K", "sk_live_...")``
    — puts a real secret on the line and must still report, which is why a
    short or mixed-case argument keeps this from excusing the line.

    Only the text after the call head is read: the assignment head's own
    quotes — a test file's Python string delimiters around a sample, for
    instance — are not arguments and must not vote.
    """
    if not _ENV_LOOKUP.search(value):
        return False
    return all(
        _ENV_NAME.fullmatch(match.group(1))
        for match in _ARGUMENT_LITERAL.finditer(line[start:])
    )


def _is_a_passed_reference(line: str, match: re.Match[str], value: str) -> bool:
    """A secret-named bare identifier handed to a call, rather than a literal.

    ``create_app(console, ..., vision_lease_secret=secret)`` and a wrapped
    argument line ``vision_lease_secret=vision_preview_secret,`` both pass a
    variable along. Code that hands a secret around is what the scanner
    protects, not what it is looking for.

    Three conditions keep it narrow, plus one containment fallback. The value
    must be a bare identifier, so ``token=sk_live_9182aeb27c4d`` still reports
    — an unquoted credential in argument position is exactly the leak this rule
    must not swallow. It must be secret-named, so ``password = mypassword`` at
    statement level still reports. And it must sit in argument position, or be
    part of the name it is assigned to (``self._api_key = api_key``), which is
    where handing a variable happens.
    """
    reference = value.rstrip(")]},")
    if not _BARE_IDENTIFIER.fullmatch(reference):
        return False
    if not _SECRET_WORD.search(reference):
        return False
    head = line[: match.start()]
    depth = head.count("(") + head.count("[") - head.count(")") - head.count("]")
    if depth > 0 or line.rstrip().endswith(","):
        return True
    # `self._api_key = api_key`: the value is part of the name it is being
    # assigned to, so the line names a variable rather than supplying a
    # literal. Direction matters — `password = mysecret` still reports, since
    # `mysecret` is not inside `password`.
    return reference.lower() in match.group("name").lower()


