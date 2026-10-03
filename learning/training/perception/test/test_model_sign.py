"""D-423 §3.4: sign_model.py signs a model folder with the release signing module."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
for _p in (ROOT / "learning" / "training" / "perception" / "model", ROOT / "middleware" / "perception"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import deliver  # noqa: E402
import sign_model  # noqa: E402
from control.sensing.perception.learned.signature import (  # noqa: E402
    SIGNATURE_NAME, SignatureError, openssl_path, verify_manifest_signature)


@pytest.fixture
def keypair(tmp_path):
    try:
        openssl = openssl_path()
    except SignatureError:
        pytest.skip("openssl not available")
    private, trusted = tmp_path / "k.key", tmp_path / "trusted"
    trusted.mkdir()
    subprocess.run([openssl, "genpkey", "-algorithm", "ed25519", "-out", str(private)], check=True,
                   capture_output=True)
    subprocess.run([openssl, "pkey", "-in", str(private), "-pubout", "-out", str(trusted / "rosy-k.pem")],
                   check=True, capture_output=True)
    return private, trusted


def test_sign_then_robot_verifies(tmp_path, keypair):
    private, trusted = keypair
    folder = tmp_path / "m"
    folder.mkdir()
    (folder / "model_manifest.json").write_text(json.dumps({"model_revision": "r"}), encoding="utf-8")
    assert sign_model.main([str(folder), "--key", str(private), "--check", str(trusted)]) == 0
    assert verify_manifest_signature(folder, trusted) == "rosy-k"


def test_sign_refuses_a_folder_without_a_manifest(tmp_path, keypair):
    private, _ = keypair
    assert sign_model.main([str(tmp_path), "--key", str(private)]) == 2


def test_push_carries_the_signature_file(tmp_path):
    from test_model_deliver import SSH, FakeRunner, _model
    rev = _model(tmp_path, "pass")
    (tmp_path / rev / SIGNATURE_NAME).write_text("c2ln", encoding="ascii")
    runner = FakeRunner()
    assert deliver.main(["push", "robot", rev, "--models", str(tmp_path), *SSH], runner=runner) == 0
    sig_sha = hashlib.sha256(b"c2ln").hexdigest()
    assert f"{sig_sha}  " in runner.calls[-1][-1] and SIGNATURE_NAME in runner.calls[-1][-1]
