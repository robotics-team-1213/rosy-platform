"""Calibration jobs, status and AI incident assessments (D-1035). Called from calibration_web.Handler; off without --cells.

The app never writes cell values: a job is the engine (`cell_calibrate.py`) run under the arm lease, and an incident
is cleared only by `omx_incident.py clear` after the measured conditions (no session, no foreign lease) pass.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

OPERATE = "calibration.operate"
STEPS = {"check": [], "depth-verify": ["--only", "depth-verify", "--verify"], "pivot-near": ["--only", "pivot-near"],
         "remap": ["--only", "remap"]}
MOVING = {"pivot-near", "remap"}  # D-911: a person at the power switch
TARGET = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}:-?\d+(\.\d+)?,-?\d+(\.\d+)?")  # never starts with '-'
ARM = re.compile(r"[A-Za-z0-9_-]{1,32}")
JOB_ID = re.compile(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{6}")
CLEAR_FRESH_S = 600
REASONS_MAX = 2000
EVIDENCE_KINDS = {"frame", "joints", "torque"}
BODY_MAX = 16384
_lock = threading.Lock()  # the lease claim and the job record are written together; assessments append under it too


def last_json(text: str):
    for line in reversed(text.strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def spawn_process(argv, cwd, env, log: Path):
    with open(log, "wb") as out:
        return subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT)


def session_running(arm: str) -> bool:
    """A record_session process for the arm, from /proc (Linux only; elsewhere nothing is known, so False)."""
    for cmd in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            args = cmd.read_bytes().decode(errors="replace").replace("\0", " ")
        except OSError:
            continue
        if "record_session.py" in args and (f"--arm {arm} " in f"{args} " or f"--arm={arm} " in f"{args} "):
            return True
    return False


def run_tool(argv, timeout=30, env=None):
    """(parsed last JSON line or None, error string); the engine tools print one JSON line."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    out = last_json(done.stdout)
    return out, "" if done.returncode == 0 and out is not None else (done.stderr or done.stdout)[-300:] or f"exit {done.returncode}"


class Jobs:
    def __init__(self, cells_path: Path, spawn=spawn_process, probe=session_running, incident_tool=run_tool):
        cells = json.loads(Path(cells_path).read_text(encoding="utf-8"))
        self.tools = Path(cells["tools"]).expanduser()
        self.python = cells["python"]
        self.work = Path(cells["work"]).expanduser()
        self.arms = cells["arms"]
        self.spawn, self.probe, self.incident_tool = spawn, probe, incident_tool
        self.threads: list[threading.Thread] = []
        self._lease = None

    # --- helpers ------------------------------------------------------------------------------------------------
    def engine(self, name):
        return str(self.tools / "deploy/robot/omx" / name)

    def lease(self):  # lazy: the app starts without the lease module
        if self._lease is None:
            file = self.tools / "deploy/robot/omx/cell_arm_lease.py"
            spec = importlib.util.spec_from_file_location("cell_arm_lease", file)
            self._lease = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self._lease)
        return self._lease

    def revision(self):
        try:
            return (self.tools / "REVISION").read_text(encoding="utf-8").strip()
        except OSError:
            return None

    def arm_config(self, arm):
        path = Path(self.arms[arm]["config"]).expanduser()
        return path, json.loads(path.read_text(encoding="utf-8"))

    def env(self, arm, owner):
        return {**os.environ, **self.arms[arm].get("env", {}), "ROSY_ARM_LEASE_OWNER": owner}

    # --- status -------------------------------------------------------------------------------------------------
    def site_status(self, config):
        path = config.get("calibration_path")
        if not path:
            return {}
        path = Path(path).expanduser()
        try:
            sites = json.loads(path.read_text(encoding="utf-8")).get("sites", {})
        except (OSError, ValueError):
            sites = {}
        try:
            regions = json.loads(path.with_suffix(".bias.json").read_text(encoding="utf-8")).get("regions", [])
        except (OSError, ValueError):
            regions = []
        out = {}
        for name, site in (config.get("sites") or {}).items():
            src = site.get("map_from", name)
            record = sites.get(name) or sites.get(f"{name}~coarse") or sites.get(src) or sites.get(f"{src}~coarse")
            summary = None if record is None else {
                "points": len(record.get("points", [])), "loo_error_mm": record.get("loo_error_mm"),
                "sha": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:12]}
            out[name] = {"map": summary, "surface_z": site.get("surface_z"), "map_from": site.get("map_from"),
                         "bias": [{k: r.get(k) for k in ("point_m", "bias_mm", "kind", "n", "rms_mm", "measured")}
                                  for r in regions if r.get("site") == name]}
        return out

    def status(self):
        arms = {}
        try:
            leases = self.lease().status()
        except Exception as exc:  # noqa: BLE001 - a missing lease module must not hide the rest
            leases = {"error": str(exc)}
        for arm in self.arms:
            incident, err = self.incident_tool([self.python, self.engine("omx_incident.py"), "status", "--arm", arm], 10)
            try:
                sites = self.site_status(self.arm_config(arm)[1])
            except (OSError, ValueError) as exc:
                sites = {"error": str(exc)}
            arms[arm] = {"lease": leases.get(arm), "incident": incident if incident is not None else {"error": err},
                         "sites": sites}
        return {"revision": self.revision(), "leases_error": leases.get("error"), "arms": arms}

    # --- jobs ---------------------------------------------------------------------------------------------------
    def job_file(self, job_id, ext="json"):
        return self.work / "jobs" / f"{job_id}.{ext}"

    def running(self, arm):
        """Jobs on the arm whose engine process is still alive (one job per arm, review 2026-11-17)."""
        alive = []
        for record in self.jobs():
            if record.get("arm") == arm and record.get("status") == "running" and record.get("pid"):
                try:
                    os.kill(record["pid"], 0)
                except PermissionError:
                    pass
                except (OSError, ValueError):
                    continue
                alive.append(record["id"])
        return alive

    def start(self, body, by, owner_id=None):
        arm, step, targets = body.get("arm"), body.get("step"), body.get("targets", [])
        if arm not in self.arms or step not in STEPS:
            return 422, {"error": f"arm은 {sorted(self.arms)}, step은 {sorted(STEPS)} 중 하나여야 합니다."}
        if not isinstance(targets, list) or not all(isinstance(t, str) and TARGET.fullmatch(t) for t in targets):
            return 422, {"error": "targets는 'site:x,y' 문자열 목록이어야 합니다."}
        if step in MOVING and body.get("person_at_switch") is not True:
            return 422, {"error": "팔이 움직이는 단계는 전원 스위치 앞의 사람이 필요합니다(person_at_switch)."}
        owner = f"calibration-web:{owner_id or by}"  # the account id: two people may share a display name
        config_path, _ = self.arm_config(arm)
        argv = [self.python, self.engine("cell_calibrate.py"), "--config", str(config_path),
                "check" if step == "check" else "auto", *STEPS[step]]
        if targets:
            argv += ["--targets", *targets]
        if step in MOVING:
            argv += ["--commissioning", "--person-at-switch"]
        if self.arms[arm].get("session"):
            argv = [self.arms[arm]["session"], *argv]
        job_id = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:6]}"
        (self.work / "jobs").mkdir(parents=True, exist_ok=True)
        lease = self.lease()
        with _lock:
            if self.running(arm):
                return 409, {"error": f"{arm}에서 작업이 이미 돌고 있습니다: {', '.join(self.running(arm))}"}
            try:
                lease.claim(arm, owner, f"calibration {step}", 1800, None, self.revision())
            except lease.LeaseHeld as exc:
                return 409, {"error": str(exc)}
            record = {"id": job_id, "arm": arm, "step": step, "targets": targets, "by": by, "revision": self.revision(),
                      "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pid": None, "status": "running"}
            proc = None
            try:
                proc = self.spawn(argv, str(config_path.parent), self.env(arm, owner), self.job_file(job_id, "log"))
                # the lease follows the engine, not this server: a server restart must not free a moving arm
                lease.claim(arm, owner, f"calibration {step}", 1800, proc.pid, self.revision())
                record["pid"] = proc.pid
                self.write(record)
            except BaseException as exc:  # no finish thread will run: stop the engine first, then free the lease
                if proc is not None:
                    proc.terminate()
                    proc.wait(timeout=30)
                lease.release(arm, owner)
                if isinstance(exc, Exception):
                    return 500, {"error": f"엔진을 시작하지 못했습니다: {exc}"}
                raise
        thread = threading.Thread(target=self.finish, args=(proc, record, owner), daemon=True)
        thread.start()
        self.threads.append(thread)
        return 202, record

    def write(self, record):
        file = self.job_file(record["id"])
        tmp = file.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, file)

    def finish(self, proc, record, owner):
        code = proc.wait()
        try:
            text = self.job_file(record["id"], "log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        record.update(exit_code=code, ended=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      result=last_json(text), status="done" if code == 0 else "failed")
        self.write(record)
        try:
            self.lease().release(record["arm"], owner)
        except Exception:  # noqa: BLE001 - the lease expires by itself; the record is already final
            pass

    def jobs(self):
        rows = []
        for file in (self.work / "jobs").glob("*.json"):
            try:
                rows.append(json.loads(file.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(rows, key=lambda r: r.get("started", ""), reverse=True)

    def job(self, job_id):
        if not JOB_ID.fullmatch(job_id):
            return None
        try:
            record = json.loads(self.job_file(job_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            record["log_tail"] = self.job_file(job_id, "log").read_text(encoding="utf-8", errors="replace")[-4000:]
        except OSError:
            record["log_tail"] = ""
        return record

    # --- assessments and incident clear -------------------------------------------------------------------------
    def assessments(self):
        try:
            lines = (self.work / "assessments.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows = []
        for line in lines:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def evidence_ok(self, evidence) -> str | None:
        """None when every item is a file under <work>/evidence whose sha256 matches, with at least one camera frame
        and one joint reading (review 2026-11-17: refs were taken on trust); else why not."""
        root = (self.work / "evidence").resolve()
        for item in evidence:
            path = (root / item["ref"]).resolve()
            if root not in path.parents or not path.is_file():
                return f"근거 파일이 없습니다: {item['ref']}"
            if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
                return f"근거 해시가 맞지 않습니다: {item['ref']}"
        kinds = {item["kind"] for item in evidence}
        return None if {"frame", "joints"} <= kinds else "카메라 프레임과 관절 상태 근거가 모두 필요합니다."

    def assess(self, body, by):
        arm, verdict, reasons, evidence = body.get("arm"), body.get("verdict"), body.get("reasons"), body.get("evidence")
        model = body.get("model")
        ok = (arm in self.arms and verdict in ("clear", "hold") and isinstance(reasons, str) and 0 < len(reasons) <= REASONS_MAX
              and isinstance(model, str) and 0 < len(model) <= 120 and isinstance(evidence, list) and evidence
              and all(isinstance(e, dict) and e.get("kind") in EVIDENCE_KINDS and isinstance(e.get("ref"), str) and e["ref"]
                      and isinstance(e.get("sha256"), str) for e in evidence))
        if not ok:
            return 422, {"error": "arm, verdict(clear|hold), model, reasons, evidence[{kind,ref,sha256}]가 필요합니다."}
        why = self.evidence_ok(evidence)
        if why:
            return 422, {"error": why}
        row = {"id": uuid.uuid4().hex[:12], "arm": arm, "verdict": verdict, "model": model, "reasons": reasons,
               "evidence": evidence, "by": by, "at": time.time()}
        with _lock:
            self.work.mkdir(parents=True, exist_ok=True)
            with open(self.work / "assessments.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return 201, row

    def clear(self, arm, by):
        if arm not in self.arms:
            return 404, {"error": "없는 팔입니다."}
        mine = [a for a in self.assessments() if a.get("arm") == arm]
        newest = max(mine, key=lambda a: a.get("at", 0), default=None)
        if not newest or newest["verdict"] != "clear" or time.time() - newest["at"] > CLEAR_FRESH_S:
            return 409, {"error": "10분 안의 clear 판정이 가장 최근 판정이어야 합니다."}
        held = (self.lease().status(arm) or {}).get(arm)
        if held and held.get("live"):  # anyone's, the clearer's own running job included (review 2026-11-17)
            return 409, {"error": f"{held['owner']}의 리스가 살아 있습니다({held.get('purpose') or '-'})."}
        if self.running(arm) or self.probe(arm):
            return 409, {"error": "이 팔에서 작업이나 record_session이 실행 중입니다."}
        out, err = self.incident_tool([self.python, self.engine("omx_incident.py"), "clear", "--arm", arm, "--note",
                                       f"ai-assessment {newest['id']} by {newest['by']}"], 60, self.env(arm, f"calibration-web:{by}"))
        if out is None:
            return 502, {"error": f"incident 해제 실패: {err}"}
        return 200, out


def _body(handler):
    try:
        length = int(handler.headers.get("Content-Length", 0))
        if not 0 < length <= BODY_MAX:
            raise ValueError
        body = json.loads(handler.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError
        return body
    except (ValueError, UnicodeDecodeError):
        return None


def handle(handler, method, path):
    """Route one /api/calibration/{status,jobs,assessments,incidents} request; Handler.dispatch calls this."""
    jobs, claims = handler.jobs, handler.claims()
    if handler.account and not claims:
        return handler.json(401, {"error": "Rosy Account로 로그인해야 합니다."})
    parts = path.removeprefix("/api/calibration/").strip("/").split("/")
    if method == "GET":
        if parts == ["status"]:
            return handler.json(200, jobs.status())
        if parts == ["jobs"]:
            return handler.json(200, {"jobs": jobs.jobs()})
        if len(parts) == 2 and parts[0] == "jobs":
            record = jobs.job(parts[1])
            return handler.json(200 if record else 404, record or {"error": "없는 작업입니다."})
        return handler.json(404, {"error": "없는 경로입니다."})
    if method != "POST" or not (parts in (["jobs"], ["assessments"])
                                or (len(parts) == 3 and parts[0] == "incidents" and parts[2] == "clear")):
        return handler.json(404, {"error": "없는 경로입니다."})
    if not handler.account:
        return handler.json(403, {"error": "Account 설정이 없어 읽기 전용입니다."})
    if not handler.same_origin():
        return handler.json(403, {"error": "등록된 출처에서만 요청할 수 있습니다."})
    if not handler.can_operate(claims):
        return handler.json(403, {"error": f"{OPERATE} 권한이 필요합니다."})
    by = handler.by_name(claims)
    if parts[0] == "incidents":
        return handler.json(*jobs.clear(parts[1], by))
    body = _body(handler)
    if body is None:
        return handler.json(422, {"error": "JSON 본문이 필요합니다."})
    return handler.json(*(jobs.start(body, by, getattr(claims, "sub", None)) if parts[0] == "jobs" else jobs.assess(body, by)))

