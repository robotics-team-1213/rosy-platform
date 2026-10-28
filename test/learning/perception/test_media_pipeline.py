from __future__ import annotations

import json
from pathlib import Path

import pytest

import media_pipeline as media


STAMP = "20260930T124745Z"
DEVICE = "rosy-pinky-8kcn"
STEM = f"teleop_{DEVICE}_{STAMP}"


def _session(root: Path, nested: bool = False) -> Path:
    folder = f"{STAMP}_{DEVICE}"
    session = root / "raw" / DEVICE / folder if nested else root / "raw" / folder
    (session / "bag").mkdir(parents=True)
    (session / "bag" / "bag_0.mcap").write_bytes(b"m" * 40)
    (session / "session.json").write_text(json.dumps({"device": DEVICE}), encoding="utf-8")
    return session


def _video(video_dir: Path, frames: int = 2) -> None:
    video_dir.mkdir(parents=True, exist_ok=True)
    payload = b"v" * 8
    video = video_dir / f"{STEM}.mp4"
    video.write_bytes(payload)
    (video_dir / f"{STEM}.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    (video_dir / f"{STEM}.json").write_text(json.dumps({
        "schema": "rosy.teleop.video/1",
        "video": {"file": video.name, "frames": frames, "bytes": len(payload)},
    }), encoding="utf-8")


def test_stage_order_is_fixed():
    assert media.STAGES == ("scan", "video", "verify", "reclaim", "receipt")


def test_checked_video_is_one_trainer_row_and_raw_stays(tmp_path):
    _session(tmp_path)
    _session(tmp_path, nested=True)
    video = tmp_path / "video"
    _video(video)
    code, doc = media.run(tmp_path / "raw", video, shrink=False, apply=False,
                          probe=lambda _p: 2, encode=lambda *_a: 1, compact=lambda _s: (False, _s))
    assert code == 0
    assert doc["schema"] == media.SCHEMA
    assert doc["applied"] is False
    assert {row["raw_state"] for row in doc["sessions"]} == {"kept"}
    rows = media.trainer_recordings(doc)
    assert rows == [{"session": f"{STAMP}_{DEVICE}", "video": str(video / f"{STEM}.mp4")}]


def test_apply_removes_raw_and_keeps_the_trainer_video(tmp_path):
    session = _session(tmp_path)
    compact = session.with_name(session.name + ".compact")
    compact.mkdir()
    (compact / "session.json").write_text("{}", encoding="utf-8")
    video = tmp_path / "video"
    _video(video)
    code, doc = media.run(tmp_path / "raw", video, shrink=False, apply=True,
                          probe=lambda _p: 2, encode=lambda *_a: 1, compact=lambda _s: (False, _s))
    assert code == 0
    assert not session.exists() and not compact.exists()
    assert (video / f"{STEM}.mp4").is_file()
    assert doc["sessions"][0]["raw_state"] == "removed"
    assert doc["sessions"][0]["compact_state"] == "removed"
    assert media.trainer_recordings(doc)[0]["video"].endswith(f"{STEM}.mp4")


def test_missing_video_is_made_then_handed_to_the_trainer(tmp_path):
    session = _session(tmp_path)
    video = tmp_path / "video"

    def encode(_session, dest):
        assert _session == session
        _video(dest)
        return 0

    code, doc = media.run(tmp_path / "raw", video, shrink=False, apply=False,
                          probe=lambda _p: 2, encode=encode, compact=lambda _s: (False, _s))
    assert code == 0
    assert doc["sessions"][0]["trainable"] is True
    assert session.is_dir()


def test_mismatch_is_not_trainable_and_blocks(tmp_path):
    session = _session(tmp_path)
    video = tmp_path / "video"
    _video(video)
    code, doc = media.run(tmp_path / "raw", video, shrink=False, apply=True,
                          probe=lambda _p: 9, encode=lambda *_a: 0, compact=lambda _s: (False, _s))
    assert code == 1
    assert session.is_dir()
    assert doc["sessions"][0]["trainable"] is False
    assert media.trainer_recordings(doc) == []


def test_compact_frees_disk_without_becoming_a_training_input(tmp_path):
    session = _session(tmp_path)
    video = tmp_path / "video"

    def compact(src):
        dest = src.with_name(src.name + ".compact")
        dest.mkdir()
        return True, dest

    code, doc = media.run(tmp_path / "raw", video, shrink=True, apply=True,
                          probe=lambda _p: 2, encode=lambda *_a: 1, compact=compact)
    assert code == 0
    assert not session.exists()
    assert media.trainer_recordings(doc) == []
    assert doc["sessions"][0]["status"] == "compact_ok"


def test_orphan_compact_goes_when_its_video_checks_out(tmp_path):
    compact = tmp_path / "raw" / DEVICE / f"{STAMP}_{DEVICE}.compact"
    (compact / "bag").mkdir(parents=True)
    (compact / "session.json").write_text(json.dumps({"device": DEVICE}), encoding="utf-8")
    video = tmp_path / "video"
    _video(video)
    code, doc = media.run(tmp_path / "raw", video, shrink=False, apply=True,
                          probe=lambda _p: 2, encode=lambda *_a: 1, compact=lambda _s: (False, _s))
    assert code == 0
    assert not compact.exists()
    assert doc["compacts"] == [{
        "session": f"{STAMP}_{DEVICE}",
        "compact": str(compact),
        "compact_state": "removed",
    }]
    assert media.trainer_recordings(doc) == []
    assert (video / f"{STEM}.mp4").is_file()


def test_compact_without_a_video_stays(tmp_path):
    compact = tmp_path / "raw" / f"{STAMP}_{DEVICE}.compact"
    compact.mkdir(parents=True)
    (compact / "session.json").write_text(json.dumps({"device": DEVICE}), encoding="utf-8")
    video = tmp_path / "video"
    video.mkdir()
    code, doc = media.run(tmp_path / "raw", video, shrink=False, apply=True,
                          probe=lambda _p: 2, encode=lambda *_a: 1, compact=lambda _s: (False, _s))
    assert code == 0
    assert compact.is_dir()
    assert doc["compacts"] == []


def test_receipt_schema_is_required():
    with pytest.raises(ValueError):
        media.trainer_recordings({"schema": "other"})


def test_cli_writes_receipt_without_deleting(tmp_path, capsys):
    session = _session(tmp_path)
    video = tmp_path / "video"
    _video(video)
    out = tmp_path / "receipt.json"
    code = media.main(["--root", str(tmp_path), "--video-dir", str(video), "--out", str(out)],
                      probe=lambda _p: 2, encode=lambda *_a: 1)
    assert code == 0
    assert session.is_dir()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["stages"] == list(media.STAGES)
    assert "trainable=1" in capsys.readouterr().out


def _shadow_video(video: Path, rows: list[str]) -> None:
    video.mkdir(parents=True, exist_ok=True)
    payload = b"v" * 8
    (video / f"{STEM}.mp4").write_bytes(payload)
    (video / f"{STEM}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (video / f"{STEM}.json").write_text(json.dumps({
        "schema": "rosy.teleop.video/1",
        "video": {"file": f"{STEM}.mp4", "frames": len(rows), "bytes": len(payload)},
    }), encoding="utf-8")


def test_receipt_counts_live_and_backfilled_shadow_evidence(tmp_path):
    _session(tmp_path)
    video = tmp_path / "video"
    live = {"schema": "rosy.perception.learned_shadow/1", "error_delta": 0.1}
    _shadow_video(video, [
        json.dumps({"t": 1.0, "side": {"perception/learned/shadow": dict(live)}}),
        json.dumps({"t": 1.5, "side": {"perception/learned/shadow": {**live, "backfill": True}}}),
        json.dumps({"t": 2.0, "side": {"perception/learned/shadow": None}}),
        json.dumps({"t": 2.5, "side": {}}),
    ])
    code, doc = media.run(tmp_path / "raw", video, shrink=False, apply=False,
                          probe=lambda _p: 4, encode=lambda *_a: 1, compact=lambda _s: (False, _s))
    assert code == 0
    row = doc["sessions"][0]
    assert row["sidecar_rows"] == 4
    assert row["shadow_live_rows"] == 1
    assert row["shadow_backfill_rows"] == 1


def test_receipt_shadow_counts_are_null_without_a_sidecar(tmp_path):
    _session(tmp_path)
    video = tmp_path / "video"
    code, doc = media.run(tmp_path / "raw", video, shrink=False, apply=False,
                          probe=lambda _p: 2, encode=lambda *_a: 1, compact=lambda _s: (False, _s))
    assert code == 1
    row = doc["sessions"][0]
    assert row["status"] == "missing"
    assert row["sidecar_rows"] is None
    assert row["shadow_live_rows"] is None
    assert row["shadow_backfill_rows"] is None
