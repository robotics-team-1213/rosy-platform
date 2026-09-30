import hashlib

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


def test_safe_names_and_args():
    assert harvest.safe_name("20260930T010203Z_pinky-1")
    assert not harvest.safe_name("../x")
    assert not harvest.safe_name("a b")
    assert not harvest.safe_name("-rf")
    assert harvest.safe_component("pinky/005 x") == "pinky_005_x"
    assert harvest.main(["--", "-oProxyCommand=x"]) == 2
    assert harvest.main(["h", "--user=-x"]) == 2


def test_failures_counted_and_loop_continues(monkeypatch, tmp_path):
    listing = [{"name": n, "device": "d", "ended_at": "t", "harvested": False}
               for n in ("a", "b", "bad name")]
    calls = []

    def fake_ssh(target, command):
        if command.startswith("python3 -c") and "glob" in command:
            return __import__("json").dumps(listing)
        calls.append(command)
        raise RuntimeError("boom")

    class R:
        returncode = 0

    monkeypatch.setattr(harvest, "_ssh", fake_ssh)
    monkeypatch.setattr(harvest.subprocess, "run", lambda *a, **k: R())
    assert harvest.main(["h", "--dest", str(tmp_path)]) == 1
    assert len(calls) == 2  # both good sessions attempted, bad name skipped
