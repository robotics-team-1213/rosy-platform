import json
import os
from pathlib import Path
import sys

import pytest

DIRECTORY = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"
sys.path.insert(0, str(DIRECTORY))
import cell_arm_lease as lease  # noqa: E402


def test_same_owner_refreshes_and_keeps_acquired(tmp_path):
    first = lease.claim("arm_a", "u@x", "calibrate", root=tmp_path, now=100)
    again = lease.claim("arm_a", "u@x", "record", root=tmp_path, now=200)
    assert again["acquired"] == first["acquired"] == 100
    assert again["purpose"] == "record" and again["expires"] == 200 + 1800


def test_other_owner_is_refused_while_live_and_named(tmp_path):
    lease.claim("arm_a", "u@x", "calibrate", root=tmp_path)
    with pytest.raises(lease.LeaseHeld, match="u@x.*calibrate"):
        lease.claim("arm_a", "v@y", root=tmp_path)


def test_expired_lease_can_be_taken(tmp_path):
    lease.claim("arm_a", "u@x", ttl_s=10, root=tmp_path, now=100)
    assert not lease.live(lease.status("arm_a", tmp_path)["arm_a"], now=111)
    assert lease.claim("arm_a", "v@y", root=tmp_path, now=111)["owner"] == "v@y"


def test_dead_pid_is_not_live(tmp_path, monkeypatch):
    rec = lease.claim("arm_a", "u@x", pid=os.getpid(), root=tmp_path)
    assert lease.live(rec)
    monkeypatch.setattr(lease, "_pid_alive", lambda pid: False)
    assert not lease.live(rec)
    assert lease.claim("arm_a", "v@y", root=tmp_path)["owner"] == "v@y"


def test_release_never_removes_another_owners_lease(tmp_path):
    lease.claim("arm_a", "u@x", root=tmp_path)
    assert not lease.release("arm_a", "v@y", root=tmp_path)
    assert "arm_a" in lease.status(root=tmp_path)
    assert lease.release("arm_a", "u@x", root=tmp_path)
    assert lease.status(root=tmp_path) == {}


def test_status_lists_arms_with_live_flag(tmp_path):
    lease.claim("arm_a", "u@x", root=tmp_path)
    lease.claim("arm_b", "u@x", ttl_s=1, root=tmp_path, now=1)
    st = lease.status(root=tmp_path)
    assert (st["arm_a"]["live"], st["arm_b"]["live"]) == (True, False)
    assert list(lease.status("arm_a", tmp_path)) == ["arm_a"]


def test_cli_exit_2_on_refusal(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROSY_ARM_LEASES", str(tmp_path))
    assert lease.main(["claim", "--arm", "arm_a", "--owner", "u@x", "--purpose", "cal"]) == 0
    assert lease.main(["claim", "--arm", "arm_a", "--owner", "v@y"]) == 2
    assert "u@x" in capsys.readouterr().out
    assert lease.main(["release", "--arm", "arm_a", "--owner", "u@x"]) == 0


def test_record_session_refuses_when_another_owner_holds_the_arm(tmp_path, monkeypatch):
    import record_session_cli as cli

    monkeypatch.setenv("ROSY_ARM_LEASES", str(tmp_path))
    monkeypatch.setenv("ROSY_ARM_LEASE_OWNER", "me@here")
    lease.claim("arm_b", "other@there", "calibrate", root=tmp_path)
    with pytest.raises(SystemExit, match="REFUSED: arm lease: .*other@there"):
        cli.claim_arm_lease("arm_b")
    lease.release("arm_b", "other@there", root=tmp_path)
    assert cli.claim_arm_lease("arm_b")[1] is True
    assert cli.claim_arm_lease("arm_b")[1] is False  # same owner already held it
