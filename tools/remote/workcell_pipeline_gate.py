"""Read-only workcell pipeline gate for one or two Fleet hosts (cell and R): workcell arm
observations twice 3 s apart (fake marker, freshness, honest unknown), cell→R mirror lag,
every camera frame through a signed vision lease, and R pipeline cell tasks. MISSING lines
(an arm honestly unknown, a boot-default arm-live state) are informational and never fail
the gate; any FAIL exits 1. The client refuses every write: only GET and the frame lease
POST /api/fleet/vision/lease go out.

    python tools/remote/workcell_pipeline_gate.py --cell-url URL [--r-url URL] \
        (--cookie-file F | --bearer-file F) --ca-file F [--json-out PATH]

The operator credential is the first non-empty line of a cookie file (--cookie-file) or a
bearer token file (--bearer-file) and is sent only to the fleet URLs given. TLS is always
verified against the PEM anchor in --ca-file: the operator cookie is never sent over
unverified TLS. --json-out writes the result
document (schema rosy.workcell-pipeline-gate.v1) for Monitoring.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "rosy.workcell-pipeline-gate.v1"
FAKE_EPOCHS = {"a1b2c3d4e5f60718293a4b5c6d7e8f90"}
FAKE_SESSIONS = {"e957f879-5ec9-48c1-ad98-d642fa8a5a7e"}
OBSERVATION_GAP_S = 3.0
SOURCE_AGE_MAX_S = 2.0
MIRROR_LAG_MAX_S = 3.0
FRAME_MIN_BYTES = 1000
FRAME_AGE_MAX_MS = 3000
LEASE_PATH = "/api/fleet/vision/lease"
CELL_TASKS_PATH = "/api/fleet/pipeline/cell-tasks"
OBSERVATIONS_PATH = "/api/fleet/workcell-observations"
BOOT_DEFAULT_SOURCE = "boot_default"
DEFAULT_TIMEOUT_S = 15.0


class GateError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is refused: the operator session must not be sent anywhere but the fleet asked."""

    def redirect_request(self, *args, **kwargs):
        return None


def tls_context(ca_file: str) -> ssl.SSLContext:
    """Chain-verified TLS against the given PEM anchor (the served leaf may be the anchor);
    the name is not checked, the anchor pins the fleet. Verification is never skipped."""
    if not ca_file:
        raise GateError("HTTPS fleets need --ca-file <certificate or CA PEM>")
    try:
        context = ssl.create_default_context(cafile=ca_file)
    except (OSError, ValueError) as error:
        raise GateError(f"cannot load the TLS anchor {ca_file}: {error}") from None
    context.check_hostname = False
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return context


def auth_header(cookie_file: str | None = None, bearer_file: str | None = None) -> tuple[str, str]:
    """(header name, value) from the first non-empty line of the named operator file."""
    if bool(cookie_file) == bool(bearer_file):
        raise GateError("pass exactly one of --cookie-file / --bearer-file")
    raw = Path(cookie_file or bearer_file).read_text(encoding="utf-8-sig").strip()
    value = raw.splitlines()[0].strip() if raw else ""
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()
    if bearer_file and value.lower().startswith("bearer "):
        value = value[7:].strip()
    if not value:
        raise GateError(f"{cookie_file or bearer_file} has no credential line")
    return ("Cookie", value) if cookie_file else ("Authorization", f"Bearer {value}")


class FleetClient:
    """Read-only JSON client for one Fleet: any GET, and POST only for the signed vision lease."""

    def __init__(self, name: str, base_url: str, auth: tuple[str, str] | None = None,
                 timeout: float = DEFAULT_TIMEOUT_S, context: ssl.SSLContext | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._auth = auth
        self._timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                   urllib.request.HTTPSHandler(context=context),
                                                   _NoRedirect())

    def call(self, method: str, path: str, body: dict | None = None,
             bearer: str | None = None) -> tuple[int, bytes, object, str | None]:
        """(status, raw body, headers, transport error). Status 0 with an error on transport failure."""
        if method != "GET" and not (method == "POST" and path == LEASE_PATH):
            raise GateError(f"read-only gate refuses {method} {path}")
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self._auth is not None:
            request.add_header(*self._auth)
        if bearer is not None:
            request.add_header("Authorization", "Bearer " + bearer)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                return response.status, response.read(), response.headers, None
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers, None
        except (urllib.error.URLError, OSError) as error:
            return 0, b"", {}, str(getattr(error, "reason", error))[:160]


def parse_observations(raw: bytes) -> tuple[dict, list[str]]:
    """(arms by source_id, camera source ids) of a workcell-observations body."""
    workcells = json.loads(raw).get("workcells") or []
    arms = {a["source_id"]: a for c in workcells for a in (c.get("arms") or []) if isinstance(a, dict)}
    cameras = [c["source_id"] for w in workcells for c in (w.get("cameras") or []) if isinstance(c, dict)]
    return arms, cameras


def fetch_observations(client: FleetClient) -> tuple[int, dict, list[str], str | None]:
    """One observation round: (status, arms, cameras, error)."""
    status, raw, _headers, error = client.call("GET", OBSERVATIONS_PATH)
    if error is not None or status != 200:
        return status, {}, [], error
    try:
        arms, cameras = parse_observations(raw)
    except ValueError:
        return status, {}, [], "unreadable JSON body"
    return status, arms, cameras, error


def observation_rows(host: str, first: tuple, second: tuple) -> list[dict]:
    """not_fake plus fresh/honest rows for every arm of the second observation round."""
    ok = first[0] == 200 and second[0] == 200
    row = {"check": f"{host}.observations_api", "result": "PASS" if ok else "FAIL",
           "status": [first[0], second[0]]}
    if not ok:
        row["error"] = first[3] or second[3]
    rows = [row]
    for sid, arm in sorted(second[1].items()):
        prev = first[1].get(sid, {})
        health = arm.get("motor_health") or {}
        fake = arm.get("epoch") in FAKE_EPOCHS or health.get("session_id") in FAKE_SESSIONS
        rows.append({"check": f"{host}.{sid}.not_fake", "result": "FAIL" if fake else "PASS",
                     "epoch": arm.get("epoch")})
        if arm.get("fresh"):
            advanced = ((arm.get("epoch"), arm.get("sequence") or 0, arm.get("captured_at") or 0)
                        != (prev.get("epoch"), prev.get("sequence") or 0, prev.get("captured_at") or 0)
                        and (arm.get("captured_at") or 0) > (prev.get("captured_at") or 0))
            age = arm.get("source_age_s")
            age_ok = isinstance(age, (int, float)) and 0 <= age <= SOURCE_AGE_MAX_S
            rows.append({"check": f"{host}.{sid}.fresh_and_advancing",
                         "result": "PASS" if advanced and age_ok else "FAIL",
                         "sequence": [prev.get("sequence"), arm.get("sequence")],
                         "captured_at": [prev.get("captured_at"), arm.get("captured_at")],
                         "source_age_s": age})
        else:
            rows.append({"check": f"{host}.{sid}.honest_unknown",
                         "result": "PASS" if arm.get("positions") is None else "FAIL",
                         "note": "no live sample (arm idle or publisher missing)"})
            rows.append({"check": f"{host}.{sid}.live", "result": "MISSING", "why": "fresh=false"})
    return rows


def mirror_rows(cell_arms: dict, r_arms: dict) -> list[dict]:
    """cell→R mirror: an arm live in the cell must be live in R within the lag bound."""
    rows = []
    for sid, cell in sorted(cell_arms.items()):
        if not cell.get("fresh"):
            continue
        r = r_arms.get(sid) or {}
        lag = (cell.get("captured_at") or 0) - (r.get("captured_at") or 0)
        ok = bool(r.get("fresh")) and abs(lag) <= MIRROR_LAG_MAX_S
        rows.append({"check": f"mirror.{sid}", "result": "PASS" if ok else "FAIL",
                     "r_fresh": bool(r.get("fresh")), "lag_s": round(lag, 3),
                     "sequence": [cell.get("sequence"), r.get("sequence")]})
    return rows


def same_origin(frame_path: str, base_url: str) -> bool:
    """A frame_path may be a path on the fleet or an absolute URL of the same origin, nothing else."""
    path = urllib.parse.urlsplit(frame_path)
    if not path.scheme and not path.netloc:
        return frame_path.startswith("/")
    base = urllib.parse.urlsplit(base_url)
    return (path.scheme, path.netloc) == (base.scheme, base.netloc)


def camera_rows(client: FleetClient, cameras: list[str]) -> list[dict]:
    """One signed lease per camera, then the frame itself: same origin, big enough, fresh enough."""
    rows = []
    for source in cameras:
        status, raw, _headers, error = client.call("POST", LEASE_PATH, {"source_id": source})
        if error is not None or status != 200:
            row = {"check": f"{client.name}.camera.{source}", "result": "FAIL",
                   "stage": "lease", "status": status}
            if error:
                row["error"] = error
            rows.append(row)
            continue
        try:
            lease = json.loads(raw)
            token, frame_path = lease["lease"], lease["frame_path"]
        except (ValueError, KeyError, TypeError):
            rows.append({"check": f"{client.name}.camera.{source}", "result": "FAIL",
                         "stage": "lease", "status": status, "why": "no lease/frame_path in the body"})
            continue
        if not same_origin(frame_path, client.base_url):
            rows.append({"check": f"{client.name}.camera.{source}", "result": "FAIL",
                         "stage": "frame_path", "frame_path": frame_path,
                         "why": "not the fleet origin"})
            continue
        if not frame_path.startswith("/"):
            frame_path = urllib.parse.urlsplit(frame_path).path
        frame_status, frame_raw, frame_headers, frame_error = client.call("GET", frame_path, bearer=token)
        age_raw = frame_headers.get("X-Frame-Age-Ms") if frame_headers is not None else None
        try:
            age = float(age_raw) if age_raw is not None else None
        except (TypeError, ValueError):
            age = None
        size = len(frame_raw or b"")
        ok = (frame_error is None and frame_status == 200 and size > FRAME_MIN_BYTES
              and age is not None and age <= FRAME_AGE_MAX_MS)
        row = {"check": f"{client.name}.camera.{source}", "result": "PASS" if ok else "FAIL",
               "status": frame_status, "bytes": size, "age_ms": age_raw,
               "frame_state": frame_headers.get("X-Frame-State") if frame_headers is not None else None}
        if frame_error:
            row["error"] = frame_error
        rows.append(row)
    return rows


def cell_task_rows(client: FleetClient) -> list[dict]:
    """R pipeline cell tasks reachable, with a MISSING line per boot-default arm-live state."""
    status, raw, _headers, error = client.call("GET", CELL_TASKS_PATH)
    ok = error is None and status == 200
    row = {"check": "R.cell_tasks_api", "result": "PASS" if ok else "FAIL", "status": status}
    if error:
        row["error"] = error
    rows = [row]
    body = None
    if ok:
        try:
            body = json.loads(raw)
        except ValueError:
            row["result"] = "FAIL"
            row["why"] = "unreadable JSON body"
    if body is None:
        return rows
    tasks = body.get("tasks") or []
    live = body.get("arm_live_states") or {}
    row["tasks"] = len(tasks)
    row["active"] = [t.get("task_id") for t in tasks
                     if isinstance(t, dict) and t.get("status") in ("QUEUED", "CLAIMED", "RUNNING")]
    row["arm_live_sources"] = {k: (v or {}).get("source") for k, v in live.items() if isinstance(v, dict)}
    row["arm_holds"] = body.get("arm_holds")
    for arm, source in sorted(row["arm_live_sources"].items()):
        if source == BOOT_DEFAULT_SOURCE:
            rows.append({"check": f"R.arm_live.{arm}", "result": "MISSING", "source": source})
    return rows


def run(targets: dict, *, sleep=time.sleep) -> list[dict]:
    """Every check row, in order, across the named Fleet clients. MISSING never fails the verdict."""
    rows, first, second, cameras = [], {}, {}, {}
    for round_no, store in ((1, first), (2, second)):
        if round_no == 2:
            sleep(OBSERVATION_GAP_S)
        for name, client in targets.items():
            store[name] = fetch_observations(client)
            if round_no == 2:
                cameras[name] = store[name][2]
    for name in targets:
        rows += observation_rows(name, first[name], second[name])
    for name, sources in cameras.items():
        rows += camera_rows(targets[name], sources)
    if "cell" in targets and "R" in targets:
        rows += mirror_rows(second["cell"][1], second["R"][1])
    if "R" in targets:
        rows += cell_task_rows(targets["R"])
    return rows


def verdict(rows: list[dict]) -> tuple[str, int, int]:
    """(verdict, judged check count, FAIL count); MISSING rows are informational."""
    failed = sum(row["result"] == "FAIL" for row in rows)
    judged = len(rows) - sum(row["result"] == "MISSING" for row in rows)
    return ("FAIL" if failed else "PASS"), judged, failed


def document(rows: list[dict], targets: dict, checked_at: str) -> dict:
    """The result document Monitoring reads (schema rosy.workcell-pipeline-gate.v1)."""
    state, _judged, failed = verdict(rows)
    return {"schema": SCHEMA, "checked_at": checked_at, "verdict": state, "failed": failed,
            "targets": {name: client.base_url for name, client in targets.items()}, "checks": rows}


def main(argv: list[str] | None = None, client_factory=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cell-url", help="cell Fleet base URL")
    parser.add_argument("--r-url", help="R Fleet base URL")
    parser.add_argument("--cookie-file", help="operator session cookie file (first non-empty line)")
    parser.add_argument("--bearer-file", help="operator bearer token file (first non-empty line)")
    parser.add_argument("--ca-file", required=True,
                        help="PEM anchor the fleets' certificates must chain to")
    parser.add_argument("--json-out", help="write the result document here for Monitoring")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="per request seconds")
    args = parser.parse_args(argv)
    if not args.cell_url and not args.r_url:
        parser.error("pass --cell-url and/or --r-url")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        auth = auth_header(args.cookie_file, args.bearer_file)
        context = tls_context(args.ca_file)
    except (GateError, OSError) as error:
        parser.exit(2, f"workcell_pipeline_gate: {error}\n")
    build = client_factory or (lambda name, url: FleetClient(name, url, auth, args.timeout, context))
    targets = {}
    if args.cell_url:
        targets["cell"] = build("cell", args.cell_url)
    if args.r_url:
        targets["R"] = build("R", args.r_url)
    rows = run(targets)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    state, judged, failed = verdict(rows)
    print(json.dumps({"verdict": state, "checks": judged, "failed": failed}), flush=True)
    if args.json_out:
        result = document(rows, targets, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    return 0 if state == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
