"""The destructive SYSTEM fixture must refuse every ordinary host before issuing a command."""
import importlib

import pytest


@pytest.mark.parametrize("slot", ["c", None, True])
def test_card_fixture_rejects_invalid_initial_slot_before_guest_commands(tmp_path, monkeypatch, slot):
    m = importlib.import_module("os_system_card")
    monkeypatch.setattr(m, "_guest", lambda: pytest.fail("invalid slot reached guest commands"))
    with pytest.raises(ValueError, match="initial slot"):
        m.prepare_card(tmp_path / "card", initial_slot=slot)


def test_card_fixture_refuses_without_guest_marker_before_block_access(tmp_path, monkeypatch):
    m = importlib.import_module("os_system_card")
    monkeypatch.delenv("ROSY_OS_GUEST", raising=False)
    monkeypatch.setattr(m, "run", lambda *a, **k: pytest.fail("unbound fixture accessed a block device"))
    with pytest.raises(ValueError, match="guest"):
        m.prepare_card(tmp_path / "card")
