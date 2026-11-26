"""Put a finished canonical train_stage checkpoint on the AI PC ACT server, as a background job.

Config (canonical config, host-private): "act_serve": {"url": "http://<ai-pc>:8790",
"token_file": "/abs/act.token", "copy": {"ssh_target": "user@ai-pc", "dest_root": "/abs/load-root"}}.
Training writes checkpoints on this (model) PC, so the job first copies the checkpoint dir to
dest_root/<run-id>-<sha12> on the ACT host (rsync over ssh), checks model.safetensors' sha256
there, then calls POST /arms/{arm}/load with that path. Without "copy" the local path is sent
(Learning and ACT server on one host). The ACT server re-verifies and keeps the old model on any
failure. Job state lives in memory: a Learning server restart forgets it (the ACT /health stays true).
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

from canonical_telemetry import load_peer_token
from canonical_watch import strip_paths, validate_peer_url
from experiment_io import identifier

LOAD_TIMEOUT_S = 180  # a GPU checkpoint load on the AI PC takes seconds to tens of seconds
COPY_TIMEOUT_S = 1800
ARM_IDS = ("arm_a", "arm_b")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_SSH_TARGET = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}|[A-Za-z0-9][A-Za-z0-9.-]{0,252}")
_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]


def parse_config(raw) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not {"url", "token_file"} <= set(raw) or set(raw) - {"url", "token_file", "copy"}:
        raise ValueError("act_serve requires url and token_file (copy optional)")
    token_file = Path(raw["token_file"])
    if not token_file.is_absolute():
        raise ValueError("act_serve.token_file must be absolute")
    out = {"url": validate_peer_url(raw["url"]), "token_file": token_file, "copy": None}
    copy = raw.get("copy")
    if copy is not None:
        if not isinstance(copy, dict) or set(copy) != {"ssh_target", "dest_root"}:
            raise ValueError("act_serve.copy requires exactly ssh_target and dest_root")
        dest = copy["dest_root"]
        if not isinstance(copy["ssh_target"], str) or not _SSH_TARGET.fullmatch(copy["ssh_target"]):
            raise ValueError("act_serve.copy.ssh_target must be host or user@host")
        if (not isinstance(dest, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]{0,255}", dest)
                or ".." in PurePosixPath(dest).parts):
            raise ValueError("act_serve.copy.dest_root must be an absolute POSIX path")
        out["copy"] = {"ssh_target": copy["ssh_target"], "dest_root": dest.rstrip("/") or "/"}
    return out


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=COPY_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 255, type(exc).__name__
    return proc.returncode, (proc.stdout + proc.stderr)[-400:]


class ServeJobs:
    """In-memory serve jobs for one CanonicalService; one job per run at a time."""

    def __init__(self, service, runner=_run, *, background: bool = True):
        self.service, self.runner, self.background = service, runner, background
        self.lock = threading.Lock()
        self.by_run: dict[str, dict] = {}

    def latest(self, rid: str) -> dict:
        with self.lock:
            job = self.by_run.get(identifier(rid))
            if job is None:
                raise KeyError("no serve job for this run")
            return strip_paths(dict(job))  # no AI PC paths or ssh output paths in the browser

    def start(self, rid: str, body) -> dict:
        cfg = getattr(self.service, "act_serve", None)
        if cfg is None:
            raise ValueError("ACT 서빙 서버가 설정되지 않았습니다 (canonical config act_serve).")
        rid = identifier(rid)
        if not isinstance(body, dict) or set(body) != {"arm_id"} or body["arm_id"] not in ARM_IDS:
            raise ValueError("서빙 요청은 arm_id(arm_a 또는 arm_b)만 담아야 합니다.")
        run = self.service.get_run(rid)
        sha = (run.get("result") or {}).get("policy_sha256")
        if run["kind"] != "train_stage" or run["status"] != "succeeded" or not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha):
            raise ValueError("완료된 train_stage 작업만 서빙에 올릴 수 있습니다.")
        if body["arm_id"] != run["arm_id"]:
            raise ValueError(f"이 작업은 {run['arm_id']} 학습입니다. 다른 팔({body['arm_id']})에는 올리지 않습니다.")
        with self.lock:
            prev = self.by_run.get(rid)
            if prev is not None and prev["state"] not in ("done", "failed"):
                raise ValueError("이 작업은 이미 서빙에 올리는 중입니다.")
            job = {"job_id": str(uuid.uuid4()), "run_id": rid, "arm_id": run["arm_id"], "sha256": sha,
                   "state": "copying" if cfg["copy"] else "loading", "reason": None, "started_at": time.time(), "reply": None}
            self.by_run[rid] = job
            snapshot = strip_paths(dict(job))
        if self.background:
            threading.Thread(target=self._work, args=(job, cfg), daemon=True, name=f"act-serve-{rid[:8]}").start()
        else:
            self._work(job, cfg)
        return snapshot

    def _set(self, job: dict, **fields) -> None:
        with self.lock:
            job.update(fields)

    def _work(self, job: dict, cfg: dict) -> None:
        try:
            self._steps(job, cfg)
        except Exception as exc:  # the job line must end in done/failed, never hang in a middle state
            self._set(job, state="failed", reason=f"내부 오류 ({type(exc).__name__})")

    def _steps(self, job: dict, cfg: dict) -> None:
        rid, sha = job["run_id"], job["sha256"]
        src = (self.service.root / "runs" / rid / "output" / "train" / "checkpoints" / "last" / "pretrained_model").resolve()
        if not (src / "model.safetensors").is_file():
            return self._set(job, state="failed", reason="이 작업대에 체크포인트 파일이 없습니다.")
        target_dir = str(src)
        if cfg["copy"]:
            host, dest = cfg["copy"]["ssh_target"], f"{cfg['copy']['dest_root']}/{rid}-{sha[:12]}"
            steps = [
                ("copying", [*_SSH, host, "mkdir -p -- " + shlex.quote(dest)]),
                ("copying", ["rsync", "-a", "--delete", "-e", " ".join(_SSH), f"{src}/", f"{host}:{dest}/"]),  # dest is [A-Za-z0-9_./-] only
            ]
            for state, argv in steps:
                self._set(job, state=state)
                code, out = self.runner(argv)
                if code != 0:
                    return self._set(job, state="failed", reason=f"복사 실패 (exit {code}): {out.strip()[-200:]}")
            self._set(job, state="verifying")
            code, out = self.runner([*_SSH, host, "sha256sum -- " + shlex.quote(dest + "/model.safetensors")])
            got = out.split()[0] if code == 0 and out.split() else ""
            if got != sha:
                return self._set(job, state="failed", reason=f"복사본 sha256이 다릅니다 ({got[:12] or '읽기 실패'} != {sha[:12]}).")
            target_dir = dest
        self._set(job, state="loading", load_dir=target_dir)  # *_dir keys never reach the browser
        status, reply = _post_load(cfg, job["arm_id"], target_dir, sha)
        ok = status == 200 and reply.get("ok") is True
        self._set(job, state="done" if ok else "failed", reply=reply, http_status=status,
                  reason=None if ok else str(reply.get("error") or f"HTTP {status}")[:300])


def _post_load(cfg: dict, arm_id: str, target_dir: str, sha: str) -> tuple[int, dict]:
    body = json.dumps({"dir": target_dir, "sha256": sha}).encode("utf-8")
    req = urllib.request.Request(cfg["url"] + f"/arms/{arm_id}/load", data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + load_peer_token(cfg["token_file"])})
    try:
        with _OPENER.open(req, timeout=LOAD_TIMEOUT_S) as resp:
            status, raw = resp.status, resp.read(65536)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(65536)
    except (OSError, urllib.error.URLError) as exc:
        return 0, {"error": f"ACT 서버에 연결하지 못했습니다 ({type(exc).__name__})."}
    try:
        reply = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        reply = {"error": f"ACT 서버 응답을 읽지 못했습니다 (HTTP {status})."}
    return status, reply if isinstance(reply, dict) else {}
