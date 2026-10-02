"""D-411 A: listing and tar streaming never leave the recording folder."""

import hashlib
import io
import json
import os
import tarfile

import pytest

from core_common.domain import pilot_recording_store as store

RID = "20261002T101500Z_rosy_01"


def make(root, rid=RID, *, manifest=True, files=None, fetched=False):
    folder = root / rid
    (folder / "bag").mkdir(parents=True)
    (folder / "bag" / "bag_0.mcap").write_bytes(b"m" * 700)
    (folder / "session.json").write_text(json.dumps({
        "schema": "rosy.recording.session/1", "device": "rosy_01", "started_at": "2026-10-02T10:15:00Z",
        "ended_at": "2026-10-02T10:16:00Z" if manifest else None, "mode": "pilot",
        "topics": ["cmd_vel"], "harvested": False}), encoding="utf-8")
    if manifest:
        entries = files or [
            {"path": p, "bytes": (folder / p).stat().st_size,
             "sha256": hashlib.sha256((folder / p).read_bytes()).hexdigest()}
            for p in ("bag/bag_0.mcap", "session.json")]
        (folder / "manifest.json").write_text(json.dumps({
            "schema": "rosy.pilot.recording.manifest/1", "id": rid, "started_at": "2026-10-02T10:15:00Z",
            "ended_at": "2026-10-02T10:16:00Z", "duration_s": 60.0, "topics": ["cmd_vel"],
            "stop_reason": "requested", "files": entries}), encoding="utf-8")
    if fetched:
        (folder / "fetched.json").write_text("{}", encoding="utf-8")
    return folder


def test_list_reports_status_size_and_manifest_hash(tmp_path):
    folder = make(tmp_path)
    make(tmp_path, "20261002T101700Z_rosy_01", manifest=False)
    (tmp_path / "not-a-recording").mkdir()
    items = {item["id"]: item for item in store.list_recordings(tmp_path, active_id=None)}
    assert set(items) == {RID, "20261002T101700Z_rosy_01"}
    assert items[RID]["status"] == "complete"
    assert items[RID]["manifest_sha256"] == hashlib.sha256(
        (folder / "manifest.json").read_bytes()).hexdigest()
    assert items[RID]["duration_s"] == 60.0 and items[RID]["fetched"] is False
    assert items[RID]["bytes"] == sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    assert items["20261002T101700Z_rosy_01"]["status"] == "incomplete"
    assert items["20261002T101700Z_rosy_01"]["manifest_sha256"] is None


def test_list_is_newest_first_and_marks_fetched(tmp_path):
    make(tmp_path, fetched=True)
    newer = "20261002T111500Z_rosy_01"
    folder = make(tmp_path, newer)
    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    session["started_at"] = "2026-10-02T11:15:00Z"
    (folder / "session.json").write_text(json.dumps(session), encoding="utf-8")
    items = store.list_recordings(tmp_path, active_id=None)
    assert [item["id"] for item in items] == [newer, RID]
    assert items[1]["fetched"] is True


def test_non_pilot_sessions_and_a_missing_root_are_skipped(tmp_path):
    folder = make(tmp_path)
    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    session["mode"] = "shadow"
    (folder / "session.json").write_text(json.dumps(session), encoding="utf-8")
    assert store.list_recordings(tmp_path, active_id=None) == []
    assert store.list_recordings(tmp_path / "absent", active_id=None) == []


def test_active_recording_is_listed_as_recording(tmp_path):
    make(tmp_path, manifest=False)
    (item,) = store.list_recordings(tmp_path, active_id=RID)
    assert item["status"] == "recording"


def test_archive_stream_is_a_valid_tar_with_exact_length(tmp_path):
    make(tmp_path)
    members, length = store.archive_plan(tmp_path, RID)
    data = b"".join(store.iter_archive(members))
    assert len(data) == length
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        names = archive.getnames()
        assert names == [f"{RID}/manifest.json", f"{RID}/bag/bag_0.mcap", f"{RID}/session.json"]
        assert archive.extractfile(f"{RID}/bag/bag_0.mcap").read() == b"m" * 700


@pytest.mark.parametrize("rid", ["../x", "20261002T101500Z_missing", "manifest.json"])
def test_unknown_or_unsafe_ids_are_not_found(tmp_path, rid):
    make(tmp_path)
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, rid)


def test_manifest_path_escape_is_refused(tmp_path):
    make(tmp_path, files=[{"path": "../../etc/passwd", "bytes": 1, "sha256": "a" * 64}])
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, RID)


def test_missing_member_is_refused(tmp_path):
    make(tmp_path, files=[{"path": "bag/bag_1.mcap", "bytes": 1, "sha256": "a" * 64}])
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, RID)


def test_manifest_naming_another_recording_is_refused(tmp_path):
    folder = make(tmp_path)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    manifest["id"] = "20261002T999999Z_other"
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, RID)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlinked_member_is_refused(tmp_path):
    folder = make(tmp_path)
    target = folder / "bag" / "bag_0.mcap"
    target.unlink()
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, RID)


def test_size_change_since_the_manifest_is_refused(tmp_path):
    folder = make(tmp_path)
    (folder / "bag" / "bag_0.mcap").write_bytes(b"m" * 10)
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, RID)


def test_incomplete_recording_has_no_archive(tmp_path):
    make(tmp_path, manifest=False)
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, RID)


def test_a_member_that_shrinks_while_streaming_fails_the_stream(tmp_path):
    folder = make(tmp_path)
    members, _ = store.archive_plan(tmp_path, RID)
    (folder / "bag" / "bag_0.mcap").write_bytes(b"m" * 10)
    with pytest.raises(OSError):
        b"".join(store.iter_archive(members))


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_symlinked_recording_folder_is_refused(tmp_path):
    real = make(tmp_path / "elsewhere")
    (tmp_path / "rec").mkdir()
    (tmp_path / "rec" / RID).symlink_to(real, target_is_directory=True)
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path / "rec", RID)
    assert store.list_recordings(tmp_path / "rec", active_id=None) == []


def test_a_member_replaced_after_the_plan_fails_the_stream(tmp_path):
    folder = make(tmp_path)
    members, _ = store.archive_plan(tmp_path, RID)
    keep = folder / "bag" / "keep"
    (folder / "bag" / "bag_0.mcap").rename(keep)          # the planned file stays alive
    (folder / "bag" / "bag_0.mcap").write_bytes(b"n" * 700)   # same size, another file
    with pytest.raises(OSError):
        b"".join(store.iter_archive(members))


def test_the_manifest_is_streamed_from_the_validated_bytes(tmp_path):
    folder = make(tmp_path)
    original = (folder / "manifest.json").read_bytes()
    members, length = store.archive_plan(tmp_path, RID)
    (folder / "manifest.json").write_bytes(b"{}")
    data = b"".join(store.iter_archive(members))
    assert len(data) == length
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        assert archive.extractfile(f"{RID}/manifest.json").read() == original
