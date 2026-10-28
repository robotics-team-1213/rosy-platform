"""SYSTEM install helpers must refuse ordinary hosts before block or service access."""
import importlib

import pytest


def test_system_install_requires_owned_guest_before_any_command(monkeypatch):
    module = importlib.import_module("os_system_install")
    monkeypatch.delenv("ROSY_OS_GUEST", raising=False)
    monkeypatch.setattr(module, "run", lambda *a, **k: pytest.fail("host command before guest admission"))
    with pytest.raises(ValueError, match="owned guest"):
        module.admit("rosy-system-00000000-0000-4000-8000-000000000000")
