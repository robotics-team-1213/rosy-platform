"""Real pinned RAUC/CMS behavior without global installs, service access or block writes."""
import json
import hashlib
import io
import subprocess
from urllib.error import URLError

import pytest
import os_rauc_fakes as fixtures

from os_rauc_fakes import rauc_tool, signer, make_bundle, run


def package_pin():
    data = b"trusted package"
    return data, dict(url="https://packages.test/rauc.deb?private=never-log", size_bytes=len(data),
                      sha256=hashlib.sha256(data).hexdigest())


def package_response(data):
    response = io.BytesIO(data)
    response.status = 200
    response.headers = {"Content-Length": str(len(data)), "Content-Type": "application/vnd.debian.binary-package"}
    return response


def test_package_acquisition_retries_only_until_exact_pinned_bytes(monkeypatch):
    trusted, pin = package_pin()
    outcomes = iter([b"truncated", URLError("private=never-log"), trusted])
    calls = []

    def open_response(url, timeout):
        calls.append((url, timeout))
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        response = package_response(result)
        original = response.read
        response.read = lambda size: original(size) if size == len(trusted) + 1 else pytest.fail("unbounded read")
        return response

    monkeypatch.setattr(fixtures, "urlopen", open_response)
    assert fixtures.download_package(pin) == trusted
    assert calls == [(pin["url"], 30)] * 3


@pytest.mark.parametrize("outcome", [b"short", b"wrong same size", b"oversized package body", URLError("private=never-log")])
def test_package_acquisition_fails_closed_with_attempt_diagnostics(monkeypatch, outcome):
    trusted, pin = package_pin()
    calls = []

    def open_response(url, timeout):
        calls.append(url)
        if isinstance(outcome, Exception):
            raise outcome
        return package_response(outcome)

    monkeypatch.setattr(fixtures, "urlopen", open_response)
    with pytest.raises(AssertionError) as failure:
        fixtures.download_package(pin)
    message = str(failure.value)
    assert len(calls) == 3
    assert all(f"attempt {number}:" in message for number in (1, 2, 3))
    assert "never-log" not in message
    if isinstance(outcome, Exception):
        assert "URLError" in message
    else:
        observed = outcome[:len(trusted) + 1]
        assert f"length={len(observed)}" in message and hashlib.sha256(observed).hexdigest() in message
        assert "status=200" in message and "content-length=" in message and "content-type=" in message


def test_isolated_rauc_accepts_codesigning_self_signed_leaf_and_exposes_full_manifest(tmp_path, rauc_tool):
    key, certificate = signer(tmp_path / "authority")
    bundle, config = make_bundle(tmp_path / "bundle", rauc_tool, key, certificate)
    raw = run([rauc_tool, "--conf", config, "info", "--output-format=json-2", bundle])
    value = json.loads(raw)
    assert value["update"]["compatible"] == "rosy-pinky-pro-ab-v2"
    assert value["bundle"]["format"] == "verity"
    assert value["meta"]["rosy"]["boot_abi"] == "2"
    assert {image["slot-class"] for image in value["images"]} == {"rootfs", "boot"}


def test_pinned_rauc_external_binary_cms_replacement_preserves_authenticated_payload(tmp_path, rauc_tool):
    prepare_key, prepare_cert = signer(tmp_path / 'preparer')
    operator_key, operator_cert = signer(tmp_path / 'operator')
    bundle, config = make_bundle(tmp_path / 'bundle', rauc_tool, prepare_key, prepare_cert)
    original = hashlib.sha256(bundle.read_bytes()).hexdigest()
    before = json.loads(run([rauc_tool, '--conf', config, 'info', '--output-format=json-2', bundle]))
    extracted, replacement, published = (tmp_path / name for name in ('extracted.cms', 'replacement.cms', 'final.raucb'))
    # Keep codesign purpose: the standalone command otherwise uses the S/MIME default.
    run([rauc_tool, '--conf', config, 'extract-signature', '--keyring', prepare_cert, bundle, extracted])
    manifest = run(['openssl', 'cms', '-verify', '-binary', '-purpose', 'any', '-CAfile', prepare_cert,
                    '-inform', 'DER', '-in', extracted])
    assert b'[bundle]' in manifest and b'format=verity' in manifest
    replacement.write_bytes(run(['openssl', 'cms', '-sign', '-binary', '-signer', operator_cert,
                                 '-inkey', operator_key, '-nodetach', '-outform', 'DER'], data=manifest))
    assert run(['openssl', 'cms', '-verify', '-binary', '-purpose', 'any', '-CAfile', operator_cert,
                '-inform', 'DER', '-in', replacement]) == manifest
    run([rauc_tool, '--conf', config, 'replace-signature', '--keyring', prepare_cert, '--signing-keyring', operator_cert,
         bundle, replacement, published])
    after = json.loads(run([rauc_tool, '--conf', config, '--keyring', operator_cert,
                            'info', '--output-format=json-2', published]))
    for key in ('update', 'bundle', 'images', 'meta'):
        assert after[key] == before[key]
    rejected = subprocess.run([str(rauc_tool), '--conf', str(config), 'info', str(published)],
                              capture_output=True, check=False, timeout=60)
    assert rejected.returncode != 0
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == original
