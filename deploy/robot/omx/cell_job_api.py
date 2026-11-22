#!/usr/bin/env python3
"""Authenticated HTTP job API on the arm cell: fixed, guarded cell commands without SSH."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_job_spec import AB_ARMS, JOBS, SESSION, build_argv, moves_arm  # noqa: E402,F401

try:
    import fcntl
except ImportError:  # Windows unit tests
    fcntl = None

JOB_TTL_S = 900.0
LIVE_MAX_AGE_S = 15.0
_REAL_POPEN = subprocess.Popen


def _flock_held(lock_path: Path, mode: int) -> bool:
    if fcntl is None or not lock_path.exists():
        return False
    with open(lock_path, "a+") as fh:
        try:
            fcntl.flock(fh.fileno(), mode | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return False


def _session_lock_held(arm: str, lock_dir: Path | None = None) -> bool:
    """True when another process holds ~/rosy-omx/session-<arm>.lock."""
    if fcntl is None:
        return False
    return _flock_held((lock_dir or (Path.home() / "rosy-omx")) / f"session-{arm}.lock", fcntl.LOCK_EX)


def _whole_cell_lock_held(lock_dir: Path | None = None) -> bool:
    """True when an exclusive whole-cell ~/rosy-omx/session.lock is held by another process."""
    if fcntl is None:
        return False
    return _flock_held((lock_dir or (Path.home() / "rosy-omx")) / "session.lock", fcntl.LOCK_SH)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_json_dict(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _tools_tree(workdir: Path) -> str | None:
    env_file = workdir / "tools-env-current.sh"
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        code = line.split("#", 1)[0]
        if "omx-tools-" not in code:
            continue
        m = re.search(r"([^\s\"':;=]*omx-tools-[A-Za-z0-9_-]+)", code)
        if m:
            p = Path(os.path.expandvars(m.group(1))).expanduser()
            if not p.is_absolute():
                p = workdir / p
            if p.is_symlink() or p.exists():
                try:
                    return p.resolve().name
                except (OSError, RuntimeError):
                    return p.name
            return p.name
    return None


def read_token(path: Path) -> str:
    st = path.stat()
    if os.name != "nt" and st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SystemExit(f"{path}: readable by group or others; chmod 600 it")
    token = path.read_text().strip()
    if len(token) < 24:
        raise SystemExit(f"{path}: token missing or shorter than 24 characters")
    return token


class Runner:
    """Starts jobs detached, serializes moving jobs per arm and A/B space, and records state/audit in <workdir>/cell-job-api."""

    def __init__(
        self,
        workdir: Path,
        jobs: dict = JOBS,
        lock_dir: Path | None = None,
        lease_dir: Path | None = None,
    ):
        self.workdir, self.jobs, self.out = workdir, jobs, workdir / "cell-job-api"
        self.lock_dir = lock_dir
        self.lease_dir = lease_dir or (Path.home() / ".local" / "state" / "rosy" / "arm-leases")
        self._lease_owner = f"cell-job-api:{os.getpid()}"
        self.out.mkdir(exist_ok=True)
        self.lock, self.runs = threading.Lock(), {}

    def _audit_locked(self, jid: str, run: dict, code: int) -> None:
        if run["audited"]:
            return
        row = {
            "id": jid,
            "job": run["job"],
            "params": run["params"],
            "start": run["start"],
            "end": time.time(),
            "exit": code,
            "state_changes": {
                "arm": run["arm"],
                "exit": code,
                "log": str(run["log"]),
                "omx_tools_tree": run.get("omx_tools_tree"),
            },
        }
        with open(self.out / "audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        run["audited"] = True

    def _can_reuse_arm_session_locked(self, arm: str) -> bool:
        """True only when this runner owns the warm idle arm session and live state is clean and unheld."""
        lease = _read_json_dict(self.lease_dir / f"{arm}.json")
        if lease is None or lease.get("owner") != self._lease_owner or lease.get("hold"):
            return False
        if "pid" in lease:
            pid = lease["pid"]
            if isinstance(pid, bool) or not isinstance(pid, int) or not _pid_alive(pid):
                return False
        last_run = next((r for r in reversed(list(self.runs.values())) if r["moving"] and r["arm"] == arm), None)
        if last_run is None or last_run["proc"].poll() != 0:
            return False
        live = _read_json_dict(self.workdir / f"chunk-io-{arm.split('_')[-1]}" / "live.json")
        if live is None or live.get("chunk") is not None or live.get("human_hold_latched") or live.get("fault") or live.get("interrupt"):
            return False
        if "t" in live:
            ts = live["t"]
            if isinstance(ts, bool) or not isinstance(ts, (int, float)) or (time.time() - float(ts)) > LIVE_MAX_AGE_S:
                return False
        return True

    def start(self, name: str, params: dict) -> dict:
        job = self.jobs.get(name)
        if job is None:
            return {"code": 404, "error": f"no job {name}"}
        try:
            argv = build_argv(job, params, self.workdir)
        except ValueError as exc:
            return {"code": 400, "error": str(exc)}
        arm = params.get("arm")
        moving = moves_arm(job, params)
        with self.lock:
            for old_jid, r in self.runs.items():
                if (code := r["proc"].poll()) is not None:
                    self._audit_locked(old_jid, r, code)
            if moving:
                for r in self.runs.values():
                    if not r["moving"] or r["proc"].poll() is not None:
                        continue
                    if r["arm"] == arm:
                        return {"code": 409, "error": f"a moving job already runs on {arm}"}
                    if arm in AB_ARMS and r["arm"] in AB_ARMS:
                        return {"code": 409, "error": f"A/B cell space is held by {r['arm']} ({r['job']})"}
                if _whole_cell_lock_held(self.lock_dir):
                    return {"code": 409, "error": "whole-cell session.lock is held by another process"}
                check_arms = sorted(AB_ARMS) if arm in AB_ARMS else [arm]
                for check_arm in check_arms:
                    if _session_lock_held(check_arm, self.lock_dir) and not self._can_reuse_arm_session_locked(check_arm):
                        return {"code": 409, "error": f"session lock for {check_arm} is held by another process"}
            if job.get("camera") and any(r["camera"] and r["proc"].poll() is None for r in self.runs.values()):
                return {"code": 409, "error": "another camera job is running (one D435 depth reader at a time)"}
            jid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
            log = self.out / f"{jid}.log"
            with open(log, "wb") as fh:
                proc = subprocess.Popen(
                    argv,
                    cwd=self.workdir,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    env={**os.environ, "ROSY_ARM_LEASE_OWNER": self._lease_owner},
                )
            now = time.time()
            run = {
                "job": name,
                "params": params,
                "argv": argv,
                "proc": proc,
                "log": log,
                "moving": moving,
                "camera": bool(job.get("camera")),
                "arm": arm,
                "purpose": params.get("purpose") or name,
                "holder": params.get("operator") or arm or name,
                "start": now,
                "expires_at": now + JOB_TTL_S,
                "omx_tools_tree": _tools_tree(self.workdir),
                "audited": False,
            }
            self.runs[jid] = run
            if isinstance(proc, _REAL_POPEN):
                def _reap(jid=jid, run=run):
                    code = run["proc"].wait()
                    with self.lock:
                        self._audit_locked(jid, run, code)

                threading.Thread(target=_reap, daemon=True, name=f"reap-{jid}").start()
        return {"code": 202, "id": jid}

    def queue(self) -> dict:
        with self.lock:
            active = []
            for jid, r in self.runs.items():
                if (code := r["proc"].poll()) is not None:
                    self._audit_locked(jid, r, code)
                    continue
                active.append(
                    {
                        "id": jid,
                        "job": r["job"],
                        "arm": r["arm"],
                        "moving": r["moving"],
                        "camera": r["camera"],
                        "holder": r["holder"],
                        "purpose": r["purpose"],
                        "started_at": r["start"],
                        "expires_at": r["expires_at"],
                    }
                )
        return {"active": active}

    def get(self, jid: str, tail: int = 4000) -> dict | None:
        with self.lock:
            run = self.runs.get(jid)
            if run is None:
                return None
            code = run["proc"].poll()
            if code is not None:
                self._audit_locked(jid, run, code)
        data = run["log"].read_bytes()[-tail:].decode("utf-8", "replace") if tail > 0 else ""
        return {"id": jid, "job": run["job"], "argv": run["argv"], "running": code is None, "exit": code, "log": data}


def make_server(bind: str, port: int, token: str, runner: Runner, viewer: str = "http://127.0.0.1:8767"):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body, ctype="application/json"):
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _authed(self) -> bool:
            got = self.headers.get("Authorization", "")
            if hmac.compare_digest(got.encode(), f"Bearer {token}".encode()):
                return True
            self._send(401, {"error": "unauthorized"})
            return False

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True})
            if not self._authed():
                return
            if m := re.fullmatch(r"/frame/(top|side|arm_s_top|arm_s_wrist|arm_a_wrist|arm_b_wrist)\.jpg", self.path):
                try:
                    with urllib.request.urlopen(f"{viewer}/frame/{m.group(1)}.jpg", timeout=5) as resp:
                        return self._send(200, resp.read(), "image/jpeg")
                except urllib.error.HTTPError as exc:
                    return self._send(exc.code, {"error": f"viewer returned HTTP {exc.code}"})
                except OSError as exc:
                    return self._send(502, {"error": f"viewer unreachable: {exc}"})
            if self.path == "/queue":
                return self._send(200, runner.queue())
            if self.path == "/jobs":
                return self._send(200, [runner.get(j, 0) for j in list(runner.runs)[-50:]])
            if (m := re.fullmatch(r"/jobs/([\w-]+)", self.path)) and (run := runner.get(m.group(1))):
                return self._send(200, run)
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authed():
                return
            m = re.fullmatch(r"/jobs/(\w+)", self.path)
            if not m:
                return self._send(404, {"error": "not found"})
            try:
                params = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 65536)) or b"{}")
            except ValueError:
                return self._send(400, {"error": "body is not JSON"})
            if not isinstance(params, dict):
                return self._send(400, {"error": "body must be a JSON object"})
            out = runner.start(m.group(1), params)
            self._send(out.pop("code"), out)

    return ThreadingHTTPServer((bind, port), Handler)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8781)
    ap.add_argument("--token-file", type=Path, default=Path.home() / ".config/rosy/cell-job-api.token")
    a = ap.parse_args()
    server = make_server(a.bind, a.port, read_token(a.token_file), Runner(a.workdir.expanduser()))
    print(f"cell job API on {a.bind}:{a.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
