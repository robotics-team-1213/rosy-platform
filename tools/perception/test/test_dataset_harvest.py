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
