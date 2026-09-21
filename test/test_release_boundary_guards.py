"""Privilege- and secret-boundary guards for the ROSY OS release contract.

Two boundaries in the image/release design are cheap to state and expensive
to lose:

* CORE is the robot API, not a host administrator. It must not own ``/dev``
  devices, the Docker socket, or host root (design sections 2.13, 4.2, 12.1).
  A future Host Agent gets those responsibilities as a separate least-
  privilege process.
* Nothing that ships carries a secret — no shared password, no shared API
  token, no Wi-Fi PSK, no SSH private key (design sections 2.7, 12.1, 12.2).

Today's ``compose.yaml`` already satisfies the first. These tests exist to
keep it that way: the boundary is one convenience mount away from being gone,
and the loss would not be obvious in review.

``test_robot_runtime.py`` also asserts parts of this, but by exact string
(``"/var/run/docker.sock:/var/run/docker.sock" not in mounts``). That form
passes the moment someone writes the same mount with a ``:ro`` suffix or via
``/run/docker.sock``. The checks here are structural instead.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

import pytest
import yaml
from secret_scan import iter_tracked_files, scan_files, scan_text  # via test/conftest.py

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "robot" / "compose.yaml"
ENV_EXAMPLE = ROOT / "deploy" / "robot" / ".env.example"
RUNTIME_MODE = ROOT / "deploy" / "robot" / "runtime-mode.sh"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def core(compose: dict) -> dict:
    return compose["services"]["rosy-core"]


# Every mount in this compose file is written ${VAR:-/default/path}, and that
# default contains a colon. Splitting the raw string on the first colon
# therefore yields "${ROSY_CONFIG_PATH" and every host-side check is evaluated
# against garbage — which silently passed a planted docker.sock and a planted
# host-root bind. Expand the defaults before splitting.
_COMPOSE_VAR = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")


def _expand(mount: str) -> str:
    """Substitute ``${VAR:-default}`` with its default value."""
    return _COMPOSE_VAR.sub(lambda m: m.group("default") or "", mount)


def _split_mount(mount: str) -> tuple[str, str, str]:
    """Return (host, container, mode) for a bind, with defaults expanded.

    Fails closed: a mount still carrying an unexpanded ``${...}`` after
    substitution has no default, so its host path is decided at runtime and
    this file cannot vouch for it.
    """
    expanded = _expand(mount)
    assert "${" not in expanded, (
        f"mount has a runtime-decided host path this guard cannot check: {mount}"
    )
    parts = expanded.split(":")
    host = parts[0]
    container = parts[1] if len(parts) > 1 else ""
    mode = parts[2] if len(parts) > 2 else "rw"
    return host, container, mode


def _host_side(mount: str) -> str:
    return _split_mount(mount)[0]


def _container_side(mount: str) -> str:
    return _split_mount(mount)[1]


# --- CORE privilege boundary ---------------------------------------------


def test_core_owns_no_devices(core):
    assert "devices" not in core, "CORE must not be handed /dev nodes"
    assert "device_cgroup_rules" not in core


def test_core_is_not_privileged(core):
    assert core.get("privileged", False) is False
    assert "cap_add" not in core, "CORE must not add capabilities back"


def test_core_drops_all_capabilities(core):
    assert core["cap_drop"] == ["ALL"]


def test_core_forbids_privilege_escalation(core):
    security_opt = core["security_opt"]
    assert "no-new-privileges:true" in security_opt
    # Unconfining seccomp or AppArmor would undo the rest of the boundary.
    for option in security_opt:
        assert "unconfined" not in option, f"CORE relaxes confinement: {option}"


def test_core_filesystem_is_read_only(core):
    assert core["read_only"] is True


#: Directories that hold a container-runtime socket. Mounting any of these,
#: or any ancestor, hands over the socket just as surely as naming it.
SOCKET_PATHS = (
    PurePosixPath("/var/run/docker.sock"),
    PurePosixPath("/run/docker.sock"),
    PurePosixPath("/var/run/podman/podman.sock"),
    PurePosixPath("/run/podman/podman.sock"),
    PurePosixPath("/run/containerd/containerd.sock"),
    PurePosixPath("/var/run/containerd/containerd.sock"),
)


def test_core_never_receives_a_container_runtime_socket(core):
    """Any runtime socket, in any form — including via a parent directory.

    Checking for the substring "docker.sock" misses ``/var/run:/host/run:ro``,
    which hands over the same socket inside a directory bind. And :ro is no
    defence: a read-only bind stops the inode being replaced, not messages
    being sent through the socket.
    """
    for mount in core.get("volumes", []):
        host = PurePosixPath(_host_side(mount))
        for socket in SOCKET_PATHS:
            assert not (host == socket or host in socket.parents), (
                f"CORE is handed {socket} via {mount}"
            )


def test_core_never_receives_host_root(core):
    """Any bind whose host side is / — with or without a :ro suffix."""
    for mount in core.get("volumes", []):
        host = _host_side(mount)
        assert host != "/", f"CORE gets host root: {mount}"
        container = _container_side(mount)
        assert container not in {"/", "/host/root", "/rootfs"}, (
            f"CORE mounts something as a root filesystem: {mount}"
        )


#: The one host path CORE is allowed to write. It holds the robot's own data,
#: which CORE owns. Everything else it sees must be read-only.
WRITABLE_HOST_PATHS = frozenset({"/var/lib/rosy"})


def test_core_writes_to_nothing_on_the_host_but_its_own_data(core):
    """Enumerate what may be writable rather than filtering what to check.

    A prefix filter over /proc /sys /etc /dev /run skipped every other host
    path entirely, so a new writable bind outside those prefixes was never
    examined at all.
    """
    for mount in core.get("volumes", []):
        host, _container, mode = _split_mount(mount)
        if mode == "ro":
            continue
        assert host in WRITABLE_HOST_PATHS, f"CORE writes to an unexpected host path: {mount}"


def test_the_writable_data_path_holds_the_authority_over_boot(core):
    """Name the exposure rather than assert a function exists.

    activation.json, the update journal and release-state.json live under
    /var/lib/rosy, which CORE writes. That is why read_activation validates
    the record instead of trusting it — the containment itself is tested
    behaviourally in test_release_layout.py, not by grepping for a symbol.
    """
    from layout import Layout

    layout = Layout.default()
    for path in (layout.activation, layout.journal, layout.release_state):
        assert str(path).replace("\\", "/").startswith("/var/lib/rosy")

    # Which paths are writable is enforced by
    # test_core_writes_to_nothing_on_the_host_but_its_own_data; what this test
    # adds is that the writable one contains the boot authority.
    writable = {
        _split_mount(mount)[0]
        for mount in core.get("volumes", [])
        if _split_mount(mount)[2] != "ro"
    }
    assert str(Layout.default().activation).replace("\\", "/").startswith(tuple(writable))


def test_core_joins_no_extra_host_groups(core):
    """group_add is how a container gets dialout (UART) without a device."""
    assert "group_add" not in core, "CORE must not join host groups such as dialout"


def test_core_does_not_share_host_process_namespaces(core):
    for key in ("pid", "ipc", "userns_mode", "cgroup"):
        value = core.get(key)
        assert value != "host", f"CORE shares the host {key} namespace"


def test_core_uses_the_host_network_deliberately(core):
    """network_mode: host is required, and its consequence is written down.

    ROS 2 discovery needs it. It is the reason the Host Agent is reached over
    a unix socket rather than a loopback port — with the host network, a
    loopback bind is reachable by every process on the machine. Asserting it
    here keeps the claim and the configuration together.
    """
    assert core["network_mode"] == "host"

    contract = (ROOT / "docs" / "reference" / "rosy-host-agent-contract.md").read_text(
        encoding="utf-8"
    )
    assert "network_mode: host" in contract, (
        "the Host Agent contract must keep explaining why the host network forces a socket"
    )


def test_core_runs_as_a_non_root_user(core):
    user = core["user"]
    assert not user.startswith("0:"), "CORE must not run as uid 0"
    assert user == "${ROSY_UID:-1000}:${ROSY_GID:-1000}"


# --- default runtime mode is core-only -----------------------------------


def test_hardware_services_are_gated_behind_compose_profiles(compose):
    """A plain `docker compose up` must start CORE and nothing else."""
    services = compose["services"]
    assert services["rosy-motor"]["profiles"] == ["motor"]
    assert services["rosy-io"]["profiles"] == ["hardware"]
    assert "profiles" not in services["rosy-core"], "CORE is the default service"


def test_declared_default_runtime_mode_is_core():
    assert "ROSY_RUNTIME_MODE=core" in ENV_EXAMPLE.read_text(encoding="utf-8")


def test_runtime_mode_wrapper_falls_back_to_core():
    script = RUNTIME_MODE.read_text(encoding="utf-8")
    assert 'MODE="${ROSY_RUNTIME_MODE:-core}"' in script
    assert 'MODE="${configured_mode:-core}"' in script, (
        "an empty ROSY_RUNTIME_MODE in .env must still mean core, not hardware"
    )


# --- no shipped secrets ---------------------------------------------------


def test_no_secrets_in_tracked_files():
    findings = scan_files(iter_tracked_files(ROOT), root=ROOT)
    assert not findings, "secrets found in tracked files:\n" + "\n".join(
        str(f) for f in findings
    )


def _pem_header(label: str) -> str:
    """Build a PEM header at runtime.

    No PEM header literal may appear in this source. Listing one as a known
    fixture is what disarmed the private-key matcher for the whole repository
    — the header is the matcher's entire signal, so excusing it anywhere
    excuses it everywhere. Assembling it here keeps the matcher armed while
    still exercising it.
    """
    return "-" * 5 + "BEGIN " + label + "-" * 5


def test_a_private_key_under_the_test_tree_is_still_reported(tmp_path):
    """Exercised through scan_files, the function CI actually runs.

    Asserting against scan_text proved nothing about CI: scan_text never
    applies the fixture allowances, so it stayed green while the production
    path was blind to every PEM header in the repository.
    """
    planted = tmp_path / "test" / "test_something.py"
    planted.parent.mkdir(parents=True)
    planted.write_text(_pem_header("OPENSSH PRIVATE KEY") + "\n", encoding="utf-8")

    findings = scan_files([planted], root=tmp_path)
    assert any(f.kind == "private-key" for f in findings), (
        "a private key under test/ must still be reported; the fixture "
        "allowance must never cover a PEM header"
    )


def test_the_fixture_allowance_does_not_reach_outside_the_test_tree(tmp_path):
    """A fixture value is only a fixture where fixtures live."""
    outside = tmp_path / "deploy" / "robot"
    outside.mkdir(parents=True)
    (outside / "leaked.env").write_text("ROSY_API_TOKEN=" + "deadbeef" * 5, encoding="utf-8")

    findings = scan_files([outside / "leaked.env"], root=tmp_path)
    assert findings, "a known fixture value outside test/ is still a secret"


PLANTED = "\n".join([
    _pem_header("OPENSSH PRIVATE KEY"),
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW",
    "wifi_password: hunter2swordfish",
    "psk=SuperSecretSitePsk99",
    "ROSY_API_TOKEN=deadbeefcafebabe0123456789abcdef01234567",
])

PLACEHOLDERS = """\
wifi_password: <your-wifi-password>
psk=${ROSY_WIFI_PSK}
api_token = "CHANGE_ME"
admin_password: REPLACE_ME
def authenticate(config: dict, bearer: Optional[str]) -> AuthContext:
image digest sha256: a3f9c2e81b7d4056af92e310cb77aa019283746511223344556677889900aabb
docs: https://www.raspberrypi.com/documentation/computers/configuration-and-networking
"""


def test_scanner_detects_planted_secrets():
    """Proof the repository check above is not vacuously green."""
    findings = scan_text("planted.txt", PLANTED)
    kinds = {f.kind for f in findings}
    assert "private-key" in kinds
    assert "wifi-psk" in kinds
    assert "credential" in kinds
    assert len(findings) >= 4


def test_scanner_accepts_only_a_structurally_valid_ed25519_public_key_body():
    public_pem = (
        _pem_header("PUBLIC KEY") + "\n"
        "MCowBQYDK2VwAyEAG6kcg6Ss99DE76w3s0iO23hx9zeW7CJ1s1ZuHGqp3h0=\n"
        + "-" * 5 + "END PUBLIC KEY" + "-" * 5 + "\n"
    )
    arbitrary = "A" * 60

    assert scan_text("release.pub", public_pem) == []
    assert any(
        finding.kind == "high-entropy-token"
        for finding in scan_text("not-a-public-key.txt", arbitrary)
    )


@pytest.mark.parametrize(
    "kind,sample",
    [
        ("private-key", _pem_header("RSA PRIVATE KEY")),
        ("private-key", _pem_header("EC PRIVATE KEY")),
        ("wifi-psk", "psk=Sk8rBoi9Delta"),
        ("wifi-psk", "wifi_passphrase: correcthorsebattery"),
        ("credential", 'api_key = "sk_live_9182aeb27c4d"'),
        ("credential", "ADMIN_PASSWORD=Tr0ub4dor3xyz"),
    ],
)
def test_scanner_detects_each_secret_shape(kind, sample):
    findings = scan_text("sample.txt", sample)
    assert findings, f"scanner missed {kind}: {sample!r}"
    assert findings[0].kind == kind


@pytest.mark.parametrize(
    "sample",
    [
        'api_key = "liveEXAMPLEkey9182aeb27c4d"',
        "password: MyEXAMPLEpass99",
        "admin_password: notCHANGEMEreally123",
        "api_token = xxPLACEHOLDERxx9182aeb27",
    ],
)
def test_a_credential_containing_a_placeholder_word_is_still_a_credential(sample):
    """The fix for xK9$Qm2Lpz must not be paid for with a new hole.

    Switching _is_placeholder to fullmatch was right; widening the individual
    alternatives to substrings to compensate was not. It dismissed any value
    with EXAMPLE or PLACEHOLDER buried in it — which is what a credential
    looks like when someone edits a template and leaves the word behind.
    """
    findings = scan_text("sample.txt", sample)
    assert findings, f"scanner dismissed a credential as a placeholder: {sample!r}"


def test_scanner_ignores_placeholders_and_public_data():
    """False positives train people to ignore the scanner."""
    findings = scan_text("placeholders.txt", PLACEHOLDERS)
    assert not findings, "scanner flagged placeholders:\n" + "\n".join(
        str(f) for f in findings
    )


def test_scanner_ignores_public_provenance_paths_and_absorption_hashes():
    path_line = (
        "Run manifest/signing/layout/updater/storage/host/runtime boundaries "
        "and core/Fleet."
    )
    assert not scan_text("docs/plans/release.md", path_line)

    digest = "a" * 64
    inventory_line = (
        f'"src.py","src/rosy_control/src.py","{digest}","{digest}",'
        '"package-metadata","copied","provenance","tests"'
    )
    assert not scan_text(
        "docs/plans/2026-09-12-control-absorption-inventory.csv",
        inventory_line,
    )

    # The exception is scoped to the inventory's two digest columns.
    assert scan_text(
        "docs/plans/other.csv",
        f'"src.py","dst.py","{digest}","{digest}"',
    )


# --- a call is not a literal, but a literal inside one still is -------------


@pytest.mark.parametrize("line", [
    'const String secret = prefs.getString("secret", "");',
    'secret = created.json()["token"]',
    'api_token = response.headers.get("x-token")',
    'password = load()',
    'psk = self.setup_psk',
])
def test_reading_a_value_out_of_code_is_not_a_secret(line):
    """The bare-value branch stops at the first quote, so a captured value that
    ends in ( or [ is the head of an expression — never a literal.

    Firmware that reads its own key out of NVS was reported for years of this
    scanner's life, which trains everyone to ignore the report.
    """
    assert not scan_text("sample.ino", line), line


@pytest.mark.parametrize("line", [
    'password = decrypt_value("hunter2swordfish")',
    'secret = config.get("key", "site-passphrase-not-to-be-kept")',
    'api_key = os.environ.get("K", "sk_live_9182aeb27c4d")',
])
def test_a_secret_handed_to_a_call_is_still_a_secret(line):
    """The exclusion is about the shape of the value, not the shape of the line.

    Excusing every call would let a literal hide one bracket deep, which is
    exactly how a matcher goes quiet without anyone noticing.
    """
    assert scan_text("sample.py", line), line


def test_a_nested_call_is_reported_rather_than_reasoned_about():
    """A call inside a call does not match the call-head shape.

    The bare value runs to the first quote, so it reads as two openers rather
    than an identifier chain. Reporting is the right way to be wrong about a
    shape this scanner cannot cheaply parse — and the sample is assembled for
    the same reason the open-call ones are.
    """
    sample = _open_call("", "secret", "wrapper") + _open_call("", "", "inner").strip()

    assert scan_text("x.py", sample), sample


def test_a_lookup_key_is_not_mistaken_for_the_secret_it_looks_up():
    """A slot name is short, and often repeats the name being assigned."""
    assert not scan_text("x.py", 'secret = prefs.getString("secret")')
    assert not scan_text("x.py", 'api_token = response.headers.get("x-token")')
    assert scan_text("x.py", 'secret = prefs.getString("hunter2swordfish")')


def _open_call(indent: str, name: str, call: str) -> str:
    """An assignment whose call is left open at the end of the line.

    Assembled rather than written out: a literal here is itself an open-call
    assignment, so the scanner reports this file's own samples. The same
    reason `_pem_header` exists.
    """
    return f"{indent}{name} = {call}("


@pytest.mark.parametrize("line", [
    _open_call("", "ROSY_FLEET_API_TOKEN", "_decode"),
    _open_call("    ", "api_password", "base64.b64decode"),
    _open_call("        ", "access_token", "build_token"),
    # A bracket in a trailing comment is not the call closing. Parenthesised
    # ADR references are this repository's house comment style, so looking for
    # a bracket rather than counting one would hand the hole straight back.
    _open_call("", "ROSY_FLEET_API_TOKEN", "_decode") + "  # base64 (D-30)",
    _open_call("", "api_password", "b64decode") + "  # noqa: E501 (long)",
    _open_call("", "access_token", "build_token") + "  # cfg[map]",
])
def test_a_call_left_open_at_the_end_of_the_line_is_not_excused(line):
    """The arguments are on the next line, where a line-oriented scanner cannot
    read them.

    Excusing the head anyway made a formatter wrapping one assignment enough to
    hide a token — the exclusion fired with most confidence exactly where it
    had no evidence.
    """
    assert scan_text("sample.py", line), line


# --- a short function name is not a way past the gate ------------------------


@pytest.mark.parametrize("call", ["f", "wrap", "get", "b64", "load"])
def test_a_short_call_name_left_open_is_still_reported(call):
    """`_ASSIGNMENT`'s six-character floor is about literals, not calls.

    Applying it to call heads made a short function name the shortest way past
    this gate — under six characters the assignment reached no matcher at all.
    The sample is assembled rather than written, for the same reason the other
    open-call ones are: as a literal it is the shape under test.
    """
    assert scan_text("x.py", _open_call("", "api_token", call))


@pytest.mark.parametrize("name", ["password", "secret", "api_key"])
def test_a_secret_handed_to_a_short_call_is_reported(name):
    """The hole was not only the open call — a closed one hid a literal too."""
    line = _open_call("", name, "f") + '"hunter2swordfish")'

    assert scan_text("x.py", line), line


def test_a_short_subscript_holding_a_secret_is_reported():
    line = _open_call("", "secret", "data").replace("(", "[") + '"hunter2swordfish"]'

    assert scan_text("x.py", line), line


@pytest.mark.parametrize("line_parts", [
    ("token", "f", ")"),
    ("secret", "data", '"key"]'),
])
def test_a_short_call_that_closes_with_no_secret_is_still_excused(line_parts):
    """The new branch must not turn every short call into a report."""
    name, call, tail = line_parts
    opener = _open_call("", name, call)
    if tail.endswith("]"):
        opener = opener.replace("(", "[")

    assert not scan_text("x.py", opener + tail)


@pytest.mark.parametrize("line", [
    "bearer: Optional[str]",
    "password: Dict[str, str] = {}",
    "api_token: Sequence[bytes]",
])
def test_a_type_annotation_is_still_not_a_credential(line):
    """The call branch also matches `Optional[`; the type check runs first."""
    assert not scan_text("x.py", line), line

