"""D-423 §3.4: signed model manifests; unsigned bundles refused unless a dev flag says otherwise.

The robot verifies with openssl (as release verification does); the PC signs with
the release signing module, deploy/robot/pinky_pro/release/signing.py."""
import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from control.sensing.perception.learned.manifest import ManifestError
from control.sensing.perception.learned.signature import (
    SIGNATURE_NAME, TRUSTED_KEYS, SignatureError, checked_opener, verify_manifest_signature)

REPO = Path(__file__).resolve().parents[4]


def _openssl():
    from control.sensing.perception.learned.signature import openssl_path
    try:
        return openssl_path()
    except SignatureError:
        pytest.skip("openssl not available")


def _release_signing():
    spec = importlib.util.spec_from_file_location(
        "release_signing", REPO / "deploy" / "robot" / "pinky_pro" / "release" / "signing.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("release_signing", module)  # dataclasses resolve their module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def keys(tmp_path):
    openssl = _openssl()
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    pairs = {}
    for name in ("rosy-release-test", "stranger"):
        private = tmp_path / f"{name}.key"
        subprocess.run([openssl, "genpkey", "-algorithm", "ed25519", "-out", str(private)],
                       check=True, capture_output=True)
        public = (trusted if name != "stranger" else tmp_path) / f"{name}.pem"
        subprocess.run([openssl, "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                       check=True, capture_output=True)
        pairs[name] = private
    return trusted, pairs


def model(tmp_path, name="m"):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "model_manifest.json").write_text(json.dumps({"model_revision": "r1"}), encoding="utf-8")
    return folder


def sign(folder, private):
    signature = _release_signing().sign_checksums((folder / "model_manifest.json").read_bytes(), private)
    (folder / SIGNATURE_NAME).write_text(signature, encoding="ascii")


def test_trusted_key_location_is_the_release_one():
    assert TRUSTED_KEYS == "/etc/rosy/trusted-release-keys"
    assert SIGNATURE_NAME == "model_manifest.json.sig"


def test_release_signed_manifest_verifies_and_names_the_key(tmp_path, keys):
    trusted, pairs = keys
    folder = model(tmp_path)
    sign(folder, pairs["rosy-release-test"])
    assert verify_manifest_signature(folder, trusted) == "rosy-release-test"


@pytest.mark.parametrize("damage", ["unsigned", "stranger", "tampered", "garbage", "short"])
def test_anything_else_is_refused(tmp_path, keys, damage):
    trusted, pairs = keys
    folder = model(tmp_path)
    if damage != "unsigned":
        sign(folder, pairs["stranger" if damage == "stranger" else "rosy-release-test"])
    if damage == "tampered":
        (folder / "model_manifest.json").write_text(json.dumps({"model_revision": "r2"}), encoding="utf-8")
    elif damage == "garbage":
        (folder / SIGNATURE_NAME).write_text("not base64 !!", encoding="ascii")
    elif damage == "short":
        (folder / SIGNATURE_NAME).write_text(base64.b64encode(b"x" * 10).decode(), encoding="ascii")
    with pytest.raises(SignatureError) as error:
        verify_manifest_signature(folder, trusted)
    assert isinstance(error.value, ManifestError)  # ModelSlot keeps the previous model


def test_no_trusted_keys_refuses_even_a_signed_manifest(tmp_path, keys):
    _, pairs = keys
    folder = model(tmp_path)
    sign(folder, pairs["rosy-release-test"])
    empty = tmp_path / "none"
    empty.mkdir()
    with pytest.raises(SignatureError, match="trusted"):
        verify_manifest_signature(folder, empty)


def test_checked_opener_refuses_unsigned_by_default_and_the_dev_flag_admits_it(tmp_path):
    folder = model(tmp_path)
    opened = []
    strict = checked_opener(opened.append, allow_unsigned=False, keys_dir=tmp_path)
    with pytest.raises(SignatureError, match="unsigned"):
        strict(folder)
    assert opened == []
    checked_opener(opened.append, allow_unsigned=True, keys_dir=tmp_path)(folder)
    assert opened == [folder]


def test_a_present_but_bad_signature_is_refused_even_with_the_dev_flag(tmp_path, keys):
    trusted, pairs = keys
    folder = model(tmp_path)
    sign(folder, pairs["stranger"])
    with pytest.raises(SignatureError):
        checked_opener(lambda f: f, allow_unsigned=True, keys_dir=trusted)(folder)
