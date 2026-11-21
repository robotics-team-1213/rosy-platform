"""omx_real2sim_stage: a fresh snapshot rides a WIP commit parented on the code SHA, adding only its own path."""
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sim"))
import omx_real2sim_stage as st  # noqa: E402


def _repo(tmp_path, monkeypatch):
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "t")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "t@t")
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    run("init", "-q")
    (tmp_path / "code.py").write_text("x = 1\n")
    run("add", "code.py")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
    return run


def test_stage_adds_only_the_snapshot(tmp_path, monkeypatch):
    run = _repo(tmp_path, monkeypatch)
    head = run("rev-parse", "HEAD")
    snap = tmp_path / "out" / "snapshot.json"
    snap.parent.mkdir()
    snap.write_text('{"a": 1}')
    got = st.stage(tmp_path, head, snap)
    assert got["code_sha"] == head and got["rel"] == f"{st.SNAP_DIR}/out.json"
    assert run("rev-parse", f"{got['sha']}^") == head
    assert run("diff-tree", "--no-commit-id", "--name-only", "-r", head, got["sha"]) == got["rel"]
    assert run("show", f"{got['sha']}:{got['rel']}") == '{"a": 1}'
    key = hashlib.sha256((head + got["snapshot_sha256"]).encode()).hexdigest()[:12]
    assert run("rev-parse", f"refs/rosy-wip/r2s-{key}") == got["sha"]
    assert run("diff", "--cached", "--name-only") == "" and run("ls-files", "-s", got["rel"]) == ""  # the shared index never saw it
    assert run("rev-parse", "HEAD") == head and run("status", "--porcelain", "code.py") == ""


def test_stage_refuses_a_name_taken_with_other_bytes(tmp_path, monkeypatch):
    run = _repo(tmp_path, monkeypatch)
    rel = f"{st.SNAP_DIR}/s.json"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text("old")
    run("add", rel)
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "s")
    fresh = tmp_path / "fresh.json"
    fresh.write_text("new")
    with pytest.raises(SystemExit, match="other bytes"):
        st.stage(tmp_path, run("rev-parse", "HEAD"), fresh, rel)


def test_stage_hashes_raw_bytes_not_the_crlf_filter(tmp_path, monkeypatch):
    run = _repo(tmp_path, monkeypatch)
    run("config", "core.autocrlf", "true")
    snap = tmp_path / "s.json"
    snap.write_bytes(b'{"a":\r\n1}\r\n')
    got = st.stage(tmp_path, run("rev-parse", "HEAD"), snap)
    assert run("rev-parse", f"{got['sha']}:{got['rel']}") == run("hash-object", "--no-filters", str(snap))  # the blob that ships is the file


def test_a_newer_code_sha_keeps_the_older_ref(tmp_path, monkeypatch):
    run = _repo(tmp_path, monkeypatch)
    snap = tmp_path / "s.json"
    snap.write_text("one")
    first = st.stage(tmp_path, run("rev-parse", "HEAD"), snap)
    (tmp_path / "code.py").write_text("x = 2\n")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "c2")
    second = st.stage(tmp_path, run("rev-parse", "HEAD"), snap)
    refs = run("for-each-ref", "--format=%(objectname)", "refs/rosy-wip/").split()
    assert {first["sha"], second["sha"]} <= set(refs)


def test_stage_refuses_a_path_outside_the_snapshot_dir(tmp_path, monkeypatch):
    run = _repo(tmp_path, monkeypatch)
    snap = tmp_path / "s.json"
    snap.write_text("x")
    with pytest.raises(SystemExit, match="outside"):
        st.stage(tmp_path, run("rev-parse", "HEAD"), snap, "code.py")


def test_committed_means_the_same_bytes_not_just_the_same_path(tmp_path, monkeypatch):
    run = _repo(tmp_path, monkeypatch)
    rel = f"{st.SNAP_DIR}/s.json"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_bytes(b"old")
    run("add", rel)
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "s")
    head = run("rev-parse", "HEAD")
    assert st.committed(tmp_path, head, rel, tmp_path / rel)
    (tmp_path / rel).write_bytes(b"edited in place")  # re-measured into the same stamp: the old blob would run
    assert not st.committed(tmp_path, head, rel, tmp_path / rel)
    assert not st.committed(tmp_path, head, f"{st.SNAP_DIR}/none.json", tmp_path / rel)
