"""D-373 decision 8: the store folder is the source of truth for datasets and models."""
import hashlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "tools" / "perception") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "perception"))

import store  # noqa: E402


def _tree(root: Path, files: dict) -> Path:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return root


def _ready(folder: Path) -> Path:
    (folder / store.READY).write_text(store.content_sha(folder), encoding="utf-8")
    return folder


# --- content_sha ----------------------------------------------------------------------------

def test_content_sha_is_the_documented_formula(tmp_path):
    _tree(tmp_path, {"b.txt": "B", "a/x.bin": b"\x00\x01"})
    lines = sorted(f"{rel}\0{hashlib.sha256(data).hexdigest()}\n".encode()
                   for rel, data in (("b.txt", b"B"), ("a/x.bin", b"\x00\x01")))
    assert store.content_sha(tmp_path) == hashlib.sha256(b"".join(lines)).hexdigest()


def test_content_sha_ignores_os_litter_and_the_marker(tmp_path):
    _tree(tmp_path, {"m.json": "{}", "d/f": "x"})
    before = store.content_sha(tmp_path)
    _tree(tmp_path, {".DS_Store": "x", "d/Thumbs.db": "y", "desktop.ini": "z", store.READY: "r"})
    assert store.content_sha(tmp_path) == before


def test_content_sha_changes_with_content_or_name(tmp_path):
    a = _tree(tmp_path / "a", {"f": "1"})
    b = _tree(tmp_path / "b", {"f": "2"})
    c = _tree(tmp_path / "c", {"g": "1"})
    assert len({store.content_sha(a), store.content_sha(b), store.content_sha(c)}) == 3


def test_content_sha_is_independent_of_the_path_separator(tmp_path):
    folder = _tree(tmp_path / "f", {"images/shard_0000/s1__0.jpg": "x", "manifest.json": "{}"})
    sha = store.content_sha(folder)
    assert store.content_sha(str(folder)) == sha
    # the lines use forward slashes whatever os.sep is
    expect = hashlib.sha256(b"".join(sorted([
        f"images/shard_0000/s1__0.jpg\0{hashlib.sha256(b'x').hexdigest()}\n".encode(),
        f"manifest.json\0{hashlib.sha256(b'{}').hexdigest()}\n".encode()]))).hexdigest()
    assert sha == expect


def test_content_sha_of_an_empty_or_missing_folder(tmp_path):
    assert store.content_sha(tmp_path) == hashlib.sha256(b"").hexdigest()
    with pytest.raises(FileNotFoundError):
        store.content_sha(tmp_path / "nope")


# --- datasets -------------------------------------------------------------------------------

def test_put_dataset_copies_into_the_content_address(tmp_path):
    src = _tree(tmp_path / "src", {"manifest.json": "{}", "images/a.jpg": "x"})
    st = store.Store(tmp_path / "store")
    path, sha = st.put_dataset(src, "lane")
    assert path == tmp_path / "store" / "datasets" / "lane" / sha
    assert store.content_sha(path) == sha == store.content_sha(src)
    assert (path / "images" / "a.jpg").read_text() == "x"
    assert not [p for p in path.parent.iterdir() if p.name != sha]  # no temp left


def test_put_dataset_is_idempotent_and_never_overwrites(tmp_path):
    src = _tree(tmp_path / "src", {"manifest.json": "{}"})
    st = store.Store(tmp_path / "store")
    path, sha = st.put_dataset(src, "lane")
    stamp = (path / "manifest.json").stat().st_mtime_ns
    assert st.put_dataset(src, "lane") == (path, sha)
    assert (path / "manifest.json").stat().st_mtime_ns == stamp
    (path / "manifest.json").write_text("tampered")
    with pytest.raises(store.StoreError, match="differs"):
        st.put_dataset(src, "lane")


@pytest.mark.parametrize("name", ["", "..", "a/b", "a\\b", "-x", " x"])
def test_put_dataset_refuses_unsafe_names(tmp_path, name):
    src = _tree(tmp_path / "src", {"f": "1"})
    with pytest.raises(store.StoreError):
        store.Store(tmp_path / "store").put_dataset(src, name)


def test_dataset_path_and_listing(tmp_path):
    st = store.Store(tmp_path / "store")
    _, s1 = st.put_dataset(_tree(tmp_path / "a", {"f": "1"}), "lane")
    _, s2 = st.put_dataset(_tree(tmp_path / "b", {"f": "2"}), "lane")
    assert st.dataset_path("lane", s1) == tmp_path / "store" / "datasets" / "lane" / s1
    assert sorted(st.datasets()["lane"]) == sorted([s1, s2])
    assert store.parse_dataset_ref(f"store:lane@{s1}") == ("lane", s1)
    assert store.parse_dataset_ref(f"lane@{s1}") == ("lane", s1)
    with pytest.raises(ValueError):
        store.parse_dataset_ref("lane@abc")


# --- inbox ----------------------------------------------------------------------------------

def test_inbox_folder_is_ready_only_with_a_matching_marker(tmp_path):
    st = store.Store(tmp_path / "store")
    st.ensure_layout()
    folder = _tree(st.inbox / "m1", {"model.onnx": "w", "model_manifest.json": "{}"})
    assert not st.inbox_ready(folder)                        # no marker: still syncing
    (folder / store.READY).write_text("0" * 64)
    assert not st.inbox_ready(folder)                        # wrong marker
    _ready(folder)
    assert st.inbox_ready(folder)
    assert st.inbox_ready("m1")                              # by folder name too
    (folder / "model.onnx").write_text("half-synced")
    assert not st.inbox_ready(folder)                        # content changed after READY
    (folder / store.READY).write_text(store.content_sha(folder) + "\r\n")
    assert st.inbox_ready(folder)                            # whitespace around the sha is fine


def test_list_inbox_is_ready_folders_oldest_marker_first(tmp_path):
    st = store.Store(tmp_path / "store")
    st.ensure_layout()
    new = _ready(_tree(st.inbox / "b-new", {"f": "1"}))
    old = _ready(_tree(st.inbox / "a-old", {"f": "2"}))
    _tree(st.inbox / "c-partial", {"f": "3"})                # no marker: ignored
    (st.inbox / "stray.intake_report.json").write_text("{}")  # files are not folders
    os.utime(old / store.READY, (1000, 1000))
    os.utime(new / store.READY, (2000, 2000))
    assert st.list_inbox() == ["a-old", "b-new"]
    assert store.Store(tmp_path / "missing").list_inbox() == []


def test_accept_moves_to_the_revision_and_is_idempotent(tmp_path):
    st = store.Store(tmp_path / "store")
    st.ensure_layout()
    _ready(_tree(st.inbox / "rev1__t", {"f": "1"}))
    dest = st.accept("rev1__t", "rev1")
    assert dest == st.accepted / "rev1" and (dest / "f").read_text() == "1"
    assert not (st.inbox / "rev1__t").exists()
    _ready(_tree(st.inbox / "rev1__t2", {"f": "1"}))         # the same model handed over again
    assert st.accept("rev1__t2", "rev1") == dest
    assert not (st.inbox / "rev1__t2").exists()
    _ready(_tree(st.inbox / "rev1__t3", {"f": "other"}))
    with pytest.raises(store.StoreError, match="already accepted"):
        st.accept("rev1__t3", "rev1")
    assert (st.inbox / "rev1__t3").exists()


def test_reject_moves_and_writes_the_reason(tmp_path):
    st = store.Store(tmp_path / "store")
    st.ensure_layout()
    _tree(st.inbox / "bad", {"f": "1"})
    dest = st.reject("bad", "latency p50 90 ms > 60 ms")
    assert dest == st.rejected / "bad"
    assert "latency p50" in (dest / store.REASON).read_text(encoding="utf-8")
    _tree(st.inbox / "bad", {"f": "2"})                      # a second folder of the same name
    dest2 = st.reject("bad", "again")
    assert dest2 != dest and dest2.parent == st.rejected and dest.exists()


def test_move_falls_back_to_copy_verify_remove_across_devices(tmp_path, monkeypatch):
    st = store.Store(tmp_path / "store")
    st.ensure_layout()
    _ready(_tree(st.inbox / "x", {"a/b": "1", "c": "2"}))

    def cross_device(src, dst):
        raise OSError(18, "Invalid cross-device link")
    monkeypatch.setattr(store.os, "rename", cross_device)
    dest = st.accept("x", "rev-x")
    assert (dest / "a" / "b").read_text() == "1" and not (st.inbox / "x").exists()


@pytest.mark.parametrize("bad", ["..", "a/b", "", "../x"])
def test_inbox_names_cannot_escape(tmp_path, bad):
    st = store.Store(tmp_path / "store")
    st.ensure_layout()
    with pytest.raises(store.StoreError):
        st.inbox_folder(bad)


def test_status_counts(tmp_path):
    st = store.Store(tmp_path / "store")
    st.ensure_layout()
    _ready(_tree(st.inbox / "r", {"f": "1"}))
    _tree(st.inbox / "p", {"f": "2"})
    _ready(_tree(st.inbox / "a", {"f": "3"}))
    st.accept("a", "rev-a")
    s = st.status()
    assert s["inbox_ready"] == 1 and s["inbox_waiting"] == 1
    assert s["accepted"] == 1 and s["rejected"] == 0
    assert s["datasets"] == {}
