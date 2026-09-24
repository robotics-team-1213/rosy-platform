"""Signature and checksum contracts for release artifacts (WP-1).

Every key in this module is generated per-test into a temporary directory.
No key material is committed, and the trusted release key is a separate
artifact that only ever exists in the signing environment and on devices —
see docs/deployment/release-signing-key.md.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

import pytest
from signing import (  # via test/conftest.py
    CHECKSUM_FILENAME,
    SIGNATURE_FILENAME,
    SigningToolMissing,
    build_sha256sums,
    find_unlisted_files,
    parse_sha256sums,
    sha256_file,
    sign_checksums,
    verify_checksums,
    verify_release_files,
    verify_signature,
)

ROOT = Path(__file__).resolve().parents[1]


def test_openssl_is_available():
    """The signature contract needs OpenSSL 3; its absence is a failure.

    This used to be a module-level skipif, directly under a comment saying a
    silent skip would report a green signature check that never ran. It did
    exactly that. Now the whole module fails on a runner without openssl,
    which is the honest outcome for a stated requirement.
    """
    assert shutil.which("openssl") is not None, (
        "openssl is required by the release signing contract; "
        "install it rather than skipping these tests"
    )


def _generate_key(directory: Path, name: str = "test") -> tuple[Path, Path]:
    """Create a throwaway Ed25519 keypair. Test-only, never a release key."""
    private = directory / f"{name}-signing-test.key"
    public = directory / f"{name}-signing-test.pub.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True, capture_output=True,
    )
    return private, public


@pytest.fixture
def release(tmp_path: Path) -> Path:
    """A small signed release directory."""
    root = tmp_path / "release"
    (root / "images").mkdir(parents=True)
    (root / "images" / "rosy-core.oci.tar").write_bytes(b"core image payload")
    (root / "images" / "rosy-io.oci.tar").write_bytes(b"io image payload")
    (root / "manifest.json").write_text('{"release_id": "2026.09.01-001"}', encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def keys(tmp_path_factory) -> tuple[Path, Path]:
    """One throwaway keypair for the whole module.

    Module-scoped because every openssl invocation is a process spawn, and
    the tests only ever read these keys. Tests that need a *second*, distinct
    key call ``_generate_key`` themselves.
    """
    return _generate_key(tmp_path_factory.mktemp("keys"))


def _sign_release(root: Path, private: Path) -> None:
    relative = [
        p.relative_to(root).as_posix()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name not in {CHECKSUM_FILENAME, SIGNATURE_FILENAME}
    ]
    sums = build_sha256sums(root, relative)
    (root / CHECKSUM_FILENAME).write_bytes(sums)
    (root / SIGNATURE_FILENAME).write_text(sign_checksums(sums, private), encoding="ascii")


# --- checksum list construction ------------------------------------------


def test_checksum_list_is_in_ascending_path_order(release):
    sums = build_sha256sums(
        release, ["manifest.json", "images/rosy-io.oci.tar", "images/rosy-core.oci.tar"]
    )
    paths = [line.split("  ", 1)[1] for line in sums.decode().splitlines()]
    assert paths == sorted(paths)
    assert paths == ["images/rosy-core.oci.tar", "images/rosy-io.oci.tar", "manifest.json"]


def test_checksum_list_uses_lf_regardless_of_build_host(release):
    sums = build_sha256sums(release, ["manifest.json"])
    assert b"\r\n" not in sums
    assert sums.endswith(b"\n")


def test_checksum_list_records_real_digests(release):
    sums = build_sha256sums(release, ["manifest.json"])
    digest = sums.decode().split("  ", 1)[0]
    assert digest == sha256_file(release / "manifest.json")


def test_round_trip_through_the_parser(release):
    sums = build_sha256sums(release, ["manifest.json", "images/rosy-core.oci.tar"])
    entries, rejections = parse_sha256sums(sums)
    assert rejections == []
    assert set(entries) == {"manifest.json", "images/rosy-core.oci.tar"}


# --- checksum list parsing ------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        b"not a checksum line\n",
        b"deadbeef  short-digest\n",
        b"a" * 64 + b" single-space-separator\n",
        b"A" * 64 + b"  uppercase-digest\n",
    ],
)
def test_malformed_checksum_line_is_rejected(line):
    _, rejections = parse_sha256sums(line)
    assert any(r.code == "SHA256SUMS_MALFORMED" for r in rejections)


def test_unordered_checksum_list_is_rejected():
    """Ascending order is part of the format, so a reordered list is tampering."""
    sums = (f"{'a' * 64}  zebra.txt\n{'b' * 64}  alpha.txt\n").encode()
    _, rejections = parse_sha256sums(sums)
    assert any(r.code == "SHA256SUMS_UNORDERED" for r in rejections)


def test_duplicate_checksum_entry_is_rejected():
    sums = (f"{'a' * 64}  same.txt\n{'b' * 64}  same.txt\n").encode()
    _, rejections = parse_sha256sums(sums)
    assert any(r.code == "SHA256SUMS_DUPLICATE" for r in rejections)


def test_empty_checksum_list_is_rejected():
    _, rejections = parse_sha256sums(b"")
    assert any(r.code == "SHA256SUMS_EMPTY" for r in rejections)


# --- signing and verification --------------------------------------------


def test_a_correctly_signed_release_verifies(release, keys):
    private, public = keys
    _sign_release(release, private)
    assert verify_release_files(release, public) == []


def test_signature_is_raw_ed25519_stored_as_base64(release, keys):
    private, _ = keys
    sums = build_sha256sums(release, ["manifest.json"])
    encoded = sign_checksums(sums, private)
    raw = base64.b64decode(encoded, validate=True)
    assert len(raw) == 64, "Ed25519 signatures are 64 bytes (RFC 8032)"


def test_signature_covers_the_exact_bytes(release, keys):
    """A single trailing newline difference must invalidate the signature."""
    private, public = keys
    sums = build_sha256sums(release, ["manifest.json"])
    encoded = sign_checksums(sums, private)
    assert verify_signature(sums, encoded, public) == []
    assert verify_signature(sums + b"\n", encoded, public)


def test_modified_checksum_list_is_rejected(release, keys):
    private, public = keys
    _sign_release(release, private)
    sums_path = release / CHECKSUM_FILENAME
    sums_path.write_bytes(sums_path.read_bytes().replace(b"manifest.json", b"manifest.jsoN"))

    rejections = verify_release_files(release, public)
    assert [r.code for r in rejections] == ["SIGNATURE_INVALID"]


def test_unsigned_release_is_rejected(release, keys):
    _, public = keys
    _sign_release(release, keys[0])
    (release / SIGNATURE_FILENAME).unlink()
    rejections = verify_release_files(release, public)
    assert [r.code for r in rejections] == ["SIGNATURE_MISSING"]


def test_release_without_a_checksum_list_is_rejected(release, keys):
    _, public = keys
    rejections = verify_release_files(release, public)
    assert [r.code for r in rejections] == ["SHA256SUMS_MISSING"]


def test_release_signed_by_the_wrong_key_is_rejected(release, tmp_path):
    """A valid signature from an untrusted key is still a rejection."""
    attacker_private, _ = _generate_key(tmp_path, "attacker")
    _, trusted_public = _generate_key(tmp_path, "trusted")

    _sign_release(release, attacker_private)

    rejections = verify_release_files(release, trusted_public)
    assert [r.code for r in rejections] == ["SIGNATURE_INVALID"]


def test_missing_trusted_key_is_distinguished_from_a_bad_signature(release, keys, tmp_path):
    private, _ = keys
    _sign_release(release, private)
    rejections = verify_release_files(release, tmp_path / "absent.pem")
    assert [r.code for r in rejections] == ["SIGNATURE_KEY_UNREADABLE"]


@pytest.mark.parametrize("garbage", ["not base64!!", "", "   \n  "])
def test_malformed_signature_is_rejected(release, keys, garbage):
    _, public = keys
    sums = build_sha256sums(release, ["manifest.json"])
    rejections = verify_signature(sums, garbage, public)
    assert rejections
    assert rejections[0].code in {"SIGNATURE_MALFORMED", "SIGNATURE_MISSING"}


def test_signature_of_the_wrong_length_is_rejected(release, keys):
    _, public = keys
    sums = build_sha256sums(release, ["manifest.json"])
    short = base64.b64encode(b"\x00" * 32).decode("ascii")
    rejections = verify_signature(sums, short, public)
    assert [r.code for r in rejections] == ["SIGNATURE_MALFORMED"]


# --- payload integrity ----------------------------------------------------


def test_corrupted_payload_is_rejected(release, keys):
    private, public = keys
    _sign_release(release, private)
    (release / "images" / "rosy-core.oci.tar").write_bytes(b"tampered payload")

    rejections = verify_release_files(release, public)
    assert [r.code for r in rejections] == ["CHECKSUM_MISMATCH"]
    assert rejections[0].field == "images/rosy-core.oci.tar"


def test_missing_payload_is_rejected(release, keys):
    private, public = keys
    _sign_release(release, private)
    (release / "images" / "rosy-io.oci.tar").unlink()

    rejections = verify_release_files(release, public)
    assert [r.code for r in rejections] == ["CHECKSUM_FILE_MISSING"]


def test_extra_unlisted_file_is_rejected(release, keys):
    """A file no checksum covers is covered by no signature either."""
    private, public = keys
    _sign_release(release, private)
    (release / "images" / "extra-payload.sh").write_bytes(b"#!/bin/sh\necho surprise\n")

    rejections = verify_release_files(release, public)
    assert [r.code for r in rejections] == ["CHECKSUM_UNLISTED_FILE"]
    assert rejections[0].field == "images/extra-payload.sh"


def test_the_checksum_and_signature_files_are_not_themselves_unlisted(release, keys):
    private, _ = keys
    _sign_release(release, private)
    entries, _ = parse_sha256sums((release / CHECKSUM_FILENAME).read_bytes())
    assert find_unlisted_files(release, entries) == []


def test_verify_checksums_reports_each_bad_file(release, keys):
    private, _ = keys
    _sign_release(release, private)
    entries, _ = parse_sha256sums((release / CHECKSUM_FILENAME).read_bytes())
    (release / "images" / "rosy-core.oci.tar").write_bytes(b"x")
    (release / "images" / "rosy-io.oci.tar").write_bytes(b"y")

    rejections = verify_checksums(release, entries)
    assert {r.field for r in rejections} == {
        "images/rosy-core.oci.tar",
        "images/rosy-io.oci.tar",
    }


# --- verification order ---------------------------------------------------


def test_payload_is_not_hashed_against_an_untrusted_checksum_list(release, tmp_path):
    """The attack this ordering exists to stop.

    Rewrite a payload, then rewrite SHA256SUMS to match it. If checksums were
    verified before the signature over the list, every file would agree and
    the release would look intact. Only the signature catches it, so only the
    signature's verdict may be reported.
    """
    trusted_private, trusted_public = _generate_key(tmp_path, "trusted")
    _sign_release(release, trusted_private)

    (release / "images" / "rosy-core.oci.tar").write_bytes(b"attacker payload")
    relative = [
        p.relative_to(release).as_posix()
        for p in sorted(release.rglob("*"))
        if p.is_file() and p.name not in {CHECKSUM_FILENAME, SIGNATURE_FILENAME}
    ]
    (release / CHECKSUM_FILENAME).write_bytes(build_sha256sums(release, relative))

    rejections = verify_release_files(release, trusted_public)
    assert [r.code for r in rejections] == ["SIGNATURE_INVALID"], (
        "a consistent but unsigned checksum list must not produce checksum-OK results"
    )


# --- no key material ships ------------------------------------------------


def test_only_public_release_key_pems_are_tracked_in_the_repository():
    """Key-shaped tracked files are public release anchors, never private keys."""
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"], capture_output=True, check=True
    )
    tracked = result.stdout.decode("utf-8").splitlines()
    suspicious = []
    for name in tracked:
        path = Path(name)
        key_shaped = (
            path.suffix in {".key", ".pem", ".p12", ".pfx"}
            or path.name in {"id_rsa", "id_ed25519", "id_ecdsa"}
        )
        if not key_shaped:
            continue
        if path.parent.as_posix() == "deploy/release/public-keys" and path.suffix == ".pem":
            content = (ROOT / path).read_text(encoding="utf-8")
            if "BEGIN PUBLIC KEY" in content and "PRIVATE KEY" not in content:
                continue
        suspicious.append(name)
    assert not suspicious, f"key-shaped files are tracked: {suspicious}"


def test_the_secret_scanner_recognises_an_ed25519_private_key(tmp_path):
    """The scanner must catch the exact artifact this module never commits."""
    from secret_scan import scan_text

    private, _ = _generate_key(tmp_path)
    findings = scan_text("leaked.key", private.read_text(encoding="utf-8"))
    assert any(f.kind == "private-key" for f in findings)


def test_a_missing_verifier_raises_rather_than_rejecting(monkeypatch, release, keys):
    """An absent verifier is not a bad signature and must not read as one."""
    import signing

    _private, public = keys
    monkeypatch.setattr(signing.shutil, "which", lambda _name: None)
    monkeypatch.setattr(signing, "_WINDOWS_OPENSSL_DIRS", ())

    # A well-formed 64-byte signature, so the call reaches openssl rather than
    # stopping at the length check.
    well_formed = base64.b64encode(bytes(64)).decode("ascii")

    with pytest.raises(SigningToolMissing):
        verify_signature(b"anything", well_formed, public)


# --- every rejection code this module can emit is exercised ---------------


def test_every_signing_rejection_code_is_asserted_somewhere():
    """The guardrail that caught the manifest gaps, applied to its sibling.

    Three hardenings shipped here with no assertions at all — the codes
    existed, the branches were unreachable from the suite, and the file could
    have been reverted wholesale without a single test noticing.
    """
    import re as _re

    source = (ROOT / "deploy" / "release" / "signing.py").read_text(encoding="utf-8")
    emitted = set(_re.findall(r'Rejection\(\s*\n?\s*"([A-Z0-9_]+)"', source))
    assert emitted, "no rejection codes found; the pattern needs updating"

    tests = Path(__file__).read_text(encoding="utf-8")
    unasserted = sorted(code for code in emitted if code not in tests)
    assert not unasserted, f"rejection codes with no test: {unasserted}"


@pytest.mark.parametrize(
    "path",
    ["/etc/systemd/system/evil.service", "../../etc/shadow", "images/../../../root/.ssh/id_ed25519"],
)
def test_a_checksum_list_path_that_leaves_the_release_is_rejected(path):
    """The manifest refuses these; the checksum list must apply the same rule.

    verify_checksums joins these onto the release root, so an unchecked path
    hashes a file outside it.
    """
    sums = (f"{'a' * 64}  {path}\n").encode()
    _, rejections = parse_sha256sums(sums)
    assert any(r.code == "SHA256SUMS_PATH_UNSAFE" for r in rejections)


def test_a_symlink_in_a_release_is_rejected(release, keys):
    """is_file() follows symlinks, so a dangling one vanished from the check."""
    import os

    if os.name != "posix":
        pytest.skip("symlink creation needs privilege on Windows; CI is Linux")

    private, public = keys
    _sign_release(release, private)
    os.symlink(release / "does-not-exist", release / "images" / "dangling")

    rejections = verify_release_files(release, public)
    assert [r.code for r in rejections] == ["CHECKSUM_SYMLINK"]


def test_a_non_utf8_signature_file_is_rejected(release, keys):
    """Not valid text is certainly not valid base64 — a rejection, not a crash."""
    private, public = keys
    _sign_release(release, private)
    (release / SIGNATURE_FILENAME).write_bytes(b"\xff\xfe\x00binary")

    rejections = verify_release_files(release, public)
    assert [r.code for r in rejections] == ["SIGNATURE_MALFORMED"]


def test_openssl_falls_back_to_git_for_windows_when_path_has_none(monkeypatch, tmp_path):
    # 2026-09-24: the card writer's PowerShell PATH had no openssl, pytest's did.
    import signing

    folder = tmp_path / "Git" / "usr" / "bin"
    folder.mkdir(parents=True)
    (folder / "openssl.exe").write_bytes(b"")
    monkeypatch.setattr(signing.shutil, "which", lambda name: None)
    monkeypatch.setattr(signing.os, "name", "nt")
    monkeypatch.setattr(signing, "_WINDOWS_OPENSSL_DIRS", (str(tmp_path / "missing"), str(folder)))

    assert signing._openssl() == str(folder / "openssl.exe")

    monkeypatch.setattr(signing, "_WINDOWS_OPENSSL_DIRS", (str(tmp_path / "missing"),))
    with pytest.raises(signing.SigningToolMissing):
        signing._openssl()
