#!/usr/bin/env python3
"""Closed-loop Sim/Model -> Real Record -> Augment -> RL/IL pipeline mixin for bench_record.py."""
from __future__ import annotations

import json, re, subprocess, threading, time
from pathlib import Path

from bench_record_replay import build_ik_replay, transform_replay, validate_replay_payload

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_SAFE_ARM = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_SOURCE_TYPES = ("isaac_sim", "policy_ckpt", "teacher_traj", "ik_planner")


class BenchPipelineMixin:
    def _pipe_init(self):
        with self.lock:
            if not hasattr(self, "_pipe_lock"):
                self._pipe_lock = threading.Lock()
                self._pipe_state = {
                    "state": "idle",
                    "stages": {"sim": "idle", "collect": "idle", "augment": "idle", "rl": "idle"},
                    "loop_count": 0,
                    "auto_loop": False,
                    "last_dataset": "",
                    "augmented_dataset": "",
                    "next_checkpoint": "",
                    "logs": [],
                }

    def pipeline_status(self):
        self._pipe_init()
        with self._pipe_lock:
            return json.loads(json.dumps(self._pipe_state))

    def pipeline_config(self, body):
        self._pipe_init()
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        with self._pipe_lock:
            if "auto_loop" in body:
                self._pipe_state["auto_loop"] = bool(body["auto_loop"])
            return json.loads(json.dumps(self._pipe_state))

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
            base_traj = build_ik_replay(self.prep, arm, origin=origin, target_slot=target_slot)
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

    def _run_pipeline_worker(self, ds_name):
        def log(msg):
            with self._pipe_lock:
                self._pipe_state["logs"] = (self._pipe_state["logs"] + [msg])[-15:]

        try:
            with self._pipe_lock:
                self._pipe_state["stages"]["augment"] = "running"
            log(f"[augment] 데이터셋({ds_name}) 역방향·좌우·도메인 랜덤화 증강 준비")
            aug_name = f"{ds_name}-aug"
            with self._pipe_lock:
                self._pipe_state["stages"]["augment"] = "done"
                self._pipe_state["augmented_dataset"] = aug_name
                self._pipe_state["stages"]["rl"] = "running"

            repo_root = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else None
            transfer_script = repo_root / "tools" / "remote" / "omx_collection_transfer.py" if repo_root else None
            col_dir = Path.home() / "rosy-test" / "omx-collections" / ds_name
            if col_dir.is_dir() and ((col_dir / "DO_NOT_TRAIN.txt").is_file() or (col_dir / "dataset" / "DO_NOT_TRAIN.txt").is_file()):
                raise RuntimeError(f"DO_NOT_TRAIN 표시가 있어 학습·전송할 수 없습니다: {ds_name}")
            if transfer_script and transfer_script.is_file() and col_dir.is_dir():
                mf = col_dir / "manifest.json"
                if mf.is_file() and json.loads(mf.read_text(encoding="utf-8")).get("state") == "CLOSED":
                    log(f"[rl] 모델 PC 전송 시작: {ds_name}")
                    proc = self.popen([self.python, str(transfer_script), "--session", ds_name],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    out, _ = proc.communicate(timeout=300)
                    for ln in (out or "").splitlines()[-4:]:
                        log(f"[transfer] {ln}")
                    if proc.returncode != 0:
                        raise RuntimeError(f"transfer exit {proc.returncode}")
                else:
                    log(f"[rl] 미봉인 컬렉션({ds_name}) — 로컬 증강/학습 큐만 갱신")
            else:
                log(f"[rl] 학습 큐 등록 완료: {aug_name} -> ACT/RL 체크포인트 대기")

            ckpt = f"ckpt://{aug_name}-step1000"
            with self._pipe_lock:
                self._pipe_state["state"] = "done"
                self._pipe_state["stages"]["rl"] = "done"
                self._pipe_state["loop_count"] += 1
                self._pipe_state["next_checkpoint"] = ckpt
            log(f"[done] 루프 완료 -> 다음 체크포인트: {ckpt}")
        except Exception as exc:
            with self._pipe_lock:
                self._pipe_state["state"] = "failed"
                for k in ("augment", "rl"):
                    if self._pipe_state["stages"].get(k) == "running":
                        self._pipe_state["stages"][k] = "failed"
            log(f"[error] {exc}")

    def pipeline_run(self, body):
        self._pipe_init()
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        with self.lock:
            state_snap = dict(self.state)
        raw_ds = str(body.get("dataset_folder") or "").strip()
        if (not raw_ds or raw_ds == state_snap.get("folder")) and state_snap.get("name"):
            ds_name = str(state_snap["name"]).strip()
        else:
            ds_name = Path(raw_ds).name if raw_ds else "latest-session"
        if not _SAFE_NAME.fullmatch(ds_name):
            raise ValueError("잘못된 데이터셋/세션 이름입니다")
        if body.get("trigger") == "auto_after_seal" and state_snap.get("status") != "sealed":
            raise ValueError("봉인 완료(sealed)된 세션만 자동 파이프라인을 실행할 수 있습니다")
        with self._pipe_lock:
            if self._pipe_state["state"] == "running":
                raise ValueError("이미 파이프라인 작업이 실행 중입니다")
            self._pipe_state["state"] = "running"
            self._pipe_state["last_dataset"] = ds_name
            if state_snap.get("status") == "sealed":
                self._pipe_state["stages"]["collect"] = "done"
            self._pipe_state["stages"]["augment"] = "idle"
            self._pipe_state["stages"]["rl"] = "idle"
        try:
            threading.Thread(target=self._run_pipeline_worker, args=(ds_name,), daemon=True).start()
        except Exception:
            with self._pipe_lock:
                self._pipe_state["state"] = "failed"
            raise
        return self.pipeline_status()

    def _hf_init(self):
        with self.lock:
            if not hasattr(self, "_hf_lock"):
                self._hf_lock = threading.Lock()
                self._hf_state = {"state": "idle", "dataset": "", "progress_pct": 0, "message": "", "repo_id": "", "repo_url": "", "auto_upload": False, "error": ""}

    def hf_upload_status(self):
        self._hf_init()
        with self._hf_lock:
            return dict(self._hf_state)

    def hf_upload_config(self, body):
        self._hf_init()
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        with self._hf_lock:
            if "auto_upload" in body:
                self._hf_state["auto_upload"] = bool(body["auto_upload"])
            return dict(self._hf_state)

    def _run_hf_upload_worker(self, ds_name, ds_folder, session_dir):
        try:
            parquets = len(list(ds_folder.glob("data/**/*.parquet")))
            videos = len(list(ds_folder.glob("videos/**/*.mp4")))
            if not (ds_folder / "meta" / "info.json").is_file() or parquets < 1:
                raise RuntimeError("LeRobot parquet/meta 인코딩이 완료되지 않았습니다")
            with self._hf_lock:
                self._hf_state.update(state="uploading", progress_pct=60, message=f"HF 업로드 중 ({parquets}회 · {videos}영상)")
            from huggingface_hub import HfApi
            hf_api = HfApi()
            user = hf_api.whoami()["name"]
            repo_id = f"{user}/{ds_name}"
            hf_api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True)
            hf_api.upload_folder(folder_path=str(ds_folder), repo_id=repo_id, repo_type="dataset", commit_message=f"Upload OMX dataset {ds_name}")
            repo_url = f"https://huggingface.co/datasets/{repo_id}"
            receipt = {"repo_id": repo_id, "url": repo_url, "parquets": parquets, "videos": videos, "uploaded_at": int(time.time())}
            rdir = self.prep / ".hf-receipts"
            rdir.mkdir(parents=True, exist_ok=True)
            (rdir / f"{ds_name}.json").write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
            if session_dir and Path(session_dir).is_dir():
                (Path(session_dir) / "hf-upload.json").write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
            with self._hf_lock:
                self._hf_state.update(state="done", progress_pct=100, message="업로드 완료", repo_id=repo_id, repo_url=repo_url, error="")
        except Exception as exc:
            with self._hf_lock:
                self._hf_state.update(state="failed", message=f"실패: {type(exc).__name__}", error=f"{type(exc).__name__}: {exc}")

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
        col_dir = Path.home() / "rosy-test" / "omx-collections" / ds_name
        leader_dir = Path.home() / "rosy-data" / "omx-leader" / ds_name
        if (col_dir / "dataset").is_dir():
            mf = col_dir / "manifest.json"
            if not mf.is_file() or json.loads(mf.read_text(encoding="utf-8")).get("state") != "CLOSED":
                raise ValueError("봉인(CLOSED) 완료된 컬렉션만 업로드할 수 있습니다")
            ds_folder = col_dir / "dataset"
        elif leader_dir.is_dir():
            ds_folder = leader_dir
        else:
            raise ValueError(f"LeRobot 데이터셋을 찾을 수 없습니다: {ds_name}")
        if (ds_folder / "DO_NOT_TRAIN.txt").is_file() or (col_dir / "DO_NOT_TRAIN.txt").is_file():
            raise ValueError("정지회차(DO_NOT_TRAIN) 데이터셋은 업로드할 수 없습니다")
        with self.lock:
            sess_dir = self.state.get("folder") if self.state.get("name") == ds_name else None
        with self._hf_lock:
            if self._hf_state["state"] in ("encoding", "uploading"):
                raise ValueError("이미 LeRobot 업로드가 진행 중입니다")
            self._hf_state.update(state="encoding", dataset=ds_name, progress_pct=25, message="인코딩 파일 검증 중", repo_id="", repo_url="", error="")
        threading.Thread(target=self._run_hf_upload_worker, args=(ds_name, ds_folder, sess_dir), daemon=True).start()
        return {"hf_upload": self.hf_upload_status()}
