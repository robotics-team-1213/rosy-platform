"""Contracts for the image pipeline's inputs and scripts (WP-6).

No image has been built. What can be checked without hardware is that the
pipeline refuses to run on assumptions nobody verified, that it refuses to
call an unbuilt image a release, and that the lock file names every input
design section 7.2 requires.

The point of the lock file is provenance: the same inputs must produce a
release you can describe. An entry left `null` or `verified: false` is an
input that is not pinned, and building on it produces an image whose
provenance cannot be stated — which is the one thing 7.2 asks for.
"""

from __future__ import annotations

import subprocess
import hashlib
import os
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "deploy" / "image"
LOCK = IMAGE_DIR / "inputs.lock.yaml"
SCRIPTS = (
    "build-image.sh",
    "fetch-base-image.sh",
    "verify-inputs.sh",
    "verify-artifacts.sh",
)


def _bash_is_usable() -> bool:
    """Probe once, but do not let one slow start silence the whole file.

    A single probe made this file nondeterministic: three identical runs gave
    43 passed, then 31 passed with 12 skipped, then a failure. Starting WSL
    here is not reliably fast (5.7s cold against 0.23s warm), so a probe that
    loses the race marked twelve gate tests "skipped" — which reads as a pass
    in the summary line and is how a suite stops being a gate.
    """
    for _ in range(3):
        try:
            probe = subprocess.run(
                ["bash", "-c", "true"], capture_output=True, check=False, timeout=60
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            return True
    return False


bash_only = pytest.mark.skipif(
    not _bash_is_usable(),
    reason="bash is required to exercise the pipeline scripts",
)


def _bash(
    args: list[str], cwd: Path, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """Run bash from the directory holding the script, with relative names.

    The bash on PATH here resolves neither a Windows drive path nor its MSYS
    form, so an absolute argument exits 127 and every one of these tests
    reports a script problem that is really a path problem. Relative names
    from an explicit cwd work in Git Bash and on Linux alike.
    """
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
        if os.name == "nt":
            forwarded = [item for item in process_env.get("WSLENV", "").split(":") if item]
            forwarded_names = {item.split("/")[0] for item in forwarded}
            forwarded.extend(name for name in env if name not in forwarded_names)
            process_env["WSLENV"] = ":".join(forwarded)
    return subprocess.run(
        ["bash", *args],
        cwd=str(cwd),
        env=process_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,  # the return code is the assertion
    )


@pytest.fixture(scope="module")
def lock() -> dict:
    return yaml.safe_load(LOCK.read_text(encoding="utf-8"))


# --- the lock names every input section 7.2 requires -----------------------


def test_the_lock_file_exists(lock):
    assert lock["schema_version"] == 1


def test_the_lock_names_pinky_pro_as_the_first_board(lock):
    board = lock["board"]
    assert board["name"] == "pinky_pro"
    assert board["host"] == "raspberry-pi-5"
    assert board["first_runtime"] == "core"


@pytest.mark.parametrize(
    "path",
    [
        ("image_tool", "commit"),
        ("base_image", "url"),
        ("base_image", "sha256"),
        ("base_image", "minimum_size_bytes"),
        ("os", "suite"),
        ("os", "architecture"),
        ("os", "apt_sources"),
        ("runtime", "model"),
        ("runtime", "container_runtime_required"),
        ("ros", "apt_repository"),
        ("ros", "apt_key_fingerprint"),
        ("rosy_packages", "required"),
        ("sources", "rosy_revision"),
    ],
)
def test_every_pinned_input_has_a_slot(lock, path):
    """Section 7.2's list, present even where the value is not yet known."""
    node = lock
    for key in path:
        assert key in node, f"the lock file has no slot for {'.'.join(path)}"
        node = node[key]


def test_the_lock_records_the_core_account_precondition(lock):
    """The Host Agent contract's precondition lives or dies in the image."""
    accounts = lock["accounts"]

    assert accounts["core_user"] == "rosy-core"
    assert accounts["io_user"] == "rosy-io"
    assert accounts["login_uid_must_differ"] is True
    assert accounts["core_uid"] != 1000, "uid 1000 is the Pi's login account"


def test_the_lock_preserves_build_provenance(lock):
    """Package repositories move; the same source can produce a different image."""
    provenance = lock["provenance"]

    assert provenance["record_installed_packages"] is True
    assert provenance["record_apt_repository_metadata"] is True


def test_the_unverified_assumptions_are_marked_as_such(lock):
    """These are exactly the ones the checklist says to settle first."""
    for section in ("image_tool", "base_image", "os", "ros"):
        assert "verified" in lock[section], f"{section} does not say whether it was verified"

    unverified = [name for name in ("image_tool", "base_image", "os", "ros")
                  if lock[name]["verified"] is False]
    assert unverified, (
        "every assumption is marked verified; if that is true, the acceptance "
        "checklist section 2 should be updated to match"
    )


def test_the_risky_assumptions_explain_themselves(lock):
    """A bare `verified: false` tells the next person nothing."""
    for section in ("image_tool", "base_image"):
        if lock[section]["verified"] is False:
            assert lock[section].get("note"), f"{section} is unverified with no explanation"


def _fetch_fixture(tmp_path: Path, content: bytes = b"ubuntu-image") -> Path:
    """Create a tiny pinned lock/cache pair for the real fetch script."""
    import shutil

    shutil.copy(IMAGE_DIR / "fetch-base-image.sh", tmp_path / "fetch-base-image.sh")
    fingerprint = "843938DF228D22F7B3742BC0D94AA3F0EFE21092"
    lock = {
        "base_image": {
            "url": "https://cdimage.ubuntu.com/releases/noble/release/ubuntu.img.xz",
            "sha256": hashlib.sha256(content).hexdigest(),
            "minimum_size_bytes": len(content),
            "checksum_url": "https://cdimage.ubuntu.com/releases/noble/release/SHA256SUMS",
            "checksum_signature_url": "https://cdimage.ubuntu.com/releases/noble/release/SHA256SUMS.gpg",
            "checksum_signing_key_fingerprint": fingerprint,
            "checksum_keyring": "ubuntu-image-signing.gpg",
        }
    }
    (tmp_path / "inputs.lock.yaml").write_text(
        yaml.safe_dump(lock), encoding="utf-8"
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "ubuntu.img.xz").write_bytes(content)
    (cache / "SHA256SUMS").write_text(
        f"{hashlib.sha256(content).hexdigest()} *ubuntu.img.xz\n",
        encoding="utf-8",
    )
    (cache / "SHA256SUMS.gpg").write_bytes(b"fixture-signature")
    (tmp_path / "ubuntu-image-signing.gpg").write_bytes(b"fixture-keyring")
    verifier = tmp_path / "fake-gpgv.sh"
    verifier.write_text(
        "#!/usr/bin/env bash\n"
        "[[ ${ROSY_FAKE_GPGV_FAIL:-0} == 0 ]] || exit 1\n"
        "printf '[GNUPG:] VALIDSIG %s 2026-09-22 0 4 0 1 10 00 %s\\n' "
        '"${ROSY_FAKE_FINGERPRINT}" "${ROSY_FAKE_FINGERPRINT}"\n',
        encoding="utf-8",
        newline="\n",
    )
    verifier.chmod(0o755)
    return cache


def _provenance_env(**overrides: str) -> dict[str, str]:
    values = {
        "ROSY_GPGV": "./fake-gpgv.sh",
        "ROSY_FAKE_FINGERPRINT": "843938DF228D22F7B3742BC0D94AA3F0EFE21092",
    }
    values.update(overrides)
    return values


def test_lock_pins_canonical_checksum_signature_and_image_signing_key(lock):
    base = lock["base_image"]

    assert base["checksum_url"].endswith("/24.04/release/SHA256SUMS")
    assert base["checksum_signature_url"].endswith("/24.04/release/SHA256SUMS.gpg")
    expected_fingerprint = "843938DF228D22F7B3742BC0D94AA3F0EFE21092"
    assert base["checksum_signing_key_fingerprint"] == expected_fingerprint
    assert base["checksum_keyring"] == "/usr/share/keyrings/ubuntu-archive-keyring.gpg"


def test_fetch_base_image_script_exists():
    assert (IMAGE_DIR / "fetch-base-image.sh").is_file()


def test_image_shell_entrypoints_are_tracked_as_executable():
    for script in IMAGE_DIR.glob("*.sh"):
        relative = script.relative_to(ROOT).as_posix()
        mode = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-s", "--", relative],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split(maxsplit=1)[0]
        assert mode == "100755", f"{relative} is tracked as {mode}"


@bash_only
def test_fetch_base_image_reuses_a_verified_offline_cache(tmp_path):
    _fetch_fixture(tmp_path)

    result = _bash([
        "fetch-base-image.sh", "--lock", "inputs.lock.yaml",
        "--cache-dir", "cache", "--offline",
    ], tmp_path, env=_provenance_env())

    assert result.returncode == 0, result.stderr
    assert "CACHE_VERIFIED" in result.stdout
    assert "PROVENANCE_VERIFIED" in result.stdout


@bash_only
def test_fetch_base_image_rejects_an_invalid_canonical_signature(tmp_path):
    _fetch_fixture(tmp_path)

    result = _bash([
        "fetch-base-image.sh", "--lock", "inputs.lock.yaml",
        "--cache-dir", "cache", "--offline",
    ], tmp_path, env=_provenance_env(ROSY_FAKE_GPGV_FAIL="1"))

    assert result.returncode != 0
    assert "signature" in result.stderr.lower()


@bash_only
def test_fetch_base_image_rejects_a_signature_from_the_wrong_fingerprint(tmp_path):
    _fetch_fixture(tmp_path)

    result = _bash([
        "fetch-base-image.sh", "--lock", "inputs.lock.yaml",
        "--cache-dir", "cache", "--offline",
    ], tmp_path, env=_provenance_env(ROSY_FAKE_FINGERPRINT="0" * 40))

    assert result.returncode != 0
    assert "fingerprint" in result.stderr.lower()


@bash_only
def test_fetch_base_image_rejects_a_signed_checksum_without_the_exact_image(tmp_path):
    cache = _fetch_fixture(tmp_path)
    (cache / "SHA256SUMS").write_text(
        f"{'0' * 64} *other.img.xz\n", encoding="utf-8"
    )

    result = _bash([
        "fetch-base-image.sh", "--lock", "inputs.lock.yaml",
        "--cache-dir", "cache", "--offline",
    ], tmp_path, env=_provenance_env())

    assert result.returncode != 0
    assert "signed checksum" in result.stderr.lower()


@bash_only
def test_fetch_base_image_rejects_checksum_mismatch(tmp_path):
    cache = _fetch_fixture(tmp_path)
    (cache / "ubuntu.img.xz").write_bytes(b"tampered-img")

    result = _bash([
        "fetch-base-image.sh", "--lock", "inputs.lock.yaml",
        "--cache-dir", "cache", "--offline",
    ], tmp_path, env=_provenance_env())

    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr.lower()


@bash_only
def test_fetch_base_image_rejects_latest_or_non_https_urls(tmp_path):
    _fetch_fixture(tmp_path)
    lock = yaml.safe_load((tmp_path / "inputs.lock.yaml").read_text(encoding="utf-8"))
    lock["base_image"]["url"] = "http://cdimage.ubuntu.com/releases/latest/ubuntu.img.xz"
    (tmp_path / "inputs.lock.yaml").write_text(yaml.safe_dump(lock), encoding="utf-8")

    result = _bash([
        "fetch-base-image.sh", "--lock", "inputs.lock.yaml",
        "--cache-dir", "cache", "--offline",
    ], tmp_path, env=_provenance_env())

    assert result.returncode != 0
    assert "pinned https" in result.stderr.lower()


@bash_only
def test_fetch_base_image_enforces_minimum_size(tmp_path):
    _fetch_fixture(tmp_path)
    lock = yaml.safe_load((tmp_path / "inputs.lock.yaml").read_text(encoding="utf-8"))
    lock["base_image"]["minimum_size_bytes"] = 1024
    (tmp_path / "inputs.lock.yaml").write_text(yaml.safe_dump(lock), encoding="utf-8")

    result = _bash([
        "fetch-base-image.sh", "--lock", "inputs.lock.yaml",
        "--cache-dir", "cache", "--offline",
    ], tmp_path, env=_provenance_env())

    assert result.returncode != 0
    assert "too small" in result.stderr.lower()


# --- the scripts refuse to proceed on unpinned inputs ---------------------


@bash_only
def test_verify_inputs_refuses_while_anything_is_unpinned():
    """The gate that stops a build producing an undescribable image."""
    result = _bash(["verify-inputs.sh", "inputs.lock.yaml"], IMAGE_DIR)

    assert result.returncode != 0, "the lock still has unpinned inputs; this must refuse"
    assert "unverified assumptions" in result.stderr or "unpinned inputs" in result.stderr


@bash_only
def test_verify_inputs_accepts_a_fully_pinned_lock(tmp_path):
    """And it must actually pass once the work is done, or it is just noise."""
    import shutil

    pinned = yaml.safe_load(LOCK.read_text(encoding="utf-8"))

    def settle(node):
        if isinstance(node, dict):
            return {
                key: (True if key == "verified" else "pinned" if value is None else settle(value))
                for key, value in node.items()
            }
        return node

    (tmp_path / "inputs.lock.yaml").write_text(yaml.safe_dump(settle(pinned)), encoding="utf-8")
    shutil.copy(IMAGE_DIR / "verify-inputs.sh", tmp_path / "verify-inputs.sh")

    result = _bash(["verify-inputs.sh", "inputs.lock.yaml"], tmp_path)

    assert result.returncode == 0, result.stderr


@bash_only
def test_verify_inputs_ignores_its_own_explanatory_comments():
    """The comments describe the markers; only settings may fail the gate."""
    result = _bash(["verify-inputs.sh", "inputs.lock.yaml"], IMAGE_DIR)

    reported = [line for line in result.stderr.splitlines() if ":" in line]
    assert reported, "the gate reported nothing"
    assert not any("#" in line for line in reported), (
        "a comment line was reported as an unpinned input"
    )


@bash_only
def test_the_build_script_does_not_pretend_to_have_built_anything(tmp_path):
    """No image exists. The script must say so rather than produce a directory."""
    result = _bash(
        ["build-image.sh", "--release-id", "2026.09.01-001", "--dist", "./_unused"], IMAGE_DIR
    )

    assert result.returncode != 0
    assert "not implemented" in result.stderr or "arm64" in result.stderr
    assert not (IMAGE_DIR / "_unused").exists(), "a failed build must leave nothing behind"


@bash_only
def test_the_build_script_refuses_a_malformed_release_id():
    result = _bash(["build-image.sh", "--release-id", "latest"], IMAGE_DIR)

    assert result.returncode != 0
    assert "YYYY.MM.DD-NNN" in result.stderr


def test_the_build_script_refuses_a_non_arm64_host():
    """Design 7.1: an x86 QEMU build is never the basis of a release image."""
    script = (IMAGE_DIR / "build-image.sh").read_text(encoding="utf-8")

    assert "aarch64" in script
    assert "uname -m" in script


def test_verify_artifacts_requires_the_image_tree_for_build_go():
    """Checking the distribution directory alone is not BUILD_GO."""
    script = (IMAGE_DIR / "verify-artifacts.sh").read_text(encoding="utf-8")

    assert "ROSY_IMAGE_MOUNT" in script
    tail = script.split("ROSY_IMAGE_MOUNT to the mounted root", 1)[1]
    assert "exit 1" in tail, "a skipped image inspection must not report BUILD_GO"


def test_verify_artifacts_checks_every_declared_artifact():
    """Section 7.4's list."""
    script = (IMAGE_DIR / "verify-artifacts.sh").read_text(encoding="utf-8")

    for artifact in ("manifest.json", "SHA256SUMS", "SHA256SUMS.sig",
                     "sbom.spdx.json", "release-notes.md", "img.xz", "bmap"):
        assert artifact in script, f"verify-artifacts does not check {artifact}"


# --- script hygiene, matching the rest of deploy/ -------------------------


@pytest.mark.parametrize("name", SCRIPTS + ("../robot/release-recover.sh",))
def test_scripts_are_lf_only(name):
    """CRLF is unsafe in a Pi shell.

    Compared as bytes rather than through an escaped string literal: the
    first version of this asserted on a literal backslash-r, so it passed
    against a CRLF file — which is the one failure a line-ending test exists
    to catch.
    """
    path = IMAGE_DIR / name
    assert bytes([13, 10]) not in path.read_bytes(), f"CRLF in {path.name}"


@bash_only
@pytest.mark.parametrize("name", SCRIPTS + ("../robot/release-recover.sh",))
def test_scripts_parse(name):
    result = _bash(["-n", name], IMAGE_DIR)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", SCRIPTS + ("../robot/release-recover.sh",))
def test_scripts_fail_fast(name):
    """set -euo pipefail, like the rest of the deployment kit."""
    text = (IMAGE_DIR / name).read_text(encoding="utf-8")
    assert "set -euo pipefail" in text


# --- the recovery gate ships and is wired ---------------------------------


def test_the_recovery_gate_unit_exists():
    unit = (ROOT / "deploy" / "robot" / "rosy-release-recover.service").read_text(encoding="utf-8")

    assert "Type=oneshot" in unit
    assert "Before=rosy-runtime.service" in unit


def test_the_runtime_requires_the_gate_rather_than_wanting_it():
    """With Wants=, a device held for recovery boots anyway."""
    unit = (ROOT / "deploy" / "robot" / "rosy-runtime.service").read_text(encoding="utf-8")

    assert "Requires=rosy-release-recover.service" in unit
    assert "After=rosy-release-recover.service" in unit
    assert "Wants=rosy-release-recover.service" not in unit


def test_the_gate_has_no_restart_or_swallowed_failure():
    """Either would convert a hold into a boot."""
    unit = (ROOT / "deploy" / "robot" / "rosy-release-recover.service").read_text(encoding="utf-8")
    script = (ROOT / "deploy" / "robot" / "release-recover.sh").read_text(encoding="utf-8")

    def directives(text: str) -> list[str]:
        return [
            line for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    assert not any(line.startswith("Restart=") for line in directives(unit))
    assert not any("|| true" in line for line in directives(script))
    assert "blocks_runtime" in script, "the gate must key on the hold, not on ok"


# --- the recovery gate actually gates ------------------------------------


def _bash_view(path: Path) -> str:
    """The path as the local bash sees it.

    The bash here is WSL, so the repository is /mnt/f/... and a Windows path
    means nothing to it. Asking bash itself avoids guessing.

    This used to return whatever `pwd` printed, with check=False and no
    validation. Starting WSL is not reliably fast on this host - a cold start
    measured 5.7s against a 0.23s warm one - so the call sometimes came back
    empty, and an empty answer became `ROSY_LAYOUT_ROOT=""`. The gate script
    then fell back to its production default, never saw the fabricated
    recovery-hold.json, exited 0, and `test_the_gate_blocks_a_held_device`
    reported that a held device was allowed to boot. A flaky probe was being
    read as a real verdict about the product.

    So: retry, and refuse to answer rather than answer emptily.
    """
    last = ""
    for attempt in range(3):
        result = subprocess.run(
            ["bash", "-c", "pwd"],
            cwd=str(path), capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, timeout=60,
        )
        answer = result.stdout.strip()
        if result.returncode == 0 and answer:
            return answer
        last = (result.stderr or "").strip() or f"exit {result.returncode}, empty stdout"
    raise RuntimeError(
        f"bash could not report a path for {path} after 3 attempts ({last}). "
        f"Refusing to continue: an empty path silently sends the script under "
        f"test to its production defaults and turns this into a false verdict."
    )


def _run_gate(tmp_path: Path) -> subprocess.CompletedProcess:
    """Run the real gate script against a temporary layout.

    Asserting that the source mentions blocks_runtime proved nothing: turning
    its exit into 0 left every test green. This runs it.

    The variables are assigned inside bash rather than passed through env=,
    because WSL does not inherit arbitrary Windows environment variables and
    the script would silently fall back to its production defaults.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    tools = _bash_view(ROOT / "deploy" / "release")
    layout = _bash_view(tmp_path)
    # The hold path calls systemctl to disable the runtime unit. The CI
    # container has no systemd — a stub on PATH keeps the test judging the
    # gate's decision (hold vs boot), not the systemd transport.
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(exist_ok=True)
    stub = stub_bin / "systemctl"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    stub_view = _bash_view(stub_bin)

    return subprocess.run(
        [
            "bash",
            "-c",
            (
                f'ROSY_RELEASE_TOOLS="{tools}" ROSY_LAYOUT_ROOT="{layout}" '
                f'ROSY_PYTHON=python3 PATH="{stub_view}:$PATH" ./release-recover.sh'
            ),
        ],
        cwd=str(ROOT / "deploy" / "robot"),
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


@bash_only
def test_the_gate_lets_a_fresh_device_boot(tmp_path):
    """A device out of the box has nothing to recover and must not be held."""
    result = _run_gate(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "NOT_INSTALLED" in result.stdout


@bash_only
def test_the_gate_blocks_a_held_device(tmp_path):
    """The whole point: a recovery hold must stop the runtime from starting."""
    import json

    layout_var = tmp_path / "var" / "lib" / "rosy"
    layout_var.mkdir(parents=True)
    (layout_var / "recovery-hold.json").write_text(
        json.dumps({"schema_version": 1, "release_id": "2026.09.05-002",
                    "detail": "the previous release also failed its health check"}),
        encoding="utf-8",
    )

    result = _run_gate(tmp_path)

    assert result.returncode != 0, "a held device must not be allowed to boot its runtime"
    assert "RECOVERY_HOLD" in result.stdout


@bash_only
def test_the_gate_reports_why_it_held(tmp_path):
    import json

    layout_var = tmp_path / "var" / "lib" / "rosy"
    layout_var.mkdir(parents=True)
    (layout_var / "recovery-hold.json").write_text(
        json.dumps({"schema_version": 1, "release_id": None,
                    "detail": "no usable activation record"}),
        encoding="utf-8",
    )

    result = _run_gate(tmp_path)

    assert "no usable activation record" in result.stdout
