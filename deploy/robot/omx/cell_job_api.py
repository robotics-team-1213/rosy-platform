#!/usr/bin/env python3
"""Authenticated HTTP job API on the arm cell: fixed, guarded cell commands without SSH."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_depth_lock import is_depth_lock_held  # noqa: E402
from cell_failure_context import default_bundle_root  # noqa: E402
from cell_job_guards import (  # noqa: E402
    IDEMPOTENCY_KEY_RE, ROLE_HUMAN, ROLE_MACHINE, IdempotencyStore, Principal,
    authenticate_bearer, authorize_principal, check_arm_incident_hold, check_fleet_safety_online,
    check_peer_ab_folded, check_two_arm_ab_ready, pid_alive as _pid_alive, read_json_dict as _read_json_dict,
    read_token_file as read_token, session_reuse_live_ok, tools_tree_name, write_cell_state_dirty,
)
from cell_job_peer_health import live_hold_attach_err  # noqa: E402
from cell_job_readiness import (  # noqa: E402
    CellStateGen, handle_get_route, parse_structured_result, proxy_frame, read_tail_bytes,
)
from cell_job_spec import AB_ARMS, JOBS, SESSION, S_DRY_RUN_ENV, build_argv, job_arms, moves_arm  # noqa: E402,F401

try:
    import fcntl
except ImportError:  # Windows unit tests
    fcntl = None

JOB_TTL_S = 900.0
LIVE_MAX_AGE_S = 15.0
_REAL_POPEN = subprocess.Popen
_check_arm_incident = check_arm_incident_hold
_check_depth_lock_held = is_depth_lock_held


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
    return False if fcntl is None else _flock_held((lock_dir or (Path.home() / "rosy-omx")) / f"session-{arm}.lock", fcntl.LOCK_EX)


def _whole_cell_lock_held(lock_dir: Path | None = None) -> bool:
    """True when an exclusive whole-cell ~/rosy-omx/session.lock is held by another process."""
    return False if fcntl is None else _flock_held((lock_dir or (Path.home() / "rosy-omx")) / "session.lock", fcntl.LOCK_SH)


def _tools_tree(workdir: Path) -> str | None:
    return tools_tree_name(workdir)


def _dirty_arms(run: dict) -> tuple[str, ...]:
    if run.get("arms"):
        return tuple(run["arms"])
    return (run["arm"],) if run.get("arm") else ()


class Runner:
    """Starts jobs detached, serializes moving jobs per arm and A/B space, and records state/audit in <workdir>/cell-job-api."""

    def __init__(self, workdir: Path, jobs: dict = JOBS, lock_dir: Path | None = None, lease_dir: Path | None = None,
                 *, incident_check_fn=None, fleet_safety_check_fn=None, fleet_r_url: str | None = None,
                 fleet_token_file: Path | None = None, ca_file: Path | None = None,
                 motor_health_dir: Path | None = None, calibration_dir: Path | None = None,
                 bundle_root: Path | None = None):
        self.workdir, self.jobs, self.out = workdir, jobs, workdir / "cell-job-api"
        self.lock_dir = lock_dir
        self.lease_dir = lease_dir or (Path.home() / ".local" / "state" / "rosy" / "arm-leases")
        self.motor_health_dir = motor_health_dir
        self.calibration_dir = calibration_dir
        self.bundle_root = Path(bundle_root) if bundle_root is not None else default_bundle_root()
        self._lease_owner = f"cell-job-api:{os.getpid()}"
        self._incident_check_fn, self._fleet_safety_check_fn = incident_check_fn, fleet_safety_check_fn
        self._fleet_r_url, self._fleet_token_file, self._ca_file = fleet_r_url, fleet_token_file, ca_file
        self.out.mkdir(exist_ok=True)
        self._idempotency = IdempotencyStore(self.out / "idempotency.json")
        self._state_gen = CellStateGen(self.out / "cell-state-gen.json")
        self.lock, self.runs = threading.Lock(), {}

    def state_gen(self) -> int:
        return self._state_gen.current()

    def _check_incident(self, arm: str | None) -> str | None:
        return self._incident_check_fn(arm) if self._incident_check_fn is not None else _check_arm_incident(arm)

    def _check_fleet_safety(self, arm: str | None) -> dict:
        if self._fleet_safety_check_fn is not None:
            return self._fleet_safety_check_fn(arm)
        return check_fleet_safety_online(
            arm, fleet_r_url=self._fleet_r_url, fleet_token_file=self._fleet_token_file, ca_file=self._ca_file
        )

    def _audit_locked(self, jid: str, run: dict, code: int) -> None:
        if run["audited"]:
            return
        ended = time.time()
        row = {
            "id": jid,
            "job": run["job"],
            "params": run["params"],
            "principal_role": run.get("principal_role", ROLE_HUMAN),
            "principal_id": run.get("principal_id", ROLE_HUMAN),
            "proposer": run.get("proposer"),
            "fleet_online": run.get("fleet_online", False),
            "start": run["start"],
            "end": ended,
            "exit": code,
            "state_changes": {"arm": run["arm"], "exit": code, "log": str(run["log"]), "omx_tools_tree": run.get("omx_tools_tree")},
        }
        with open(self.out / "audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        if run["moving"]:
            for dirty_arm in _dirty_arms(run):
                write_cell_state_dirty(
                    self.workdir, dirty_arm, job_id=jid, job=run["job"], start=run["start"], end=ended, exit_code=code,
                    fleet_online=bool(run.get("fleet_online")),
                    principal=Principal(row["principal_role"], row["principal_id"]),
                )
        if run["moving"] and code == 0:
            self._state_gen.bump()
        run["audited"] = True

    def _can_reuse_arm_session_locked(self, arm: str) -> bool:
        """True only when this runner owns the warm idle arm session and live state is clean and unheld."""
        if self._check_incident(arm):
            return False
        return session_reuse_live_ok(
            arm, self.workdir, self.lease_dir, self.runs,
            lease_owner=self._lease_owner, live_max_age_s=LIVE_MAX_AGE_S,
            read_json_fn=_read_json_dict, pid_alive_fn=_pid_alive,
        )

    def start(self, name: str, params: dict, *, principal: Principal | None = None, idempotency_key: str | None = None) -> dict:
        principal = principal or Principal(ROLE_HUMAN, ROLE_HUMAN)
        if idempotency_key is not None and not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
            return {"code": 400, "error": "invalid Idempotency-Key header"}
        job = self.jobs.get(name)
        if job is None:
            return {"code": 404, "error": f"no job {name}"}
        eff_params, auth_err = authorize_principal(name, job, params, principal, moves_arm_fn=moves_arm)
        if auth_err is not None:
            return auth_err
        try:
            argv = build_argv(job, eff_params, self.workdir)
        except (ValueError, OSError, RuntimeError) as exc:  # RuntimeError: Path.resolve() on a symlink loop (3.12)
            return {"code": 400, "error": str(exc)}
        arms = job_arms(job, eff_params)
        target_arms = set(arms)
        arm = arms[0] if len(arms) == 1 else ("arm_ab" if target_arms == AB_ARMS else None)
        moving = moves_arm(job, eff_params)
        idem_digest = IdempotencyStore.payload_sha256(name, eff_params) if idempotency_key else None
        with self.lock:
            for old_jid, r in self.runs.items():
                if (code := r["proc"].poll()) is not None:
                    self._audit_locked(old_jid, r, code)
            if idempotency_key and idem_digest is not None:
                kind, existing_jid = self._idempotency.lookup(idempotency_key, idem_digest)
                if kind == "replay":
                    return {"code": 202, "id": existing_jid, "idempotent_replay": True}
                if kind == "conflict":
                    return {"code": 409, "error_code": "IDEMPOTENCY_KEY_CONFLICT", "error": "Idempotency-Key conflict"}
            fleet_online = False
            if moving:
                for r in self.runs.values():
                    if not r["moving"] or r["proc"].poll() is not None:
                        continue
                    r_arms = set(r.get("arms") or (() if not r.get("arm") else (r["arm"],)))
                    if overlap := (target_arms & r_arms):
                        return {"code": 409, "error": f"a moving job already runs on {sorted(overlap)[0]}"}
                    if (target_arms & AB_ARMS) and (r_arms & AB_ARMS):
                        return {"code": 409, "error": f"A/B cell space is held by {r['arm']} ({r['job']})"}
                if not job.get("recovery_home"):
                    for a in arms:
                        if inc_reason := self._check_incident(a):
                            return {"code": 409, "error_code": "ARM_INCIDENT_HELD", "error": f"{a} held: {inc_reason}"}
                for a in arms or (None,):
                    fleet_st = self._check_fleet_safety(a)
                    fleet_online = fleet_online or bool(fleet_st.get("online"))
                    if fleet_st.get("blocked"):
                        return {"code": 409, "error_code": "FLEET_SAFETY_STOP", "error": fleet_st.get("reason") or "Fleet safety stop"}
                if _whole_cell_lock_held(self.lock_dir):
                    return {"code": 409, "error": "whole-cell session.lock is held by another process"}
                attach_hold, rec_home = bool(job.get("attach_live_hold")), bool(job.get("recovery_home"))
                attach_err = live_hold_attach_err(arm, self.workdir, self.lease_dir, self.lock_dir, session_lock_held_fn=_session_lock_held, read_json_fn=_read_json_dict, live_max_age_s=LIVE_MAX_AGE_S, pid_alive_fn=_pid_alive) if (attach_hold or rec_home) else None
                if attach_hold and attach_err: return {"code": 409, "error_code": "NO_LIVE_HOLD_TO_RECOVER", "error": attach_err}
                lock_arms = sorted(AB_ARMS) if (target_arms & AB_ARMS) else list(arms)
                for check_arm in lock_arms:
                    if not ((attach_hold or (rec_home and attach_err is None)) and check_arm == arm) and _session_lock_held(check_arm, self.lock_dir) and not self._can_reuse_arm_session_locked(check_arm):
                        return {"code": 409, "error": f"session lock for {check_arm} is held by another process"}
                if target_arms == AB_ARMS:
                    if ready_err := check_two_arm_ab_ready(self.workdir, self.lease_dir, self.lock_dir, session_lock_held_fn=_session_lock_held, read_json_fn=_read_json_dict, live_max_age_s=LIVE_MAX_AGE_S, incident_check_fn=self._check_incident, motor_health_dir=self.motor_health_dir, calibration_dir=self.calibration_dir):
                        return {"code": 409, "error_code": "TWO_ARM_NOT_READY", "error": ready_err}
                elif arm in AB_ARMS:
                    if peer_err := check_peer_ab_folded(
                        arm, self.workdir, self.lease_dir, self.lock_dir,
                        session_lock_held_fn=_session_lock_held, read_json_fn=_read_json_dict,
                        live_max_age_s=LIVE_MAX_AGE_S, incident_check_fn=self._check_incident,
                        motor_health_dir=self.motor_health_dir, calibration_dir=self.calibration_dir,
                    ):
                        return {"code": 409, "error_code": "PEER_ARM_NOT_FOLDED", "error": peer_err}
            if job.get("camera"):
                if any(r["camera"] and r["proc"].poll() is None for r in self.runs.values()):
                    return {"code": 409, "error": "another camera job is running (one D435 depth reader at a time)"}
                if _check_depth_lock_held(self.lock_dir):
                    return {"code": 409, "error_code": "DEPTH_LOCK_HELD", "error": "depth-d435.lock held by another process"}
            jid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
            log = self.out / f"{jid}.log"
            env = {**os.environ, "ROSY_ARM_LEASE_OWNER": self._lease_owner}
            if "act_backend" in eff_params:
                env["ROSY_ACT_BACKEND"] = str(eff_params["act_backend"])
            with open(log, "wb") as fh:
                proc = subprocess.Popen(
                    argv, cwd=self.workdir, stdout=fh, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, start_new_session=True, env=env,
                )
            now = time.time()
            run = {
                "job": name, "params": eff_params, "argv": argv, "proc": proc, "log": log,
                "moving": moving, "camera": bool(job.get("camera")), "arm": arm, "arms": arms,
                "purpose": eff_params.get("purpose") or name,
                "holder": eff_params.get("operator") or arm or name,
                "principal_role": principal.role, "principal_id": principal.principal_id,
                "proposer": eff_params.get("proposer"), "fleet_online": fleet_online,
                "start": now, "expires_at": now + JOB_TTL_S,
                "omx_tools_tree": Path(argv[4]).name if len(argv) >= 5 and argv[2].startswith(S_DRY_RUN_ENV) else _tools_tree(self.workdir), "audited": False,
            }
            self.runs[jid] = run
            if moving:
                for dirty_arm in _dirty_arms(run):
                    write_cell_state_dirty(
                        self.workdir, dirty_arm, job_id=jid, job=name, start=now, end=None, exit_code=None,
                        fleet_online=fleet_online, principal=principal,
                    )
                self._state_gen.bump()
            if idempotency_key and idem_digest is not None:
                self._idempotency.record(idempotency_key, idem_digest, jid, name)
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
                active.append({
                    "id": jid, "job": r["job"], "arm": r["arm"], "moving": r["moving"], "camera": r["camera"],
                    "holder": r["holder"], "purpose": r["purpose"], "started_at": r["start"], "expires_at": r["expires_at"],
                })
        return {"active": active}

    def get(self, jid: str, tail: int = 4000) -> dict | None:
        with self.lock:
            run = self.runs.get(jid)
            if run is None:
                return None
            code = run["proc"].poll()
            if code is not None:
                self._audit_locked(jid, run, code)
        data = read_tail_bytes(run["log"], tail).decode("utf-8", "replace")
        if code is not None and "_parsed_result" in run:
            structured_result, failure_bundle_id = run["_parsed_result"]
        elif code is not None or tail > 0:
            structured_result, failure_bundle_id = parse_structured_result(run["log"])
            if code is not None:
                run["_parsed_result"] = (structured_result, failure_bundle_id)
        else:
            structured_result, failure_bundle_id = None, None
        return {
            "id": jid, "job": run["job"], "argv": run["argv"], "running": code is None, "exit": code,
            "log": data, "structured_result": structured_result, "failure_bundle_id": failure_bundle_id,
        }


def make_server(bind: str, port: int, token: str, runner: Runner, viewer: str = "http://127.0.0.1:8767",
                *, machine_token: str | None = None, human_principal_id: str = ROLE_HUMAN,
                machine_principal_id: str = ROLE_MACHINE):
    if machine_token is not None and hmac.compare_digest(token.encode("utf-8"), machine_token.encode("utf-8")):
        raise ValueError("human and machine tokens must differ")

    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body, ctype="application/json", extra_headers: dict[str, str] | None = None):
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def _auth_principal(self) -> Principal | None:
            principal = authenticate_bearer(
                self.headers.get("Authorization", ""),
                human_token=token,
                machine_token=machine_token,
                human_id=human_principal_id,
                machine_id=machine_principal_id,
            )
            if principal is None:
                self._send(401, {"error": "unauthorized"})
            return principal

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True})
            if self._auth_principal() is None:
                return
            if m := re.fullmatch(r"/frame/(top|side|arm_s_top|arm_s_wrist|arm_a_wrist|arm_b_wrist)\.jpg", self.path):
                code, body, ctype, hdrs = proxy_frame(viewer, m.group(1), urlopen_fn=urllib.request.urlopen)
                return self._send(code, body, ctype, extra_headers=hdrs)
            if routed := handle_get_route(
                self.path, runner,
                whole_cell_lock_fn=_whole_cell_lock_held, session_lock_fn=_session_lock_held, depth_lock_fn=_check_depth_lock_held,
            ):
                code, body, ctype, hdrs = routed
                return self._send(code, body, ctype, extra_headers=hdrs)
            if self.path == "/queue":
                return self._send(200, runner.queue())
            if self.path == "/jobs":
                return self._send(200, [runner.get(j, 0) for j in list(runner.runs)[-50:]])
            if (m := re.fullmatch(r"/jobs/([\w-]+)", self.path)) and (run := runner.get(m.group(1))):
                return self._send(200, run)
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if (principal := self._auth_principal()) is None:
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
            out = runner.start(m.group(1), params, principal=principal, idempotency_key=self.headers.get("Idempotency-Key"))
            self._send(out.pop("code"), out)

    return ThreadingHTTPServer((bind, port), Handler)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8781)
    ap.add_argument("--token-file", type=Path, default=Path.home() / ".config/rosy/cell-job-api.token")
    ap.add_argument("--human-token-file", type=Path, default=(os.environ.get("ROSY_CELL_JOB_HUMAN_TOKEN_FILE") or None))
    ap.add_argument("--machine-token-file", type=Path, default=(os.environ.get("ROSY_CELL_JOB_MACHINE_TOKEN_FILE") or None))
    ap.add_argument("--fleet-r-url", default=(os.environ.get("ROSY_FLEET_R_URL") or None))
    ap.add_argument("--fleet-token-file", type=Path, default=(os.environ.get("ROSY_FLEET_TOKEN_FILE") or None))
    ap.add_argument("--ca-file", type=Path, default=(os.environ.get("ROSY_FLEET_CA_FILE") or None))
    a = ap.parse_args()
    human_token = read_token(a.human_token_file or a.token_file)
    machine_token = read_token(a.machine_token_file) if a.machine_token_file else None
    runner = Runner(a.workdir.expanduser(), fleet_r_url=a.fleet_r_url, fleet_token_file=a.fleet_token_file, ca_file=a.ca_file)
    server = make_server(a.bind, a.port, human_token, runner, machine_token=machine_token)
    print(f"cell job API on {a.bind}:{a.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
