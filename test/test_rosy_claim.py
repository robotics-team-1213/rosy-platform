"""D-410 / D-387 decision 4 (interim): the /run/rosy-claim exclusive claim.

`mkdir /run/rosy-claim` is the atomic step; the winner writes claim.json. An
expired claim, or one from another boot, may be cleared by exactly one party
with a rename to /run/rosy-claim.stale.<rand>. Every test runs on a fake root.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy" / "robot" / "pinky_pro" / "native"
BOOT = "11111111-2222-3333-4444-555555555555"
T0 = dt.datetime(2026, 10, 1, 12, 0, 0, tzinfo=dt.timezone.utc)


def _load():
    spec = importlib.util.spec_from_file_location("rosy_claim", NATIVE / "rosy_claim.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["rosy_claim"] = module
    spec.loader.exec_module(module)
    return module


claim_mod = _load()


@pytest.fixture
def device(tmp_path):
    (tmp_path / "run").mkdir()
    boot = tmp_path / "proc/sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text(BOOT + "\n", encoding="utf-8")
    return tmp_path


def _claim_dir(device: Path) -> Path:
    return device / "run" / "rosy-claim"


def test_acquire_writes_the_contract_fields(device):
    claim = claim_mod.acquire(device, "rosy-auto-update", "update 2026.10.01-022", 1800, now=T0)

    on_disk = json.loads((_claim_dir(device) / "claim.json").read_text(encoding="utf-8"))
    assert on_disk == claim
    assert set(on_disk) == {"holder", "purpose", "acquired_at", "expires_at", "boot_id"}
    assert on_disk["holder"] == "rosy-auto-update"
    assert on_disk["acquired_at"] == "2026-10-01T12:00:00Z"
    assert on_disk["expires_at"] == "2026-10-01T12:30:00Z"
    assert on_disk["boot_id"] == BOOT


def test_a_live_claim_refuses_a_second_holder(device):
    claim_mod.acquire(device, "push-pc", "release push", 1800, now=T0)

    with pytest.raises(claim_mod.ClaimBusy) as caught:
        claim_mod.acquire(device, "rosy-auto-update", "update", 1800, now=T0 + dt.timedelta(minutes=29))

    assert caught.value.claim["holder"] == "push-pc"
    assert json.loads((_claim_dir(device) / "claim.json").read_text(encoding="utf-8"))["holder"] == "push-pc"


def test_an_expired_claim_is_moved_aside_and_taken_over(device):
    claim_mod.acquire(device, "push-pc", "release push", 60, now=T0)

    claim = claim_mod.acquire(device, "rosy-auto-update", "update", 1800, now=T0 + dt.timedelta(seconds=61))

    assert claim["holder"] == "rosy-auto-update"
    assert not list((device / "run").glob("rosy-claim.stale.*"))  # cleared after the rename


def test_a_claim_from_another_boot_is_stale(device):
    claim_mod.acquire(device, "push-pc", "release push", 3600, now=T0)
    (device / "proc/sys/kernel/random/boot_id").write_text("other-boot\n", encoding="utf-8")

    claim = claim_mod.acquire(device, "rosy-auto-update", "update", 1800, now=T0)

    assert claim["holder"] == "rosy-auto-update"
    assert claim["boot_id"] == "other-boot"


def test_a_claim_directory_without_claim_json_is_busy_while_young(device):
    # The winner of mkdir has not written claim.json yet.
    _claim_dir(device).mkdir()
    young = T0.timestamp()
    os.utime(_claim_dir(device), (young, young))

    with pytest.raises(claim_mod.ClaimBusy):
        claim_mod.acquire(device, "rosy-auto-update", "update", 1800, now=T0 + dt.timedelta(seconds=5))

    claim = claim_mod.acquire(device, "rosy-auto-update", "update", 1800, now=T0 + dt.timedelta(seconds=120))
    assert claim["holder"] == "rosy-auto-update"


def test_only_one_party_wins_a_stale_takeover(device, monkeypatch):
    claim_mod.acquire(device, "push-pc", "release push", 60, now=T0)
    later = T0 + dt.timedelta(seconds=120)
    real_rename = os.rename

    def racing_rename(source, destination):
        # Another party moved the stale claim aside and took the name first.
        if str(destination).count("rosy-claim.stale.") and not getattr(racing_rename, "done", False):
            racing_rename.done = True
            real_rename(source, str(destination) + "-peer")
            # A peer that does not use the lock (the contract's bare mkdir) wins the name.
            claim_mod._acquire_locked(device / "run" / "rosy-claim", "peer", "peer", 1800, later, BOOT)
            raise FileNotFoundError(source)
        return real_rename(source, destination)

    monkeypatch.setattr(claim_mod.os, "rename", racing_rename)

    with pytest.raises(claim_mod.ClaimBusy) as caught:
        claim_mod.acquire(device, "rosy-auto-update", "update", 1800, now=later)
    assert caught.value.claim["holder"] == "peer"


def test_release_only_by_the_holder(device):
    claim_mod.acquire(device, "push-pc", "release push", 1800, now=T0)

    assert claim_mod.release(device, "rosy-auto-update") is False
    assert _claim_dir(device).is_dir()
    assert claim_mod.release(device, "push-pc") is True
    assert not _claim_dir(device).exists()
    assert claim_mod.release(device, "push-pc") is False


def test_release_that_loses_the_rename_reports_false(device, monkeypatch):
    claim_mod.acquire(device, "push-pc", "release push", 1800, now=T0)

    def lost(source, destination):
        raise FileNotFoundError(source)

    monkeypatch.setattr(claim_mod.os, "rename", lost)
    assert claim_mod.release(device, "push-pc") is False


def test_check_reports_a_live_claim_without_taking_it(device):
    assert claim_mod.check(device, now=T0) is None
    claim_mod.acquire(device, "push-pc", "release push", 60, now=T0)

    assert claim_mod.check(device, now=T0)["holder"] == "push-pc"
    assert claim_mod.check(device, now=T0 + dt.timedelta(seconds=61)) is None  # stale = acquirable
    assert _claim_dir(device).is_dir()


@pytest.mark.parametrize("ttl", [0, -1, 24 * 3600 + 1])
def test_ttl_must_be_bounded(device, ttl):
    with pytest.raises(ValueError):
        claim_mod.acquire(device, "push-pc", "release push", ttl, now=T0)


@pytest.mark.parametrize("holder", ["", "a b", "x" * 65, "evil;rm"])
def test_holder_must_be_a_plain_name(device, holder):
    with pytest.raises(ValueError):
        claim_mod.acquire(device, holder, "release push", 60, now=T0)


def test_cli_acquire_busy_release(device, capsys):
    assert claim_mod.main(["--root", str(device), "acquire", "--holder", "push-pc",
                           "--purpose", "release push", "--ttl-s", "600"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["ok"] is True and first["claim"]["holder"] == "push-pc"

    assert claim_mod.main(["--root", str(device), "acquire", "--holder", "other",
                           "--purpose", "x", "--ttl-s", "600"]) == 3
    busy = json.loads(capsys.readouterr().out)
    assert busy["ok"] is False and busy["error"] == "CLAIM_BUSY" and busy["claim"]["holder"] == "push-pc"

    assert claim_mod.main(["--root", str(device), "show"]) == 0
    assert json.loads(capsys.readouterr().out)["claim"]["holder"] == "push-pc"

    assert claim_mod.main(["--root", str(device), "status"]) == 0  # T3 calls it "status"
    assert json.loads(capsys.readouterr().out)["claim"]["holder"] == "push-pc"

    assert claim_mod.main(["--root", str(device), "release", "--holder", "other"]) == 3
    assert json.loads(capsys.readouterr().out)["released"] is False
    assert json.loads((device / "run/rosy-claim/claim.json").read_text(encoding="utf-8"))["holder"] == "push-pc"
    assert claim_mod.main(["--root", str(device), "release", "--holder", "push-pc"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "released": True}


def test_refresh_extends_only_the_holders_claim(device):
    # M8 (review): a long run keeps its claim alive at each journal step.
    claim_mod.acquire(device, "rosy-auto-update", "update", 60, now=T0)
    later = T0 + dt.timedelta(seconds=50)

    assert claim_mod.refresh(device, "someone-else", 600, now=later) is False
    assert claim_mod.refresh(device, "rosy-auto-update", 600, now=later) is True

    on_disk = json.loads((_claim_dir(device) / "claim.json").read_text(encoding="utf-8"))
    assert on_disk["expires_at"] == "2026-10-01T12:10:50Z"
    assert on_disk["acquired_at"] == "2026-10-01T12:00:00Z"


def test_takeover_is_serialised_by_the_claim_lock(device):
    # M9 (review): the stale check, rename and mkdir run under /run/rosy-claim.lock.
    claim_mod.acquire(device, "push-pc", "release push", 60, now=T0)
    later = T0 + dt.timedelta(seconds=120)
    with claim_mod._claim_lock(device, wait_s=1.0):
        with pytest.raises(claim_mod.ClaimBusy, match="lock"):
            claim_mod.acquire(device, "rosy-auto-update", "update", 1800, now=later, lock_wait_s=0.2)
    assert json.loads((_claim_dir(device) / "claim.json").read_text(encoding="utf-8"))["holder"] == "push-pc"

    assert claim_mod.acquire(device, "rosy-auto-update", "update", 1800, now=later)["holder"] == "rosy-auto-update"
    assert (device / "run" / "rosy-claim.lock").is_file()


def test_cli_refresh(device, capsys):
    # T3's push: rosy_claim.py refresh --holder H --ttl-s N
    assert claim_mod.main(["--root", str(device), "refresh", "--holder", "push-pc", "--ttl-s", "600"]) == 3
    missing = json.loads(capsys.readouterr().out)
    assert missing == {"ok": False, "error": "CLAIM_MISSING", "claim": None}

    claim_mod.acquire(device, "push-pc", "release push", 60)
    before = json.loads((_claim_dir(device) / "claim.json").read_text(encoding="utf-8"))["expires_at"]
    assert claim_mod.main(["--root", str(device), "refresh", "--holder", "push-pc", "--ttl-s", "1800"]) == 0
    refreshed = json.loads(capsys.readouterr().out)
    assert refreshed["ok"] is True and refreshed["claim"]["holder"] == "push-pc"
    assert refreshed["claim"]["expires_at"] > before

    assert claim_mod.main(["--root", str(device), "refresh", "--holder", "other", "--ttl-s", "600"]) == 3
    busy = json.loads(capsys.readouterr().out)
    assert busy["ok"] is False and busy["error"] == "CLAIM_BUSY" and busy["claim"]["holder"] == "push-pc"

    assert claim_mod.main(["--root", str(device), "refresh", "--holder", "push-pc", "--ttl-s", "0"]) == 2
    capsys.readouterr()
    with pytest.raises(SystemExit) as caught:
        claim_mod.main(["--root", str(device), "refresh", "--holder", "push-pc"])
    assert caught.value.code == 2


def test_cli_refresh_waits_for_the_claim_lock(device, capsys, monkeypatch):
    claim_mod.acquire(device, "push-pc", "release push", 60)
    monkeypatch.setattr(claim_mod, "LOCK_WAIT_S", 0.2)
    with claim_mod._claim_lock(device, wait_s=1.0):
        assert claim_mod.main(["--root", str(device), "refresh", "--holder", "push-pc", "--ttl-s", "600"]) == 3
    busy = json.loads(capsys.readouterr().out)
    assert busy["error"] == "CLAIM_BUSY" and "lock" in busy["detail"]
