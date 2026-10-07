"""D-477: the resolver must check the tailscale deb, never mark it verified blindly."""

import hashlib
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "deploy" / "robot" / "pinky_pro" / "image" / "resolve-build-lock.py"


def _resolver():
    spec = importlib.util.spec_from_file_location("resolve_build_lock", RESOLVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deb(tmp_path):
    deb = tmp_path / "tailscale.deb"
    deb.write_bytes(b"not really a deb")
    return deb, {"size": 16, "sha256": hashlib.sha256(b"not really a deb").hexdigest()}


def test_size_mismatch_refuses(tmp_path):
    deb, section = _deb(tmp_path)
    section["size"] = 17
    with pytest.raises(SystemExit, match="size mismatch"):
        _resolver().check_tailscale_deb(deb, section)


def test_sha256_mismatch_refuses(tmp_path):
    deb, section = _deb(tmp_path)
    section["sha256"] = "0" * 64
    with pytest.raises(SystemExit, match="sha256 mismatch"):
        _resolver().check_tailscale_deb(deb, section)


def test_tailscale_is_not_in_the_blind_verified_list():
    text = RESOLVER.read_text(encoding="utf-8")
    blind = text.split('for section in (', 1)[1].split(")", 1)[0]
    assert "tailscale" not in blind
    assert text.index('verify_tailscale(lock["tailscale"])') < text.index('lock["tailscale"]["verified"] = True')
