"""Calibration jobs, status and AI incident assessments (D-1035). Called from calibration_web.Handler; off without --cells.

The app never writes cell values: a job is the engine (`cell_calibrate.py`) run under the arm lease, and an incident
is cleared only by `omx_incident.py clear` after the measured conditions (no session, no foreign lease) pass.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

OPERATE = "calibration.operate"
STEPS = {"check": [], "depth-verify": ["--only", "depth-verify", "--verify"], "pivot-near": ["--only", "pivot-near"],
         "remap": ["--only", "remap"], "surface": ["--only", "surface"], "post-eval": []}
MOVING = {"pivot-near", "remap", "surface", "post-eval"}  # D-911: a person at the power switch
TARGET = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}:-?\d+(\.\d+)?,-?\d+(\.\d+)?")  # never starts with '-'
ARM = re.compile(r"[A-Za-z0-9_-]{1,32}")
SITE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*(?::[A-Za-z0-9_-]+)?")
JOB_ID = re.compile(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{6}")
TASK_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}")
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


def failure_line(text: str):
    """The engine's exit message on a failed job: the last log line that is not JSON."""
    for line in reversed(text.strip().splitlines()):
        if line.strip() and last_json(line) is None:
            return line.strip()[:500]
    return None


def site_point(name, site):
    point = site.get("place")
    if (SITE.fullmatch(name) and isinstance(point, list) and len(point) == 2
            and all(type(v) in (int, float) and math.isfinite(v) for v in point)):
        return point
    return None


def post_eval_point(name, site, arm):
    # The deployed engine takes a single site:x,y argument; a colon in the name is ambiguous.
    if not isinstance(name, str) or ":" in name or not isinstance(site, dict):
        return None
    point = site_point(name, site)
    if point is None:
        return None
    try:
        from cell_site_target import resolve_cell_ab_site
        resolved = resolve_cell_ab_site(name) or resolve_cell_ab_site(name, 1)
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return None
    return point if resolved is None or arm in resolved["arms"] else None


def map_grade(key, record):
    if key.endswith("~coarse") or "z_view" in record or record.get("coarse") or record.get("marks") in ("jaw", "tcp"):
        return "coarse"
    def vector(row, size):
        return isinstance(row, list) and len(row) == size and all(type(v) in (float, int) and math.isfinite(v) for v in row)
    h, points, residual = record.get("homography"), record.get("points"), record.get("loo_error_mm")
    if (isinstance(h, list) and len(h) == 3 and all(vector(row, 3) for row in h)
            and isinstance(record.get("measured"), str) and record["measured"].strip()
            and isinstance(residual, dict) and vector([residual.get("mean"), residual.get("max")], 2)
            and isinstance(points, list) and len(points) >= 5 and all(isinstance(p, dict)
            and vector(p.get("pixel"), 2) and vector(p.get("arm_m"), 2) for p in points)):
        return "fine"
    return "unknown"


def process_stamp(pid):
    """Kernel process start ticks survive exec and distinguish a reused PID."""
    try:
        row = Path(f"/proc/{int(pid)}/stat").read_text()
        return int(row.rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, TypeError, IndexError):
        return None


def can_remeasure_surface(name, site, arm):
    from cell_recovery_cargo import fixed_base_geometry, fixed_site

    yaw = site.get("yaw_deg")
    return (site_point(name, site) is not None and fixed_site(name, arm) and fixed_base_geometry(site)
            and type(yaw) in (int, float) and math.isfinite(yaw))


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
        self.registry = Path(cells_path).resolve()
        self.fleet_console_url = None
        url = cells.get("fleet_cell_console_url")
        if isinstance(url, str):
            try:
                parts = urlsplit(url)
                if parts.scheme == "https" and parts.hostname and not parts.username and not parts.password:
                    self.fleet_console_url = url
            except ValueError:
                pass
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

    def check_config_path(self, arm, default):
        route_path = self.arms[arm].get("route_config")
        if not isinstance(route_path, str) or not Path(route_path).is_absolute():
            return default
        path = Path(route_path)
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default
        if not isinstance(profile, dict) or profile.get("arm_id") != arm:
            return default
        preflight = profile.get("preflight")
        route = preflight.get("check_route") if isinstance(preflight, dict) else None
        if isinstance(route, list) and len(route) == 2 and all(isinstance(s, str) and s.strip() for s in route):
            return path
        return default

    def env(self, arm, owner):
        return {**os.environ, **self.arms[arm].get("env", {}), "ROSY_ARM_LEASE_OWNER": owner,
                "ROSY_CALIBRATION_REGISTRY": str(self.registry)}

    # --- status -------------------------------------------------------------------------------------------------
    def route_sites(self, arm):
        if arm not in ("arm_a", "arm_b") or not self.arms[arm].get("route_config"):
            return []
        layout = json.loads((self.tools / "shared/web/cell-site-map.json").read_text(encoding="utf-8"))
        return [tier["item"] for zone in layout["zones"] for slot in zone["slots"]
                if arm in slot["arms"] for tier in slot["tiers"]]

    def site_status(self, config, arm):
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
            if not isinstance(site, dict):
                continue
            src = site.get("map_from", name)
            key = next((k for k in (name, f"{name}~coarse", src, f"{src}~coarse") if sites.get(k)), None)
            record = sites.get(key)
            grade = map_grade(key, record) if isinstance(record, dict) else "unknown"
            record = record if isinstance(record, dict) else {}
            summary = None if key is None else {
                "points": len(record["points"]) if isinstance(record.get("points"), list) else 0, "loo_error_mm": record.get("loo_error_mm"),
                "grade": grade, "coarse": grade == "coarse", "inherited": key not in (name, f"{name}~coarse"),
                "sha": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:12]}
            out[name] = {"map": summary, "surface_z": site.get("surface_z"), "map_from": site.get("map_from"),
                         "can_post_eval": config.get("arm_id") == arm and post_eval_point(name, site, arm) is not None,
                         "place_xy_m": site_point(name, site), "can_remeasure_surface": can_remeasure_surface(name, site, config.get("arm_id")),
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
                sites = self.site_status(self.arm_config(arm)[1], arm)
            except (OSError, ValueError) as exc:
                sites = {"error": str(exc)}
            arms[arm] = {"lease": leases.get(arm), "incident": incident if incident is not None else {"error": err},
                         "sites": sites}
            try:
                arms[arm]["route_sites"] = self.route_sites(arm)
            except (OSError, ValueError, KeyError, TypeError):
                arms[arm]["route_sites"] = []
        return {"revision": self.revision(), "leases_error": leases.get("error"), "arms": arms,
                "fleet_cell_console_url": self.fleet_console_url}

    # --- jobs ---------------------------------------------------------------------------------------------------
    def job_file(self, job_id, ext="json"):
        return self.work / "jobs" / f"{job_id}.{ext}"

    def running(self, arm):
        return [row["id"] for row in self.jobs() if row.get("arm") == arm and row.get("status") == "running"]

    def worker_status(self, record):
        if record.get("status") == "running":
            stamp = process_stamp(record.get("pid"))
            reused = stamp is not None and record.get("pid_start_ticks") not in (None, stamp)
            if reused or not record.get("pid") or not self.lease().live(record):
                return {**record, "status": "interrupted"}
        return record

    def start(self, body, by, owner_id=None):
        arm, step, targets = body.get("arm"), body.get("step"), body.get("targets", [])
        if arm not in self.arms or step not in STEPS:
            return 422, {"error": f"arm은 {sorted(self.arms)}, step은 {sorted(STEPS)} 중 하나여야 합니다."}
        if not isinstance(targets, list) or not all(isinstance(t, str) and TARGET.fullmatch(t) for t in targets):
            return 422, {"error": "targets는 'site:x,y' 문자열 목록이어야 합니다."}
        if step in MOVING and body.get("person_at_switch") is not True:
            return 422, {"error": "팔이 움직이는 단계는 전원 스위치 앞의 사람이 필요합니다(person_at_switch)."}
        if "remeasure" in body and (step != "remap" or body["remeasure"] is not True):
            return 422, {"error": "지도 강제 재측정(remeasure: true)은 재매핑 작업에서만 선택할 수 있습니다."}
        route = body.get("route")
        if "task_id" in body and (step != "check" or not (route or body.get("supply_route") is True)
                or not isinstance(body["task_id"], str) or not TASK_REF.fullmatch(body["task_id"])):
            return 422, {"error": "경로 점검에 연결할 Fleet 작업 ID를 확인하세요."}
        if "route" in body:
            if (step != "check" or targets or "site" in body or arm not in ("arm_a", "arm_b")
                    or not isinstance(route, list) or len(route) != 2 or route[0] == route[1]
                    or not all(isinstance(name, str) for name in route)):
                return 422, {"error": "A·B 경로 점검에는 서로 다른 출발칸과 도착칸이 필요합니다."}
            try:
                config_path = Path(self.arms[arm]["route_config"]).expanduser()
                config = json.loads(config_path.read_text(encoding="utf-8"))
                allowed = self.route_sites(arm)
            except (OSError, ValueError, KeyError, TypeError):
                return 409, {"error": "이 팔의 이송 실행기 설정 또는 칸 목록을 읽을 수 없습니다."}
            if not isinstance(config, dict) or config.get("arm_id") != arm or not all(site in allowed for site in route):
                return 422, {"error": "이송 설정과 두 칸이 선택한 팔에 속하는지 확인하세요."}
        else:
            config_path, config = self.arm_config(arm)
        if "supply_route" in body:
            from core_common.profile import LEGACY_VEHICLE_SITE

            if (body["supply_route"] is not True or arm != "arm_s" or step != "check" or targets
                    or route or "site" in body or config.get("arm_id") != arm):
                return 422, {"error": "공급 경로 점검에는 S팔 실행기 설정이 필요합니다."}
            for name in (LEGACY_VEHICLE_SITE, "belt"):
                site = (config.get("sites") or {}).get(name)
                xy = site_point(name, site) if isinstance(site, dict) else None
                if xy is None:
                    return 422, {"error": f"S팔 공급 경로의 {name} 중심 XY를 검증해 등록하세요."}
                targets.append(f"{name}:{xy[0]},{xy[1]}")
        if step == "check" and not targets and not route and "supply_route" not in body:
            config_path = self.check_config_path(arm, config_path)
        argv = [self.python, self.engine("cell_calibrate.py"), "--config", str(config_path),
                "check" if step == "check" else "auto", *STEPS[step]]
        if targets:
            argv += ["--targets", *targets]
        if route:
            argv += ["--route", *route]
        if step == "post-eval":
            name = body.get("site")
            site = (config.get("sites") or {}).get(name) if isinstance(name, str) else None
            if (set(body) != {"arm", "step", "site", "person_at_switch"} or config.get("arm_id") != arm
                    or not config.get("calibration_path")):
                return 422, {"error": "팔과 등록된 측정 지점만 선택하세요."}
            point = post_eval_point(name, site, arm)
            if point is None:
                return 422, {"error": "이 팔에 중심 좌표가 등록된 지점을 선택하세요."}
            targets = [f"{name}:{point[0]},{point[1]}"]
            argv = [self.python, self.engine("cell_post_eval.py"), "--config", str(config_path), "--targets", *targets]
        elif "site" in body or step == "surface":
            name = body.get("site")
            site = (config.get("sites") or {}).get(name) if isinstance(name, str) else None
            if (step != "surface" or targets or config.get("arm_id") != arm or not isinstance(site, dict)
                    or not can_remeasure_surface(name, site, arm)):
                return 422, {"error": "등록된 면 측정 지점을 선택하세요."}
            if body.get("surface_clear") is not True:
                return 422, {"error": "선택한 고정 지점과 팔 이동 경로가 비어 있는지 확인하세요."}
            argv += ["--remeasure-surface", name, "--surface-clear"]
        if body.get("remeasure") is True:
            argv += ["--remeasure-map"]
        if step in MOVING:
            argv += ["--commissioning", "--person-at-switch"]
        if step in MOVING and self.arms[arm].get("session"):
            argv = [self.arms[arm]["session"], *argv]
        job_id = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:6]}"
        owner = f"calibration-web:{owner_id or by}:{job_id}"
        (self.work / "jobs").mkdir(parents=True, exist_ok=True)
        lease = self.lease()
        with _lock:
            for previous in self.jobs():
                if previous.get("arm") != arm:
                    continue
                if previous.get("status") == "running":
                    return 409, {"error": f"{arm}에서 작업이 이미 돌고 있습니다: {previous['id']}"}
                if previous.get("status") == "interrupted" and previous.get("lease_owner", "").endswith(f":{previous['id']}"):
                    lease.release(arm, previous["lease_owner"], expected_pid=previous["pid"])
            try:
                lease.claim(arm, owner, f"calibration {step}", 1800, None, self.revision())
            except lease.LeaseHeld as exc:
                return 409, {"error": str(exc)}
            record = {"id": job_id, "arm": arm, "step": step, "targets": targets, "by": by, "revision": self.revision(),
                      "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pid": None, "status": "running"}
            proc = None
            if route:
                record.update(route=route, route_config=config_path.name)
            if body.get("supply_route") is True:
                record.update(supply_route=True, route_config=config_path.name)
            if "task_id" in body:
                record["task_id"] = body["task_id"]  # Advisory link provenance, never a Fleet command.
            if "site" in body:
                record["site"] = body["site"]
            if step == "surface":
                record["surface_clear"] = True
            try:
                proc = self.spawn(argv, str(config_path.parent), self.env(arm, owner), self.job_file(job_id, "log"))
                # the lease follows the engine, not this server: a server restart must not free a moving arm
                bound = lease.claim(arm, owner, f"calibration {step}", 1800, proc.pid, self.revision())
                record.update(pid=proc.pid, boot_id=bound.get("boot_id"), pid_start_ticks=process_stamp(proc.pid), lease_owner=owner)
                self.write(record)
            except BaseException as exc:  # no finish thread will run: stop the engine first, then free the lease
                if proc is not None:
                    proc.terminate()
                    proc.wait(timeout=30)
                lease.release(arm, owner, expected_pid=record["pid"])
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
        if code != 0:
            record["error"] = failure_line(text)
        self.write(record)
        try:
            self.lease().release(record["arm"], owner, expected_pid=proc.pid)
        except Exception:  # noqa: BLE001 - the lease expires by itself; the record is already final
            pass

    def jobs(self):
        rows = []
        for file in (self.work / "jobs").glob("*.json"):
            try:
                rows.append(self.worker_status(json.loads(file.read_text(encoding="utf-8"))))
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
        return self.worker_status(record)

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
        with _lock:  # no job of this app can start between the checks and the clear (review 2026-11-17)
            return self._clear(arm, by)

    def _clear(self, arm, by):
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

