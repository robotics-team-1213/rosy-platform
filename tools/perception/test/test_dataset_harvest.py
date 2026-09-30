import hashlib
import json

import pytest

import harvest


def test_sessions_to_fetch():
    listing = [
        {"name": "a", "ended_at": "t", "harvested": False},
        {"name": "b", "ended_at": None, "harvested": False},
        {"name": "c", "ended_at": "t", "harvested": True},
        {"name": "d", "ended_at": "t"},
    ]
    assert harvest.sessions_to_fetch(listing) == ["a", "d"]


def test_verify_tree_detects_change(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "x.bin").write_bytes(b"one")
    (tmp_path / "y.bin").write_bytes(b"two")
    sums = {"s/x.bin": hashlib.sha256(b"one").hexdigest(),
            "y.bin": hashlib.sha256(b"two").hexdigest()}
    assert harvest.verify_tree(tmp_path, sums) == []
    (tmp_path / "y.bin").write_bytes(b"TWO")
    assert harvest.verify_tree(tmp_path, sums) == ["y.bin"]
    assert harvest.verify_tree(tmp_path, {**sums, "z": "0"}) == ["y.bin", "z"]


def test_verify_tree_reports_extra_local(tmp_path):
    (tmp_path / "a").write_bytes(b"1")
    (tmp_path / "extra").write_bytes(b"x")
    sums = {"a": hashlib.sha256(b"1").hexdigest()}
    assert harvest.verify_tree(tmp_path, sums) == ["extra"]


SSH = ["--identity", "/keys/id", "--known-hosts", "/keys/kh"]
IDLE = {"mode": "IDLE", "navigation": "IDLE", "velocity": {"linear": 0.0, "angular": 0.0},
        "line_follow": {"mode": "OFF", "state": "OFF"}}


def test_safe_names_and_args():
    assert harvest.safe_name("20260930T010203Z_pinky-1")
    assert not harvest.safe_name("../x")
    assert not harvest.safe_name("a b")
    assert not harvest.safe_name("-rf")
    assert harvest.safe_component("pinky/005 x") == "pinky_005_x"
    assert harvest.main([*SSH, "--", "-oProxyCommand=x"]) == 2
    assert harvest.main(["h", "--user=-x", *SSH]) == 2


# --- D-136 idle rule: never pull recordings off a robot that is driving ---------------------

def test_idle_state_is_idle():
    assert harvest.idle_verdict(IDLE) == (True, "idle")
    # a CORE without line_follow (pre v1.10) cannot line-follow
    older = {k: v for k, v in IDLE.items() if k != "line_follow"}
    assert harvest.idle_verdict(older)[0] is True
    for nav in ("ARRIVED", "CANCELED", "FAILED"):
        assert harvest.idle_verdict({**IDLE, "navigation": nav})[0] is True


@pytest.mark.parametrize("change, why", [
    ({"mode": "NAVIGATION"}, "mode"),
    ({"mode": "MANUAL"}, "mode"),
    ({"mode": "DOCKING"}, "mode"),
    ({"mode": None}, "mode"),
    ({"navigation": "NAVIGATING"}, "navigation"),
    ({"navigation": "PLANNING"}, "navigation"),
    ({"navigation": "BLOCKED"}, "navigation"),
    ({"velocity": {"linear": 0.05, "angular": 0.0}}, "velocity"),
    ({"velocity": {"linear": 0.0, "angular": -0.2}}, "velocity"),
    ({"velocity": {"linear": "x", "angular": 0.0}}, "velocity"),
    ({"velocity": None}, "velocity"),
    ({"line_follow": {"mode": "LANE", "state": "WAITING"}}, "line_follow"),
])
def test_moving_or_unknown_state_is_not_idle(change, why):
    idle, reason = harvest.idle_verdict({**IDLE, **change})
    assert idle is False and why in reason


def test_non_dict_state_is_not_idle():
    assert harvest.idle_verdict(None)[0] is False
    assert harvest.idle_verdict([])[0] is False


def _fake_listing(monkeypatch, listing):
    calls = []

    def fake_ssh(base, target, command):
        if command.startswith("python3 -c") and "glob" in command:
            return json.dumps(listing)
        calls.append(command)
        raise RuntimeError("boom")

    monkeypatch.setattr(harvest, "_ssh", fake_ssh)
    return calls


def test_driving_robot_is_skipped_with_exit_4(monkeypatch, tmp_path, capsys):
    token = tmp_path / "core.token"
    token.write_text("secret\n", encoding="utf-8")
    seen = {}

    def fake_state(url, tok, timeout):
        seen.update(url=url, token=tok)
        return {**IDLE, "mode": "NAVIGATION"}

    monkeypatch.setattr(harvest, "fetch_core_state", fake_state)
    ran = []
    monkeypatch.setattr(harvest.subprocess, "run", lambda *a, **k: ran.append(a))
    calls = _fake_listing(monkeypatch, [{"name": "a", "ended_at": "t", "harvested": False}])
    rc = harvest.main(["robot", "--dest", str(tmp_path), "--core-token-file", str(token), *SSH])
    assert rc == 4
    assert ran == [] and calls == []  # nothing transferred, nothing marked
    assert seen == {"url": "http://robot:8080/api/v1/robot/state", "token": "secret"}
    assert "mode NAVIGATION" in capsys.readouterr().err


def test_core_unreachable_is_skipped_with_exit_4(monkeypatch, tmp_path):
    token = tmp_path / "core.token"
    token.write_text("secret", encoding="utf-8")

    def down(url, tok, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(harvest, "fetch_core_state", down)
    _fake_listing(monkeypatch, [{"name": "a", "ended_at": "t", "harvested": False}])
    assert harvest.main(["robot", "--dest", str(tmp_path), "--core-token-file", str(token),
                         *SSH]) == 4


def test_no_token_and_no_assume_idle_is_refused(monkeypatch, tmp_path):
    monkeypatch.delenv("ROSY_CORE_TOKEN_FILE", raising=False)
    _fake_listing(monkeypatch, [])
    assert harvest.main(["robot", "--dest", str(tmp_path), *SSH]) == 2


def test_assume_idle_skips_core_and_warns(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(harvest, "fetch_core_state",
                        lambda *a: (_ for _ in ()).throw(AssertionError("queried CORE")))
    _fake_listing(monkeypatch, [])
    assert harvest.main(["robot", "--dest", str(tmp_path), "--assume-idle", *SSH]) == 0
    assert "WARNING" in capsys.readouterr().err


def test_idle_is_rechecked_before_each_session(monkeypatch, tmp_path):
    token = tmp_path / "core.token"
    token.write_text("secret", encoding="utf-8")
    states = iter([IDLE, {**IDLE, "navigation": "NAVIGATING"}])
    monkeypatch.setattr(harvest, "fetch_core_state", lambda *a: next(states))

    class R:
        returncode = 1  # the first scp fails; the loop goes on to the idle check

    monkeypatch.setattr(harvest.subprocess, "run", lambda *a, **k: R())
    _fake_listing(monkeypatch, [{"name": n, "device": "d", "ended_at": "t", "harvested": False}
                                for n in ("a", "b")])
    assert harvest.main(["robot", "--dest", str(tmp_path), "--core-token-file", str(token),
                         *SSH]) == 4


def test_ssh_scp_are_rosy_pinned_and_mark_uses_sudo(monkeypatch, tmp_path):
    ran, sshed = [], []

    def fake_ssh(base, target, command):
        sshed.append((base, target, command))
        if "glob" in command:
            return json.dumps([{"name": "a", "device": "d", "ended_at": "t",
                                "harvested": False}])
        if "sha256sum" in command:
            return ""
        return ""

    class R:
        returncode = 0

    monkeypatch.setattr(harvest, "_ssh", fake_ssh)
    monkeypatch.setattr(harvest.subprocess, "run", lambda cmd, **k: ran.append(cmd) or R())
    assert harvest.main(["robot", "--dest", str(tmp_path), "--assume-idle", *SSH]) == 0
    base, target, listing = sshed[0]
    assert target == "rosy@robot"
    assert "/var/lib/rosy/camera/recordings" in listing
    for cmd in (base, ran[0]):
        assert cmd[cmd.index("-i") + 1] == "/keys/id"
        for opt in ("BatchMode=yes", "IdentitiesOnly=yes", "UserKnownHostsFile=/keys/kh",
                    "StrictHostKeyChecking=yes"):
            assert opt in cmd
        assert cmd[-1] == "--" or "--" in cmd
    assert ran[0][0] == "scp" and ran[0][-2] == "rosy@robot:/var/lib/rosy/camera/recordings/a"
    mark = sshed[-1][2]
    assert mark.startswith("sudo -n python3 -c")
    assert "chown" in mark  # session.json keeps the recorder's owner


def test_failures_counted_and_loop_continues(monkeypatch, tmp_path):
    listing = [{"name": n, "device": "d", "ended_at": "t", "harvested": False}
               for n in ("a", "b", "bad name")]
    calls = _fake_listing(monkeypatch, listing)

    class R:
        returncode = 0

    monkeypatch.setattr(harvest.subprocess, "run", lambda *a, **k: R())
    assert harvest.main(["h", "--dest", str(tmp_path), "--assume-idle", *SSH]) == 1
    assert len(calls) == 2  # both good sessions attempted, bad name skipped
