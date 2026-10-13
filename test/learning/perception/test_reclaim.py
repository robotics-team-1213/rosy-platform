from __future__ import annotations

import json
from pathlib import Path

import pytest

import reclaim


STAMP = "20260930T124745Z"
DEVICE = "rosy-pinky-8kcn"
STEM = f"teleop_{DEVICE}_{STAMP}"


def _session(root: Path, nested: bool) -> Path:
    folder = f"{STAMP}_{DEVICE}"
    session = root / "raw" / DEVICE / folder if nested else root / "raw" / folder
    (session / "bag").mkdir(parents=True)
    (session / "bag" / "bag_0.mcap").write_bytes(b"m" * 1000)
    (session / "session.json").write_text(json.dumps({
        "device": DEVICE, "started_at": "2026-09-30T12:47:45+00:00"}), encoding="utf-8")
    return session


def _video(video_dir: Path, frames: int = 4, *, sidecar: int | None = None,
           byte_size: int | None = None, schema: str = "rosy.teleop.video/1") -> None:
    video_dir.mkdir(parents=True, exist_ok=True)
    payload = b"v" * 20
    video = video_dir / f"{STEM}.mp4"
    video.write_bytes(payload)
    lines = frames if sidecar is None else sidecar
    (video_dir / f"{STEM}.jsonl").write_text(("\n".join(["{}"] * lines) + "\n") if lines else "",
                                             encoding="utf-8")
    doc = {"schema": schema, "video": {
        "file": video.name, "frames": frames,
        "bytes": len(payload) if byte_size is None else byte_size}}
    (video_dir / f"{STEM}.json").write_text(json.dumps(doc), encoding="utf-8")


def _probe_ok(_video):
    return 4


def test_both_layouts_are_candidates_and_compact_is_not(tmp_path):
    flat = _session(tmp_path, nested=False)
    nested = _session(tmp_path, nested=True)
    compact = nested.with_name(nested.name + ".compact")
    (compact / "bag").mkdir(parents=True)
    (compact / "session.json").write_text("{}", encoding="utf-8")
    video = tmp_path / "video"
    _video(video)
    rows = reclaim.plan(reclaim.iter_sessions(tmp_path / "raw"), video, _probe_ok)
    assert {Path(row["path"]) for row in rows} == {flat, nested}
    assert {row["status"] for row in rows} == {"ok"}


def test_sidecar_mismatch_is_not_reclaimable(tmp_path):
    _session(tmp_path, nested=False)
    video = tmp_path / "video"
    _video(video, sidecar=3)
    rows = reclaim.plan(reclaim.iter_sessions(tmp_path / "raw"), video, _probe_ok)
    assert rows[0]["status"] == "mismatch"


def test_probe_mismatch_and_probe_error(tmp_path):
    _session(tmp_path, nested=False)
    video = tmp_path / "video"
    _video(video)
    sessions = reclaim.iter_sessions(tmp_path / "raw")
    assert reclaim.plan(sessions, video, lambda _p: 2)[0]["status"] == "mismatch"

    def boom(_path):
        raise RuntimeError("ff")

    assert reclaim.plan(sessions, video, boom)[0]["status"] == "probe_error"


def test_apply_deletes_raw_copies_and_a_verified_videos_compact(tmp_path, capsys):
    flat = _session(tmp_path, nested=False)
    nested = _session(tmp_path, nested=True)
    compact = nested.with_name(nested.name + ".compact")
    (compact / "bag").mkdir(parents=True)
    (compact / "session.json").write_text("{}", encoding="utf-8")
    (video := tmp_path / "video").mkdir()
    _video(video)
    (video / "teleop_201_upright.mp4").write_bytes(b"keep")
    code = reclaim.main(["--root", str(tmp_path), "--video-dir", str(video), "--apply"],
                        probe=_probe_ok)
    assert code == 0
    out = capsys.readouterr().out
    assert not flat.exists() and not nested.exists() and not compact.exists()
    assert (video / f"{STEM}.mp4").is_file()
    assert (video / "teleop_201_upright.mp4").is_file()
    assert "unmatched videos 1" in out
    assert "\napply\n" in out
    assert f"removed {flat.resolve()}" in out
    assert f"removed {nested.resolve()}" in out


def test_dry_run_and_mismatch_do_not_delete(tmp_path, capsys):
    session = _session(tmp_path, nested=False)
    video = tmp_path / "video"
    _video(video, sidecar=1)
    assert reclaim.main(["--root", str(tmp_path), "--video-dir", str(video), "--apply"],
                        probe=_probe_ok) == 0
    assert session.is_dir()
    out = capsys.readouterr().out
    assert "dry-run" not in out
    assert "reclaim 0 sessions" in out
    assert reclaim.main(["--root", str(tmp_path), "--video-dir", str(video)],
                        probe=_probe_ok) == 0
    assert session.is_dir()
    assert "dry-run" in capsys.readouterr().out


def test_make_video_encodes_each_stem_once(tmp_path):
    flat = _session(tmp_path, nested=False)
    _session(tmp_path, nested=True)
    video = tmp_path / "video"
    calls = []

    def encode(session, dest):
        calls.append(session)
        assert dest == video
        _video(dest)
        return 0

    code = reclaim.main(["--root", str(tmp_path), "--video-dir", str(video), "--make-video"],
                        probe=_probe_ok, encode=encode)
    assert code == 0
    assert calls == [flat]
    assert flat.is_dir()


def test_shrink_candidate_is_deleted_and_compact_stays(tmp_path):
    session = _session(tmp_path, nested=False)
    video = tmp_path / "video"
    video.mkdir()

    def compact(src):
        dest = src.with_name(src.name + ".compact")
        dest.mkdir()
        (dest / "session.json").write_text("{}", encoding="utf-8")
        return True, dest

    code = reclaim.main(["--root", str(tmp_path), "--video-dir", str(video), "--shrink", "--apply"],
                        probe=_probe_ok, compact=compact)
    assert code == 0
    assert not session.exists()
    assert (tmp_path / "raw" / f"{STAMP}_{DEVICE}.compact" / "session.json").is_file()


def test_failed_shrink_does_not_delete(tmp_path):
    session = _session(tmp_path, nested=False)
    video = tmp_path / "video"
    video.mkdir()
    code = reclaim.main(["--root", str(tmp_path), "--video-dir", str(video), "--shrink", "--apply"],
                        probe=_probe_ok, compact=lambda _src: (False, _src))
    assert code == 1
    assert session.is_dir()


def test_bad_compact_preflight_deletes_nothing(tmp_path):
    session = _session(tmp_path, nested=False)
    outside = tmp_path / "elsewhere.compact"
    outside.mkdir()
    rows = [{"status": "ok", "path": str(session)}]
    original = reclaim.compact_sibling
    reclaim.compact_sibling = lambda _session: outside
    try:
        with pytest.raises(ValueError):
            reclaim.delete_targets(rows, tmp_path / "raw")
    finally:
        reclaim.compact_sibling = original
    assert session.is_dir()
    assert outside.is_dir()


def test_guard_rejects_raw_root_derivative_and_outside(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    compact = raw / "s.compact"
    compact.mkdir()
    with pytest.raises(ValueError):
        reclaim.guard(raw, raw)
    with pytest.raises(ValueError):
        reclaim.guard(outside, raw)
    with pytest.raises(ValueError):
        reclaim.guard(compact, raw)


def test_preflight_deletes_nothing_when_one_target_is_outside(tmp_path):
    session = _session(tmp_path, nested=False)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    rows = [
        {"status": "ok", "path": str(session)},
        {"status": "ok", "path": str(outside)},
    ]
    with pytest.raises(ValueError):
        reclaim.delete_targets(rows, tmp_path / "raw")
    assert session.is_dir()
