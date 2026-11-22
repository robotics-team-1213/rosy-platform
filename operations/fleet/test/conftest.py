"""colcon install 없이 pytest 를 돌린다 (Windows/CI).

`fleet` 은 `core_common.protocol.schemas` 를 import 한다(D-18, D-126). 두 패키지 모두
소스 트리에서 바로 찾도록 sys.path 를 잡는다 — 루트 `test/conftest.py` 가
`deploy/robot/pinky_pro/release` 에 하는 것과 같은 방식이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = (Path(__file__).resolve().parents[3] / "src")

# Each entry is the *outer* ROS-package dir, so the inner Python package
# (which owns __init__.py) resolves: fleet, core_common (prod, D-126 S3),
# core_features (cross-checks only: test_geometry.py follow_goal, D-60; test_trip_runner.py CORE's
# junction manoeuvre states).
for path in (
    SRC.parent / "operations" / "fleet",
    SRC.parent / "operations" / "account",
    SRC.parent / "operations" / "decision" / "src",
    SRC.parent / "operations" / "world" / "src",
    SRC.parent / 'operations' / 'site_execution' / "src",
    SRC.parent / "contracts" / "foundation",
    SRC.parent / "middleware" / "core" / "services",
    # Cell app tests import this production dependency before test_cell_compiler.
    SRC.parent / "operations" / "processes" / "palletizing" / "src",
):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)

# Browser tests here import test/browser_harness.py (opt-in flag, Chromium-safe ports).
_HARNESS = str(Path(__file__).resolve().parents[3] / "test")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)

# Capture method/status/test identities only; credentials and request bodies never leave the test.
import hmac
import os

import pytest
from rosy_account import site_users as _site_users

if os.environ.get('ROSY_CAPTURE_FLEET_APP_CONTRACTS') == '1':
    sys.path.append(str(SRC.parent / 'applications/fleet/test'))
    from backend_evidence import fleet_contract_probe, pytest_runtest_logreport, pytest_terminal_summary

_REAL_SCRYPT = _site_users._scrypt
_REAL_HASHES: dict[str, str] = {}
_REAL_SCRYPT_TESTS = frozenset({
    "test_hash_format_round_trips_with_the_adr_parameters",
    "test_hash_password_cli_reads_stdin",
    "test_loader_accepts_token_only_login_only_and_both",
    "test_loader_rejects_service_login_duplicate_login_bad_hash_and_missing_credential",
    "test_login_sets_a_strict_http_only_cookie_and_session_reports_it",
    "test_password_change_replaces_cookie_revokes_other_sessions_and_survives_restart",
})


def _fast_scrypt_kdf(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    """Fast test KDF keeping scrypt$n$r$p$salt$digest headers valid for _parse_password_hash."""
    return hmac.new(salt, f"{n}:{r}:{p}:{password}".encode("utf-8"), "sha256").digest()


def pytest_configure(config):
    _site_users._scrypt = _fast_scrypt_kdf


def pytest_unconfigure(config):
    _site_users._scrypt = _REAL_SCRYPT


@pytest.fixture(autouse=True)
def _scrypt_mode(request, monkeypatch):
    """Use real scrypt only for the contract tests in _REAL_SCRYPT_TESTS."""
    if getattr(request.node, "originalname", request.node.name) not in _REAL_SCRYPT_TESTS:
        return
    monkeypatch.setattr(_site_users, "_scrypt", _REAL_SCRYPT)
    mod = request.module
    if hasattr(mod, "TYPED") and hasattr(mod, "HASH"):
        if mod.TYPED not in _REAL_HASHES:
            _REAL_HASHES[mod.TYPED] = _site_users.hash_password(mod.TYPED)
        monkeypatch.setattr(mod, "HASH", _REAL_HASHES[mod.TYPED])
    if hasattr(mod, "BOOTSTRAP_PASSWORD_HASH"):
        if "alice" not in _REAL_HASHES:
            _REAL_HASHES["alice"] = _site_users.hash_password("alice")
        monkeypatch.setattr(mod, "BOOTSTRAP_PASSWORD_HASH", _REAL_HASHES["alice"])
