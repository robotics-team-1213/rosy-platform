#!/usr/bin/env python3
"""Honest server-driven Sim -> Collect -> Seal -> Model-PC Transfer -> Canonical Intake pipeline mixin."""
from __future__ import annotations

import json, re, shutil, threading, time
from pathlib import Path

from bench_record_guard import hold_other_arm_locks
from bench_record_handoff import (
    collections_root,
    load_handoff_config,
    load_handoff_queue,
    notify_canonical_intake,
    push_collection_to_model,
    record_queue_status,
    save_handoff_config,
    validate_team_hf_upload,
    verify_sealed_collection,
)
from bench_record_inspect import ARMS
from bench_record_replay import build_ik_replay, transform_replay, validate_replay_payload

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_SAFE_ARM = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_SOURCE_TYPES = ("isaac_sim", "policy_ckpt", "teacher_traj", "ik_planner")


class BenchPipelineMixin:
    def _pipe_init(self):
        cfg = load_handoff_config(self.prep)
        queue = load_handoff_queue(self.prep)
        with self.lock:
            if not hasattr(self, "_pipe_lock"):
                self._pipe_lock = threading.Lock()
                self._pipe_state = {
                    "state": "idle",
                    "stages": {"sim": "idle", "collect": "idle", "seal": "idle", "transfer": "idle", "intake": "idle"},
                    "loop_count": 0,
                    "auto_loop": bool(cfg["auto_loop"]),
                    "model_target": cfg["model_target"],
                    "intake_url": cfg["intake_url"],
                    "last_dataset": "",
                    "manifest_sha256": "",
                    "remote_path": "",
                    "intake_job_id": "",
                    "blocked_reason": "",
                    "error": "",
                    "pending_queue": queue,
                    "logs": [],
                }

    def pipeline_status(self):
        self._pipe_init()
        cfg = load_handoff_config(self.prep)
        queue = load_handoff_queue(self.prep)
        with self._pipe_lock:
            snap = json.loads(json.dumps(self._pipe_state))
        snap["auto_loop"] = bool(cfg["auto_loop"])
        snap["model_target"] = cfg["model_target"]
        snap["intake_url"] = cfg["intake_url"]
        snap["pending_queue"] = queue
        return snap

    def pipeline_config(self, body):
        self._pipe_init()
        self._hf_init()
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        cfg = save_handoff_config(self.prep, body)
        with self._pipe_lock:
            self._pipe_state["auto_loop"] = bool(cfg["auto_loop"])
            self._pipe_state["model_target"] = cfg["model_target"]
            self._pipe_state["intake_url"] = cfg["intake_url"]
        with self._hf_lock:
            self._hf_state["auto_upload"] = bool(cfg["auto_hf_upload"])
        return self.pipeline_status()

    def pipeline_generate_replay(self, body):
        self._pipe_init()
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        src_type = str(body.get("source_type") or "isaac_sim")
        if src_type not in _SOURCE_TYPES:
            raise ValueError("source_type은 isaac_sim, policy_ckpt, teacher_traj, ik_planner 중 하나여야 합니다")
        src_ref = str(body.get("source_ref") or "").strip()
        if src_ref and (".." in src_ref or src_ref.startswith("/")):
            raise ValueError("잘못된 source_ref 경로입니다")
        arm = str(body.get("arm") or "arm_a").strip()
        if not _SAFE_ARM.fullmatch(arm) or arm == "arm_ab":
            raise ValueError("단일 팔(arm_a, arm_b, arm_s)만 replay 궤적을 생성할 수 있습니다")
        rdir = self.prep / "replays"
        rdir.mkdir(parents=True, exist_ok=True)
        existing = sorted(rdir.glob("*.json"))
        base_traj = None
        if src_type == "ik_planner":
            origin = str(body.get("origin") or "belt-in").strip()
            target_slot = str(body.get("target_slot") or "pinky").strip()
            hold = lambda: hold_other_arm_locks(arm, ARMS, self.procs, self.mounts, own=True)  # noqa: E731
            base_traj = build_ik_replay(self.prep, arm, origin=origin, target_slot=target_slot, python_exe=getattr(self, "python", None), hold=hold)
        elif src_ref.startswith("replays/"):
            cand = self.prep / src_ref
            if not cand.is_file():
                raise ValueError(f"요청한 replay 파일을 찾을 수 없습니다: {src_ref}")
            base_traj = json.loads(cand.read_text(encoding="utf-8"))
        elif src_ref:
            cand = rdir / f"{Path(src_ref).stem}.json"
            if cand.is_file():
                base_traj = json.loads(cand.read_text(encoding="utf-8"))
        if base_traj is None and existing:
            base_traj = json.loads(existing[0].read_text(encoding="utf-8"))
        if base_traj is None:
            base_traj = {
                "schema": "rosy.omx-replay-trajectory.v1",
                "fps": 30,
                "names": ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos", "gripper.pos"],
                "frames": [[0.0, -20.0, 20.0, 0.0, 0.0, 50.0]] * 30,
                "segments": {"A": [0, 14], "reset": [14, 16], "B": [16, 30]},
            }
        validate_replay_payload(base_traj)
        base_traj["source"] = {"kind": src_type, "ref": src_ref or "default", "arm": arm, "ts": int(self.clock())}
        raw = json.dumps(base_traj, ensure_ascii=False).encode("utf-8")
        mode = str(body.get("replay_mode") or "none")
        raw = transform_replay(raw, mode=mode, invert_gripper=bool(body.get("invert_gripper")))
        out_name = f"pipe-{src_type.replace('_', '-')}-{arm}.json"
        (rdir / out_name).write_bytes(raw)
        replay_id = f"replays/{out_name}"
        with self._pipe_lock:
            self._pipe_state["stages"]["sim"] = "done"
            self._pipe_state["logs"] = (self._pipe_state["logs"] + [f"[sim] {src_type} -> {replay_id} ({len(base_traj.get('frames', []))} frames)"])[-15:]
            snap = json.loads(json.dumps(self._pipe_state))
        return {"ok": True, "replay_id": replay_id, "summary": f"{src_type} 궤적 준비 완료 ({len(base_traj.get('frames', []))}프레임)", "pipeline": snap}

    def _on_session_sealed(self, folder):
        """Server-side post-seal auto handoff (isolated so failures never affect homing/seal state)."""
        try:
            self._pipe_init()
            self._hf_init()
            with self.lock:
                ds_name = str(self.state.get("name") or Path(folder).name)
            cfg = load_handoff_config(self.prep)
            col_dir = collections_root() / ds_name
            if not (col_dir / "manifest.json").is_file():
                return
            if cfg.get("auto_loop"):
                try:
                    self.pipeline_run({"dataset_folder": ds_name, "trigger": "auto_after_seal"})
                except Exception as exc:
                    with self._pipe_lock:
                        self._pipe_state["logs"] = (self._pipe_state["logs"] + [f"[auto-seal:pipe] {exc}"])[-15:]
            if cfg.get("auto_hf_upload") and (not hasattr(self, "hf_logged_in") or self.hf_logged_in()):
                try:
                    self.hf_upload_start({"dataset": ds_name})
                except Exception as exc:
                    with self._pipe_lock:
                        self._pipe_state["logs"] = (self._pipe_state["logs"] + [f"[auto-seal:hf] {exc}"])[-15:]
        except Exception:
            pass

    def _run_pipeline_worker(self, ds_name):
        def log(msg):
            with self._pipe_lock:
                self._pipe_state["logs"] = (self._pipe_state["logs"] + [msg])[-15:]

        def fail_stage(stage, msg):
            record_queue_status(self.prep, ds_name, status=f"{stage}_failed", error=msg)
            with self._pipe_lock:
                self._pipe_state["state"] = "failed"
                self._pipe_state["stages"][stage] = "failed"
                self._pipe_state["error"] = msg
            log(f"[{stage}:failed] {msg}")

        cfg = load_handoff_config(self.prep)
        col_dir = collections_root() / ds_name
        try:
            with self._pipe_lock:
                self._pipe_state["stages"]["seal"] = "running"
            ver = verify_sealed_collection(col_dir)
            record_queue_status(self.prep, ds_name, status="sealed_verified", manifest_sha256=ver["manifest_sha256"], total_episodes=ver["total_episodes"])
            with self._pipe_lock:
                self._pipe_state["stages"]["seal"] = "done"
                self._pipe_state["stages"]["transfer"] = "running"
                self._pipe_state["manifest_sha256"] = ver["manifest_sha256"]
            log(f"[seal] {ds_name} 무결성 확인 완료 ({ver['total_episodes']}ep, {ver['file_count']} files)")

            tr = push_collection_to_model(col_dir, cfg, verified=ver)
            if tr["status"] == "unconfigured":
                record_queue_status(self.prep, ds_name, status="pending_transfer", error=tr["error"])
                with self._pipe_lock:
                    self._pipe_state.update(state="blocked", blocked_reason="model_target_unconfigured", error=tr["error"])
                    self._pipe_state["stages"]["transfer"] = "unconfigured"
                    self._pipe_state["stages"]["intake"] = "unconfigured"
                log(f"[transfer:unconfigured] {tr['error']}")
                return
            if not tr["ok"]:
                return fail_stage("transfer", tr["error"])

            record_queue_status(self.prep, ds_name, status="transferred", remote_path=tr["remote_path"])
            with self._pipe_lock:
                self._pipe_state["stages"]["transfer"] = "done"
                self._pipe_state["stages"]["intake"] = "running"
                self._pipe_state["remote_path"] = tr["remote_path"]
            log(f"[transfer] 모델 PC 전송 완료 -> {tr['remote_path']}")

            intake = notify_canonical_intake(cfg, tr)
            if intake["status"] == "unconfigured":
                record_queue_status(self.prep, ds_name, status="pending_intake", error=intake["error"])
                with self._pipe_lock:
                    self._pipe_state.update(state="transferred", blocked_reason="intake_url_unconfigured", error=intake["error"])
                    self._pipe_state["stages"]["intake"] = "unconfigured"
                log(f"[intake:unconfigured] {intake['error']}")
                return
            if not intake["ok"]:
                return fail_stage("intake", intake["error"])

            job_id = str(intake["response"].get("job_id") or "")
            record_queue_status(self.prep, ds_name, status="done", job_id=job_id, error="")
            with self._pipe_lock:
                self._pipe_state["stages"]["intake"] = "done"
                self._pipe_state["state"] = "done"
                self._pipe_state["intake_job_id"] = job_id
                self._pipe_state["blocked_reason"] = ""
                self._pipe_state["error"] = ""
                self._pipe_state["loop_count"] += 1
            log(f"[intake] Canonical 인입 완료 (job={job_id or 'accepted'})")
        except Exception as exc:
            with self._pipe_lock:
                active_stage = next((k for k in ("seal", "transfer", "intake") if self._pipe_state["stages"].get(k) == "running"), "seal")
            fail_stage(active_stage, f"{type(exc).__name__}: {exc}" if not isinstance(exc, ValueError) else str(exc))

    def pipeline_run(self, body):
        self._pipe_init()
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        with self.lock:
            state_snap = dict(self.state)
        raw_ds = str(body.get("dataset_folder") or body.get("collection") or "").strip()
        if (not raw_ds or raw_ds == state_snap.get("folder")) and state_snap.get("name"):
            ds_name = str(state_snap["name"]).strip()
        elif raw_ds:
            ds_name = Path(raw_ds).name
        else:
            q_pending = [r["collection"] for r in load_handoff_queue(self.prep) if r.get("status") != "done"]
            cols = sorted((p.name for p in collections_root().iterdir() if p.is_dir() and (p / "manifest.json").is_file()), reverse=True) if collections_root().is_dir() else []
            ds_name = (q_pending[-1] if q_pending else "") or (self._pipe_state.get("last_dataset") or "") or (cols[0] if cols else "")
        if not ds_name or not _SAFE_NAME.fullmatch(ds_name):
            raise ValueError("전송할 봉인 컬렉션 이름이 필요합니다 (최근 세션 또는 컬렉션을 선택하세요)")
        if body.get("trigger") == "auto_after_seal" and state_snap.get("status") != "sealed":
            raise ValueError("봉인 완료(sealed)된 세션만 자동 파이프라인을 실행할 수 있습니다")
        with self._pipe_lock:
            if self._pipe_state["state"] == "running":
                raise ValueError("이미 파이프라인 작업이 실행 중입니다")
            self._pipe_state.update(
                state="running", last_dataset=ds_name, manifest_sha256="", remote_path="",
                intake_job_id="", blocked_reason="", error="",
            )
            self._pipe_state["stages"]["collect"] = "done" if state_snap.get("status") == "sealed" else self._pipe_state["stages"].get("collect", "idle")
            for k in ("seal", "transfer", "intake"):
                self._pipe_state["stages"][k] = "idle"
        try:
            threading.Thread(target=self._run_pipeline_worker, args=(ds_name,), daemon=True).start()
        except Exception:
            with self._pipe_lock:
                self._pipe_state["state"] = "failed"
            raise
        return self.pipeline_status()

    def _hf_init(self):
        cfg = load_handoff_config(self.prep)
        with self.lock:
            if not hasattr(self, "_hf_lock"):
                self._hf_lock = threading.Lock()
                self._hf_state = {
                    "state": "idle", "dataset": "", "progress_pct": 0, "message": "",
                    "repo_id": "", "repo_url": "", "auto_upload": bool(cfg["auto_hf_upload"]), "error": "",
                }

    def hf_upload_status(self):
        self._hf_init()
        with self._hf_lock:
            return dict(self._hf_state)

    def hf_upload_config(self, body):
        self._hf_init()
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        if "auto_upload" in body:
            cfg = save_handoff_config(self.prep, {"auto_hf_upload": bool(body["auto_upload"])})
            with self._hf_lock:
                self._hf_state["auto_upload"] = bool(cfg["auto_hf_upload"])
        with self._hf_lock:
            return dict(self._hf_state)

    def _run_hf_upload_worker(self, ds_name, ds_folder, session_dir):
        try:
            parquets = len(list(ds_folder.glob("data/**/*.parquet")))
            videos = len(list(ds_folder.glob("videos/**/*.mp4")))
            if not (ds_folder / "meta" / "info.json").is_file() or parquets < 1:
                raise RuntimeError("LeRobot parquet/meta 인코딩이 완료되지 않았습니다")
            from huggingface_hub import HfApi
            hf_api = HfApi()
            repo_id, path_in_repo = validate_team_hf_upload(
                hf_api, ds_folder, load_handoff_config(self.prep), ds_name=ds_name
            )
            with self._hf_lock:
                self._hf_state.update(state="uploading", progress_pct=60, message=f"HF 팀 업로드 중 ({parquets}회 · {videos}영상)")
            hf_api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True)
            if hasattr(hf_api, "repo_info") and not getattr(hf_api.repo_info(repo_id=repo_id, repo_type="dataset"), "private", False):
                raise RuntimeError(f"비공개 팀 저장소만 업로드 가능합니다: {repo_id}")
            hf_api.upload_folder(
                folder_path=str(ds_folder), repo_id=repo_id, repo_type="dataset",
                path_in_repo=path_in_repo, commit_message=f"Upload OMX dataset {ds_name}",
            )
            repo_url = f"https://huggingface.co/datasets/{repo_id}/tree/main/{path_in_repo}"
            receipt = {"repo_id": repo_id, "path_in_repo": path_in_repo, "url": repo_url, "parquets": parquets, "videos": videos, "uploaded_at": int(time.time())}
            rdir = self.prep / ".hf-receipts"
            rdir.mkdir(parents=True, exist_ok=True)
            (rdir / f"{ds_name}.json").write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
            if session_dir and Path(session_dir).is_dir():
                (Path(session_dir) / "hf-upload.json").write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
            with self._hf_lock:
                self._hf_state.update(state="done", progress_pct=100, message="팀 저장소 업로드 완료", repo_id=repo_id, repo_url=repo_url, error="")
        except Exception as exc:
            with self._hf_lock:
                self._hf_state.update(state="failed", message=str(exc), error=f"{type(exc).__name__}: {exc}")

    def hf_upload_start(self, body):
        self._hf_init()
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        if hasattr(self, "hf_logged_in") and not self.hf_logged_in():
            raise ValueError("HuggingFace 로그인이 필요합니다 (~/.cache/huggingface/token)")
        raw = str(body.get("dataset") or body.get("name") or "").strip()
        ds_name = Path(raw).name if raw else ""
        if not ds_name or not _SAFE_NAME.fullmatch(ds_name):
            raise ValueError("올바른 데이터셋 이름이 필요합니다")
        col_dir = collections_root() / ds_name
        leader_dir = Path.home() / "rosy-data" / "omx-leader" / ds_name
        if (col_dir / "dataset").is_dir():
            verify_sealed_collection(col_dir)
            ds_folder = col_dir / "dataset"
        elif leader_dir.is_dir():
            if any((p / "DO_NOT_TRAIN.txt").is_file() for p in (self.prep / "sessions").glob(f"*-{ds_name}")):
                raise ValueError("정지회차(DO_NOT_TRAIN) 세션의 데이터셋은 업로드할 수 없습니다")
            ds_folder = leader_dir
        else:
            raise ValueError(f"LeRobot 데이터셋을 찾을 수 없습니다: {ds_name}")
        if (ds_folder / "DO_NOT_TRAIN.txt").is_file() or (col_dir / "DO_NOT_TRAIN.txt").is_file():
            raise ValueError("정지회차(DO_NOT_TRAIN) 데이터셋은 업로드할 수 없습니다")
        with self.lock:
            sess_dir = self.state.get("folder") if self.state.get("name") == ds_name else None
        if sess_dir and (Path(sess_dir) / "DO_NOT_TRAIN.txt").is_file():
            raise ValueError("정지회차(DO_NOT_TRAIN) 세션은 업로드할 수 없습니다")
        with self._hf_lock:
            if self._hf_state["state"] in ("encoding", "uploading"):
                raise ValueError("이미 LeRobot 업로드가 진행 중입니다")
            self._hf_state.update(state="encoding", dataset=ds_name, progress_pct=25, message="인코딩 및 팀 계정 검증 중", repo_id="", repo_url="", error="")
        threading.Thread(target=self._run_hf_upload_worker, args=(ds_name, ds_folder, sess_dir), daemon=True).start()
        return {"hf_upload": self.hf_upload_status()}

    def dataset_delete(self, body):
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        ds_name = Path(str(body.get("dataset") or body.get("name") or "").strip()).name
        if not ds_name or not _SAFE_NAME.fullmatch(ds_name):
            raise ValueError("올바른 데이터셋 이름이 필요합니다")
        with self.lock:
            if self.state.get("status") in ("handing_over", "homing", "recording", "restoring", "sealing"):
                raise ValueError("녹화/봉인 중에는 데이터셋을 삭제할 수 없습니다")
        ds_folder = Path.home() / "rosy-data" / "omx-leader" / ds_name
        if not ds_folder.is_dir():
            raise ValueError(f"데이터셋을 찾을 수 없습니다: {ds_name}")
        if list(ds_folder.glob("data/**/*.parquet")):
            raise ValueError("에피소드(parquet)가 있는 데이터셋은 삭제할 수 없습니다")
        shutil.rmtree(ds_folder)
        return {"ok": True, "deleted": ds_name, "lerobot_datasets": self.lerobot_datasets()}
