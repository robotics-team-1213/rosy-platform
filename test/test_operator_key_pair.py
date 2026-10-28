"""Check real OpenSSH key files, including encrypted keys and mismatched .pub siblings."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import shutil
import subprocess

import pytest

SD = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/sd"
KEYGEN = shutil.which("ssh-keygen")


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(SD))
    spec = importlib.util.spec_from_file_location("operator_key_verifier", SD / "verify-operator-key.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def make_key(tmp_path):
    if KEYGEN is None:
        pytest.fail("OpenSSH key generation is required to validate real operator keys")
    def create(name="operator", key_type="ed25519", passphrase="", cipher=None):
        private = tmp_path / name
        command = [KEYGEN, "-q", "-t", key_type, "-N", passphrase, "-f", str(private)]
        if cipher:
            command += ["-Z", cipher]
        subprocess.run(command,
                       capture_output=True, check=True, timeout=15)
        return private, private.with_name(private.name + ".pub")
    return create


@pytest.mark.parametrize("key_type", ["ed25519", "ecdsa"])
@pytest.mark.parametrize("passphrase", ["", "fixture-only-passphrase"])
def test_matching_real_keys_work_without_decryption(verifier, make_key, key_type, passphrase):
    private, public = make_key(key_type=key_type, passphrase=passphrase)
    before = private.read_bytes(), public.read_bytes()
    blob = base64.b64decode(public.read_text().split()[1])
    expected = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    assert verifier.key_pair(private, public) == expected
    assert (private.read_bytes(), public.read_bytes()) == before


@pytest.mark.parametrize("cipher", ["aes256-gcm@openssh.com", "chacha20-poly1305@openssh.com"])
def test_authenticated_encryption_keys_are_accepted(verifier, make_key, cipher):
    key_passphrase = secrets.token_urlsafe(16)
    private, public = make_key(passphrase=key_passphrase, cipher=cipher)
    assert verifier.key_pair(private, public).startswith("SHA256:")


@pytest.mark.parametrize("passphrase", ["", "fixture-only-passphrase"])
def test_mismatched_sibling_public_key_is_rejected(verifier, make_key, passphrase):
    private, public = make_key(passphrase=passphrase)
    _, other = make_key("other")
    public.write_bytes(other.read_bytes())
    before = private.read_bytes(), public.read_bytes()
    with pytest.raises(ValueError, match="do not match"):
        verifier.key_pair(private, public)
    assert (private.read_bytes(), public.read_bytes()) == before


@pytest.mark.parametrize("kind", ["invalid-base64", "truncated", "oversized", "not-openssh", "missing"])
def test_invalid_private_file_is_refused(verifier, make_key, kind):
    private, public = make_key()
    if kind == "missing":
        private.unlink()
    elif kind == "truncated":
        private.write_bytes(private.read_bytes()[:80])
    elif kind == "oversized":
        private.write_bytes(b"x" * 65537)
    elif kind == "not-openssh":
        private.write_bytes(b"not a private key")
    else:
        lines = private.read_bytes().splitlines()
        private.write_bytes(lines[0] + b"\n!!!\n" + lines[-1] + b"\n")
    with pytest.raises((ValueError, OSError)):
        verifier.key_pair(private, public)


def test_malformed_binary_lengths_are_refused(verifier, make_key):
    private, public = make_key()
    lines = private.read_bytes().splitlines()
    data = bytearray(base64.b64decode(b"".join(lines[1:-1])))
    data[15:19] = b"\xff\xff\xff\xff"
    private.write_bytes(lines[0] + b"\n" + base64.b64encode(data) + b"\n" + lines[-1] + b"\n")
    with pytest.raises(ValueError):
        verifier.key_pair(private, public)


def test_cli_returns_only_the_public_fingerprint(verifier, make_key, capsys):
    private, public = make_key()
    assert verifier.main(["--private-key", str(private), "--public-key", str(public)]) == 0
    result = capsys.readouterr()
    assert set(json.loads(result.out)) == {"fingerprint"}
    assert "PRIVATE KEY" not in result.out + result.err


def test_cli_does_not_echo_invalid_private_material(verifier, make_key, capsys):
    private, public = make_key()
    private.write_text("DO-NOT-PRINT-PRIVATE-MATERIAL")
    assert verifier.main(["--private-key", str(private), "--public-key", str(public)]) == 2
    result = capsys.readouterr()
    assert not result.out
    assert "DO-NOT-PRINT" not in result.err and "HOLD" in result.err
