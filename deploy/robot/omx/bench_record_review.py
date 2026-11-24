#!/usr/bin/env python3
"""Per-episode evaluation (good/bad/retry/notes), DO_NOT_TRAIN gate, MP4 clip lookup, and episode deletion."""
from __future__ import annotations

import json, os, re, shutil, time
from pathlib import Path

from bench_record_handoff import atomic_write_json, collections_root, load_json_value
from bench_record_inspect import ARMS

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_SAFE_CAM = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_RATINGS = ("good", "bad", "retry", "unrated")
_PRUNE_SCRIPT = """import json, os, sys
from pathlib import Path
from lerobot.datasets import dataset_tools, lerobot_dataset
src, out_dir, repo_id, indices = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], json.loads(sys.argv[4])
os.environ.setdefault("HF_HUB_OFFLINE", "1")
ds = lerobot_dataset.LeRobotDataset(repo_id=repo_id, root=src, download_videos=False)
dataset_tools.delete_episodes(ds, episode_indices=indices, output_dir=out_dir, repo_id=repo_id)
"""


def _parse_int_list(raw):
    if not isinstance(raw, list) or not raw:
        raise ValueError("삭제할 에피소드 번호 목록이 필요합니다")
    out = []
    for x in raw:
        if isinstance(x, bool) or not isinstance(x, int) or x < 0:
            raise ValueError("에피소드 번호는 0 이상의 정수여야 합니다")
        if x not in out:
            out.append(x)
    return sorted(out)


def _read_episode_rows(ds_folder: Path, fps: float, total_eps: int):
    ep_files = sorted((ds_folder / "meta" / "episodes").rglob("*.parquet"))
    rows_by_idx, cams = {}, set()
    if ep_files:
        try:
            import pandas as pd
            df = pd.concat([pd.read_parquet(f) for f in ep_files]).sort_values("episode_index")
            for _, r in df.iterrows():
                idx = int(r["episode_index"])
                length = int(r["length"]) if "length" in r else 0
                raw_tasks = r["tasks"] if "tasks" in r else []
                task_txt = str(raw_tasks[0]) if hasattr(raw_tasks, "__len__") and not isinstance(raw_tasks, str) and len(raw_tasks) else str(raw_tasks or "")
                vids = {}
                for col in df.columns:
                    if col.startswith("videos/") and col.endswith("/chunk_index"):
                        key = col[len("videos/"):-len("/chunk_index")]
                        cam = key.removeprefix("observation.images.")
                        cams.add(cam)
                        vids[cam] = {
                            "chunk": int(r[f"videos/{key}/chunk_index"]),
                            "file": int(r[f"videos/{key}/file_index"]),
                            "from_s": round(float(r[f"videos/{key}/from_timestamp"]), 2),
                            "to_s": round(float(r[f"videos/{key}/to_timestamp"]), 2),
                        }
                rows_by_idx[idx] = {"index": idx, "length": length, "duration_s": round(length / max(fps, 1.0), 1), "task": task_txt, "videos": vids}
        except Exception:
            rows_by_idx = {}
    if not rows_by_idx and total_eps > 0:
        for i in range(total_eps):
            rows_by_idx[i] = {"index": i, "length": 0, "duration_s": None, "task": "", "videos": {}}
    return rows_by_idx, sorted(cams)


class BenchReviewMixin:
    def _review_root(self) -> Path:
        return self.prep / ".episode-reviews"

    def _review_path(self, ds_name: str) -> Path:
        return self._review_root() / f"{ds_name}.json"

    def _ds_dir(self, ds_name: str) -> Path:
        clean = Path(str(ds_name or "").strip()).name
        if not clean or clean != str(ds_name or "").strip() or not _SAFE_NAME.fullmatch(clean):
            raise ValueError("올바른 데이터셋 이름이 필요합니다")
        ds_folder = Path.home() / "rosy-data" / "omx-leader" / clean
        if not ds_folder.is_dir() or ds_folder.is_symlink():
            raise ValueError(f"데이터셋을 찾을 수 없습니다: {clean}")
        return ds_folder

    def _load_reviews(self, ds_name: str) -> dict:
        doc = load_json_value(self._review_path(ds_name), {})
        eps = doc.get("episodes") if isinstance(doc, dict) and isinstance(doc.get("episodes"), dict) else {}
        return {"schema": "rosy.omx-episode-reviews.v1", "episodes": eps}

    def dataset_review_summary(self, ds_name: str) -> dict:
        eps = self._load_reviews(ds_name).get("episodes", {})
        counts = {"good": 0, "bad": 0, "retry": 0, "unrated": 0}
        for row in eps.values():
            r = str((row or {}).get("rating") or "unrated")
            if r in counts:
                counts[r] += 1
        return counts

    def dataset_episodes(self, ds_name: str) -> dict:
        ds_folder = self._ds_dir(ds_name)
        info = load_json_value(ds_folder / "meta" / "info.json", {})
        if not isinstance(info, dict):
            info = {}
        fps = float(info.get("fps") or 30.0)
        parquets = len(list(ds_folder.glob("data/**/*.parquet")))
        te = info.get("total_episodes")
        total_eps = int(te) if (type(te) is int and te >= 0) else parquets
        rows_by_idx, cams = _read_episode_rows(ds_folder, fps, total_eps)
        if not cams and (ds_folder / "videos").is_dir():
            cams = sorted(p.name.removeprefix("observation.images.") for p in (ds_folder / "videos").iterdir() if p.is_dir())
        static_set = set()
        st_doc = load_json_value(ds_folder / "static_episodes.json", {})
        raw_static = []
        if isinstance(st_doc, dict):
            for key in ("static", "static_episodes", "episodes"):
                val = st_doc.get(key)
                if isinstance(val, (list, tuple)):
                    raw_static = val
                    break
        for entry in raw_static:
            if isinstance(entry, int) and not isinstance(entry, bool):
                static_set.add(entry)
            elif isinstance(entry, dict) and isinstance(entry.get("episode_index"), int):
                static_set.add(entry["episode_index"])
        rev_eps = self._load_reviews(ds_folder.name).get("episodes", {})
        out_rows = []
        summary = {"good": 0, "bad": 0, "retry": 0, "unrated": 0}
        for idx in sorted(rows_by_idx):
            row = dict(rows_by_idx[idx])
            rv = rev_eps.get(str(idx)) or {}
            rating = str(rv.get("rating") or "unrated")
            if rating not in _RATINGS:
                rating = "unrated"
            summary[rating] += 1
            row["rating"] = rating
            row["note"] = str(rv.get("note") or "")
            row["updated_at"] = str(rv.get("updated_at") or "")
            row["static"] = idx in static_set
            out_rows.append(row)
        rc = load_json_value(self.prep / ".hf-receipts" / f"{ds_folder.name}.json", {})
        dnt_p = ds_folder / "DO_NOT_TRAIN.txt"
        return {
            "dataset": ds_folder.name,
            "fps": fps,
            "total_episodes": len(out_rows),
            "total_frames": int(info.get("total_frames") or sum(r.get("length") or 0 for r in out_rows)),
            "cameras": cams,
            "episodes": out_rows,
            "summary": summary,
            "do_not_train": dnt_p.is_file(),
            "do_not_train_text": dnt_p.read_text(encoding="utf-8", errors="replace").strip()[:200] if dnt_p.is_file() else "",
            "hf_uploaded": bool(isinstance(rc, dict) and rc.get("repo_id")),
            "sealed": (collections_root() / ds_folder.name / "manifest.json").is_file(),
        }

    def rate_episode(self, body: dict) -> dict:
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        ds_folder = self._ds_dir(body.get("dataset") or "")
        ep = body.get("episode")
        if isinstance(ep, bool) or not isinstance(ep, int) or ep < 0:
            raise ValueError("episode는 0 이상의 정수여야 합니다")
        rating = str(body.get("rating") or "unrated").strip()
        if rating not in _RATINGS:
            raise ValueError("rating은 good, bad, retry, unrated 중 하나여야 합니다")
        note = str(body.get("note") or "").strip()[:200]
        doc = self._load_reviews(ds_folder.name)
        if rating == "unrated" and not note:
            doc["episodes"].pop(str(ep), None)
        else:
            doc["episodes"][str(ep)] = {"rating": rating, "note": note, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        atomic_write_json(self._review_path(ds_folder.name), doc)
        if hasattr(self, "_log_event"):
            self._log_event("review", "warn" if rating == "bad" else "info", f"{ds_folder.name} ep#{ep} 평가={rating}" + (f" ({note})" if note else ""))
        return self.dataset_episodes(ds_folder.name)

    def set_dataset_do_not_train(self, body: dict) -> dict:
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        ds_folder = self._ds_dir(body.get("dataset") or "")
        with self.lock:
            if self.state.get("status") in ("handing_over", "homing", "recording", "restoring", "sealing"):
                raise ValueError("녹화/봉인 중에는 학습 제외 상태를 변경할 수 없습니다")
        dnt = bool(body.get("do_not_train"))
        dnt_p = ds_folder / "DO_NOT_TRAIN.txt"
        reason = str(body.get("reason") or "operator_marked_bad").strip()[:160]
        if dnt:
            dnt_p.write_text(f"# bench-review\nreason: {reason}\nts: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n", encoding="utf-8")
        elif dnt_p.is_file():
            txt = dnt_p.read_text(encoding="utf-8", errors="replace")
            if not txt.startswith("# bench-review") and body.get("force") is not True:
                raise ValueError("하드웨어 가드/중단으로 표시된 DO_NOT_TRAIN은 임의로 해제할 수 없습니다")
            dnt_p.unlink(missing_ok=True)
        if hasattr(self, "_log_event"):
            self._log_event("review", "warn" if dnt else "good", f"{ds_folder.name} 학습제외={'ON' if dnt else 'OFF'}")
        return {"ok": True, "dataset": ds_folder.name, "do_not_train": dnt_p.is_file(), "lerobot_datasets": self.lerobot_datasets()}

    def trash_dataset_dir(self, ds_folder: Path, reason: str = "discard") -> Path:
        trash_root = ds_folder.parent / ".trash"
        trash_root.mkdir(parents=True, exist_ok=True)
        dest = trash_root / f"{ds_folder.name}-{reason}-{time.strftime('%Y%m%d-%H%M%S')}"
        n = 1
        while dest.exists():
            dest = trash_root / f"{ds_folder.name}-{reason}-{time.strftime('%Y%m%d-%H%M%S')}-{n}"
            n += 1
        shutil.move(str(ds_folder), str(dest))
        return dest

    def _prune_lerobot_episodes(self, ds_folder: Path, indices: list[int], staging: Path, repo_id: str) -> None:
        import subprocess
        env = dict(os.environ, HF_HUB_OFFLINE="1")
        res = subprocess.run(
            [self.python, "-c", _PRUNE_SCRIPT, str(ds_folder), str(staging), repo_id, json.dumps(indices)],
            cwd=self.prep, env=env, capture_output=True, text=True, timeout=180,
        )
        if res.returncode != 0:
            detail = (res.stderr or res.stdout or "").strip()[-240:]
            raise ValueError(f"에피소드 재인덱싱 실패: {detail}")

    def delete_dataset_episodes(self, body: dict) -> dict:
        if not isinstance(body, dict) or body.get("confirm") is not True:
            raise ValueError("에피소드 삭제 확인(confirm=true)이 필요합니다")
        ds_folder = self._ds_dir(body.get("dataset") or "")
        indices = _parse_int_list(body.get("episodes"))
        with self.lock:
            if self.state.get("status") in ("handing_over", "homing", "recording", "restoring", "sealing"):
                raise ValueError("녹화/봉인 중에는 에피소드를 삭제할 수 없습니다")
        if hasattr(self, "hf_upload_status") and self.hf_upload_status().get("state") in ("encoding", "uploading"):
            raise ValueError("HF 업로드 중에는 에피소드를 삭제할 수 없습니다")
        cur = self.dataset_episodes(ds_folder.name)
        existing = {r["index"] for r in cur["episodes"]}
        missing = [i for i in indices if i not in existing]
        if missing:
            raise ValueError(f"존재하지 않는 에피소드 번호입니다: {missing}")
        if len(indices) >= len(existing):
            self.trash_dataset_dir(ds_folder, "all-deleted")
            self._review_path(ds_folder.name).unlink(missing_ok=True)
            if hasattr(self, "_log_event"):
                self._log_event("review", "warn", f"{ds_folder.name} 전체 에피소드({len(indices)}개) 삭제로 .trash 이동")
            return {"ok": True, "dataset": ds_folder.name, "deleted_all": True, "deleted_episodes": indices, "lerobot_datasets": self.lerobot_datasets()}

        staging = ds_folder.parent / f".pruning-{ds_folder.name}-{os.getpid()}"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        try:
            self._prune_lerobot_episodes(ds_folder, indices, staging, f"local/{ds_folder.name}")
            new_info = load_json_value(staging / "meta" / "info.json", {})
            want_eps = len(existing) - len(indices)
            if not isinstance(new_info, dict) or new_info.get("total_episodes") != want_eps or not list(staging.glob("data/**/*.parquet")):
                raise ValueError(f"에피소드 삭제 후 데이터셋 검증 실패 (기대 {want_eps}회, 실제 {new_info.get('total_episodes') if isinstance(new_info, dict) else '?'})")
            self.trash_dataset_dir(ds_folder, f"before-del-{len(indices)}ep")
            os.replace(staging, ds_folder)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        kept = [i for i in sorted(existing) if i not in set(indices)]
        old_rev = self._load_reviews(ds_folder.name).get("episodes", {})
        new_rev = {str(new_i): old_rev[str(old_i)] for new_i, old_i in enumerate(kept) if str(old_i) in old_rev}
        atomic_write_json(self._review_path(ds_folder.name), {"schema": "rosy.omx-episode-reviews.v1", "episodes": new_rev})
        if hasattr(self, "_log_event"):
            self._log_event("review", "warn", f"{ds_folder.name} 에피소드 {indices} 삭제 완료 (잔여 {want_eps}회)")
        return {"ok": True, "dataset": ds_folder.name, "deleted_episodes": indices, "remaining_episodes": want_eps, "episodes_info": self.dataset_episodes(ds_folder.name), "lerobot_datasets": self.lerobot_datasets()}

    def resolve_dataset_video(self, ds_name: str, cam: str, chunk: int = 0, file_idx: int = 0) -> Path:
        ds_folder = self._ds_dir(ds_name)
        clean_cam = str(cam or "").strip()
        if not _SAFE_CAM.fullmatch(clean_cam):
            raise ValueError("올바른 카메라 이름이 필요합니다")
        if chunk < 0 or file_idx < 0:
            raise ValueError("잘못된 영상 chunk/file 번호입니다")
        vdir = ds_folder / "videos"
        cand = vdir / (clean_cam if clean_cam.startswith("observation.images.") else f"observation.images.{clean_cam}") / f"chunk-{chunk:03d}" / f"file-{file_idx:03d}.mp4"
        if not cand.is_file() or cand.is_symlink() or not cand.resolve().is_relative_to(ds_folder.resolve()):
            raise ValueError("요청한 에피소드 영상을 찾을 수 없습니다")
        return cand

