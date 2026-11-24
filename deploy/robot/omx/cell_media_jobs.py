#!/usr/bin/env python3
"""Non-motion media, dataset conversion/transfer, and policy bundle staging jobs for `:8781` (D-1072)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_record_handoff as brh  # noqa: E402
from cell_job_validators import VIEW, _repo_id, resolve_under_workdir  # noqa: E402

MAX_CLIP_BYTES = 16 * 1024 * 1024
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 65_536
MAX_BUNDLE_FILE_BYTES = 256 * 1024 * 1024
MIN_CLIP_S = 1
MAX_CLIP_S = 15
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _build_opener(*, ca_file: Path | None = None):
    handlers: list = [urllib.request.ProxyHandler({}), brh._NoRedirectHandler()]
    ca_raw = ca_file or os.environ.get("ROSY_LEARNING_CA_FILE") or os.environ.get("ROSY_FLEET_CA_FILE")
    if ca_raw:
        ctx = ssl.create_default_context(cafile=str(Path(ca_raw).expanduser()))
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def _read_bounded(resp, limit: int, label: str) -> bytes:
    try:
        data = resp.read(limit + 1)
    except TypeError:
        data = resp.read()
    if len(data) > limit:
        raise ValueError(f"{label} exceeds {limit} bytes")
    return data


def _resolve_target(path: Path | str, workdir: Path | None) -> Path:
    if workdir is not None:
        return resolve_under_workdir(workdir, path if isinstance(path, Path) else str(path))
    raw = path.as_posix() if isinstance(path, Path) else str(path)
    if "\x00" in raw or ".." in Path(raw).parts:
        raise ValueError(f"path traversal forbidden: {raw!r}")
    target = Path(path).expanduser()
    if target.is_symlink():
        raise ValueError(f"symlink path forbidden: {target}")
    return target


def _encode_mp4_cv2(frames_bgr: list, out_mp4: Path, fps: int) -> None:
    import cv2

    h, w = frames_bgr[0].shape[:2]
    writer = cv2.VideoWriter(str(out_mp4), cv2.VideoWriter_fourcc(*"mp4v"), float(fps), (w, h))
    try:
        if not writer.isOpened():
            raise RuntimeError("cv2.VideoWriter could not open output MP4")
        for img in frames_bgr:
            if img.shape[:2] != (h, w):
                img = cv2.resize(img, (w, h))
            writer.write(img)
    finally:
        writer.release()


def _encode_mp4_ffmpeg(jpg_dir: Path, out_mp4: Path, fps: int) -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(jpg_dir / "%05d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_mp4)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return res.returncode == 0 and out_mp4.is_file() and out_mp4.stat().st_size > 0


def capture_clip(view: str, duration_s: int, out_dir: Path, *, fps: int = 10, viewer_url: str | None = None, urlopen_fn=None, sleep_fn=time.sleep, workdir: Path | None = None, ca_file: Path | None = None) -> dict:
    """Record a bounded 1..15s MP4 (<= 16 MiB) from `:8767` MJPEG viewer without holding arm or D435 locks."""
    if not isinstance(view, str) or not VIEW.fullmatch(view):
        raise ValueError(f"invalid camera view {view!r}")
    if isinstance(duration_s, bool) or not isinstance(duration_s, int) or not MIN_CLIP_S <= duration_s <= MAX_CLIP_S:
        raise ValueError(f"duration_s must be in {MIN_CLIP_S}..{MAX_CLIP_S}")
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 30:
        raise ValueError("fps must be in 1..30")
    viewer = brh._validate_url(viewer_url or os.environ.get("ROSY_CAMERA_VIEWER_URL") or "http://127.0.0.1:8767")
    open_fn = urlopen_fn or _build_opener(ca_file=ca_file).open
    import cv2
    import numpy as np

    target_frames = max(1, duration_s * fps)
    raw_frames: list[bytes] = []
    bgr_frames: list = []
    seqs: list[int] = []
    period = 1.0 / fps
    for idx in range(target_frames):
        t0 = time.monotonic()
        with open_fn(f"{viewer}/frame/{view}.jpg", timeout=5) as resp:
            if getattr(resp, "status", 200) != 200:
                raise RuntimeError(f"viewer returned HTTP {resp.status}")
            raw = _read_bounded(resp, MAX_FRAME_BYTES, f"frame/{view}.jpg")
            seq = resp.headers.get("X-Frame-Seq") if hasattr(resp, "headers") else None
            if isinstance(seq, str) and seq.isdigit():
                seqs.append(int(seq))
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("viewer frame is not a valid JPEG")
        raw_frames.append(raw)
        bgr_frames.append(img)
        if idx + 1 < target_frames:
            sleep_fn(max(0.0, period - (time.monotonic() - t0)))

    out_dir = _resolve_target(out_dir, workdir)
    if out_dir.is_symlink():
        raise ValueError("out_dir cannot be a symlink")
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_dir.is_symlink():
        raise ValueError("out_dir cannot be a symlink")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_mp4 = out_dir / f"{stamp}-{view}.mp4"
    tmp_jpg = out_dir / f".clip-jpg-{uuid.uuid4().hex[:12]}"
    tmp_jpg.mkdir(parents=False, exist_ok=False)
    try:
        for i, raw in enumerate(raw_frames):
            (tmp_jpg / f"{i:05d}.jpg").write_bytes(raw)
        if not _encode_mp4_ffmpeg(tmp_jpg, out_mp4, fps):
            _encode_mp4_cv2(bgr_frames, out_mp4, fps)
    finally:
        shutil.rmtree(tmp_jpg, ignore_errors=True)
    size = out_mp4.stat().st_size if out_mp4.is_file() else 0
    if size <= 0 or size > MAX_CLIP_BYTES:
        out_mp4.unlink(missing_ok=True)
        raise ValueError(f"clip size {size} invalid or exceeds {MAX_CLIP_BYTES} bytes")
    sha = brh._sha256_file(out_mp4)
    receipt = {
        "schema": "rosy.cell-clip.v1", "ok": True, "view": view, "duration_s": duration_s,
        "fps": fps, "frames": len(bgr_frames), "bytes": size, "sha256": sha,
        "file": str(out_mp4), "source_seqs": seqs[:200],
    }
    out_mp4.with_suffix(".json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def convert_episodes(episodes: Path, out_root: Path, repo_id: str, *, fps: int = 30, images: str = "top=top,front=front", outcome: str = "success", workdir: Path | None = None) -> dict:
    """Convert raw recorded episodes to LeRobot format, refusing any DO_NOT_TRAIN or symlinked source."""
    repo_id = _repo_id(repo_id)
    episodes = _resolve_target(episodes, workdir)
    out_root = _resolve_target(out_root, workdir)
    if out_root.is_symlink():
        raise ValueError("out_root cannot be a symlink")
    if episodes.is_symlink() or not episodes.is_dir():
        raise ValueError(f"episodes directory not found: {episodes}")
    base_res = episodes.resolve()
    if any(p.name == "DO_NOT_TRAIN.txt" for p in episodes.rglob("*")):
        raise ValueError("DO_NOT_TRAIN blocked episode conversion")
    for p in episodes.rglob("*"):
        if p.is_symlink() or not p.resolve().is_relative_to(base_res):
            raise ValueError(f"symlinks or traversal forbidden in episodes: {p.name}")
    image_map = dict(pair.split("=", 1) for pair in images.split(",") if "=" in pair)
    if not image_map:
        raise ValueError("images mapping required")
    import episode_recorder

    count = episode_recorder.convert(episodes, out_root, repo_id, fps, image_map, outcome)
    return {"schema": "rosy.cell-episodes-converted.v1", "ok": True, "episodes": count, "root": str(out_root), "repo_id": repo_id, "outcome": outcome}


def transfer_dataset(collection: str, *, prep_dir: Path = Path("."), collections_root: Path | None = None, push_fn=brh.push_collection_to_model, intake_fn=brh.notify_canonical_intake) -> dict:
    """Verify CLOSED hardware collection (blocking DO_NOT_TRAIN), push to model PC, and notify intake."""
    if not _SAFE_NAME.fullmatch(collection):
        raise ValueError(f"invalid collection name {collection!r}")
    prep = Path(prep_dir).expanduser()
    if prep.is_symlink():
        raise ValueError("prep_dir cannot be a symlink")
    root = Path(collections_root).expanduser() if collections_root is not None else brh.collections_root()
    col_dir = root / collection
    ver = brh.verify_sealed_collection(col_dir)
    cfg = brh.load_handoff_config(prep)
    tr = push_fn(col_dir, cfg, verified=ver)
    if not tr.get("ok"):
        return {"ok": False, "collection": collection, "error": tr.get("error") or "transfer failed", "transfer": tr}
    intake = intake_fn(cfg, tr) if cfg.get("intake_url") else {"status": "skipped", "ok": True}
    if not intake.get("ok"):
        return {"ok": False, "collection": collection, "error": intake.get("error") or "intake failed", "transfer": tr, "intake": intake}
    return {"schema": "rosy.cell-dataset-transfer.v1", "ok": True, "collection": collection, "manifest_sha256": ver["manifest_sha256"], "total_episodes": ver["total_episodes"], "transfer": tr, "intake": intake}


def _parse_manifest_files(manifest: object) -> list[tuple[str, str, int | None]]:
    raw_files = manifest.get("files") if isinstance(manifest, dict) else None
    if isinstance(raw_files, list) and raw_files:
        pairs = []
        for item in raw_files:
            if not isinstance(item, dict):
                raise ValueError("invalid manifest entry object")
            size = item.get("bytes")
            if size is not None and (isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_BUNDLE_FILE_BYTES):
                raise ValueError(f"invalid manifest bytes for {item.get('path')!r}")
            pairs.append((item.get("path"), item.get("sha256"), size))
    elif isinstance(raw_files, dict) and raw_files:
        pairs = [(k, v, None) for k, v in raw_files.items()]
    else:
        raise ValueError("bundle-manifest files list is empty")
    entries: list[tuple[str, str, int | None]] = []
    seen: set[str] = set()
    for rel, sha, size in pairs:
        if (not isinstance(rel, str) or not rel or rel == "bundle-manifest.json" or "\x00" in rel or "\\" in rel
                or rel.startswith(("/", "-")) or any(p in ("", ".", "..") for p in Path(rel).parts)):
            raise ValueError(f"invalid manifest entry path: {rel!r}")
        if rel in seen:
            raise ValueError(f"duplicate manifest entry: {rel!r}")
        if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
            raise ValueError(f"invalid manifest sha256 for {rel!r}")
        seen.add(rel)
        entries.append((rel, sha, size))
    return entries


def _verify_staged_dir(final: Path, mf_sha: str, entries: list[tuple[str, str, int | None]]) -> None:
    if final.is_symlink() or not final.is_dir():
        raise ValueError(f"target {final} exists and is not a real directory")
    mf_local = final / "bundle-manifest.json"
    if mf_local.is_symlink() or not mf_local.is_file() or brh._sha256_file(mf_local) != mf_sha:
        raise ValueError(f"target {final} already exists with different bundle manifest")
    final_res = final.resolve()
    for rel, expected_sha, expected_bytes in entries:
        cur = final
        for part in Path(rel).parts:
            cur = cur / part
            if cur.is_symlink():
                raise ValueError(f"symlink inside staged bundle: {rel}")
        if not cur.is_file() or not cur.resolve().is_relative_to(final_res):
            raise ValueError(f"staged bundle file missing: {rel}")
        if expected_bytes is not None and cur.stat().st_size != expected_bytes:
            raise ValueError(f"staged file byte size mismatch for {rel}")
        if brh._sha256_file(cur) != expected_sha:
            raise ValueError(f"staged file SHA-256 mismatch for {rel}")


def stage_policy_bundle(run_id: str, target_dir: Path, *, learning_url: str | None = None, token_file: Path | None = None, expected_manifest_sha256: str | None = None, opener=None, workdir: Path | None = None, ca_file: Path | None = None) -> dict:
    """Download `:8768` canonical run bundle, verify manifest & file SHA-256s, and atomically stage to target_dir."""
    if not _SAFE_NAME.fullmatch(run_id):
        raise ValueError(f"invalid run_id {run_id!r}")
    base_url = brh._validate_url(learning_url or os.environ.get("ROSY_LEARNING_URL") or "")
    if not base_url:
        raise ValueError("learning_url (or ROSY_LEARNING_URL) is required")
    headers: dict[str, str] = {}
    tok_raw = str(token_file or os.environ.get("ROSY_LEARNING_TOKEN_FILE") or "").strip()
    if tok_raw:
        headers["Authorization"] = f"Bearer {brh._read_bearer_token(Path(tok_raw).expanduser())}"
    open_fn = opener or _build_opener(ca_file=ca_file).open

    def _get(rel: str, limit: int) -> bytes:
        req = urllib.request.Request(f"{base_url}{rel}", headers=headers, method="GET")
        with open_fn(req, timeout=15) as resp:
            if getattr(resp, "status", 200) != 200:
                raise RuntimeError(f"HTTP {resp.status} for {rel}")
            return _read_bounded(resp, limit, rel)

    raw_mf = _get(f"/api/learning/canonical/runs/{urllib.parse.quote(run_id, safe='')}/bundle-manifest", MAX_MANIFEST_BYTES)
    mf_sha = hashlib.sha256(raw_mf).hexdigest()
    if expected_manifest_sha256 and mf_sha != expected_manifest_sha256:
        raise ValueError("bundle-manifest SHA-256 mismatch")
    entries = _parse_manifest_files(json.loads(raw_mf.decode("utf-8")))

    target_dir = _resolve_target(target_dir, workdir)
    if target_dir.is_symlink():
        raise ValueError("target_dir cannot be a symlink")
    target_dir.mkdir(parents=True, exist_ok=True)
    if target_dir.is_symlink():
        raise ValueError("target_dir cannot be a symlink")
    final = target_dir / run_id
    if final.is_symlink():
        raise ValueError("target staging path cannot be a symlink")
    if final.exists():
        _verify_staged_dir(final, mf_sha, entries)
        return {"schema": "rosy.cell-policy-stage.v1", "ok": True, "run_id": run_id, "staged_dir": str(final), "manifest_sha256": mf_sha, "file_count": len(entries), "already_staged": True}

    staging = target_dir / f".staging-{run_id}-{uuid.uuid4().hex[:12]}"
    staging.mkdir(parents=False, exist_ok=False)
    staging_res = staging.resolve()
    try:
        for rel, expected_sha, expected_bytes in entries:
            dest = (staging / rel).resolve()
            if not dest.is_relative_to(staging_res):
                raise ValueError(f"path traversal blocked: {rel!r}")
            data = _get(f"/api/learning/canonical/runs/{urllib.parse.quote(run_id, safe='')}/file/{urllib.parse.quote(rel, safe='/')}", MAX_BUNDLE_FILE_BYTES)
            if expected_bytes is not None and len(data) != expected_bytes:
                raise ValueError(f"file byte size mismatch for {rel}")
            if hashlib.sha256(data).hexdigest() != expected_sha:
                raise ValueError(f"file SHA-256 mismatch for {rel}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        with (staging / "bundle-manifest.json").open("wb") as fh:
            fh.write(raw_mf)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"schema": "rosy.cell-policy-stage.v1", "ok": True, "run_id": run_id, "staged_dir": str(final), "manifest_sha256": mf_sha, "file_count": len(entries)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workdir", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture-clip")
    c.add_argument("--view", required=True)
    c.add_argument("--duration-s", type=int, required=True)
    c.add_argument("--out-dir", type=Path, default=Path("clips"))
    c.add_argument("--fps", type=int, default=10)
    c.add_argument("--viewer")
    e = sub.add_parser("convert-episodes")
    e.add_argument("--episodes", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--repo-id", required=True)
    e.add_argument("--fps", type=int, default=30)
    e.add_argument("--images", default="top=top,front=front")
    e.add_argument("--outcome", default="success")
    t = sub.add_parser("transfer-dataset")
    t.add_argument("--collection", required=True)
    t.add_argument("--collections-root", type=Path)
    s = sub.add_parser("stage-policy-bundle")
    s.add_argument("--run-id", required=True)
    s.add_argument("--target-dir", type=Path, required=True)
    s.add_argument("--learning-url")
    s.add_argument("--token-file", type=Path)
    s.add_argument("--expected-manifest-sha256")
    args = ap.parse_args(argv)
    wd = Path(args.workdir).expanduser() if args.workdir is not None else Path.cwd()
    try:
        if args.cmd == "capture-clip":
            out = capture_clip(args.view, args.duration_s, args.out_dir, fps=args.fps, viewer_url=args.viewer, workdir=wd)
        elif args.cmd == "convert-episodes":
            out = convert_episodes(args.episodes, args.out, args.repo_id, fps=args.fps, images=args.images, outcome=args.outcome, workdir=wd)
        elif args.cmd == "transfer-dataset":
            out = transfer_dataset(args.collection, prep_dir=wd, collections_root=args.collections_root)
        else:
            out = stage_policy_bundle(args.run_id, args.target_dir, learning_url=args.learning_url, token_file=args.token_file, expected_manifest_sha256=args.expected_manifest_sha256, workdir=wd)
        print(json.dumps(out))
        return 0 if out.get("ok") else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
