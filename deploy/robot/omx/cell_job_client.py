#!/usr/bin/env python3
"""HTTP client and CLI for `cell_job_api.py` (:8781) — zero-SSH guarded cell control."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8781"


class CellJobError(RuntimeError):
    """Raised when `cell_job_api` returns an HTTP error."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(f"cell-job-api HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def default_token_path() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "Rosy" / "cell-job-api.token"
    return Path.home() / ".config" / "rosy" / "cell-job-api.token"


def resolve_token(token: str | None = None, token_file: Path | None = None) -> str:
    if token:
        return token.strip()
    if env_token := os.environ.get("ROSY_CELL_JOB_TOKEN"):
        return env_token.strip()
    path = token_file or default_token_path()
    return path.read_text(encoding="utf-8").strip()


class CellJobClient:
    """Thin stdlib client for `cell_job_api.py`."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        token_file: Path | None = None,
        timeout: float = 10.0,
    ):
        self.base_url = (base_url or os.environ.get("ROSY_CELL_JOB_URL") or DEFAULT_URL).rstrip("/")
        self._token = token
        self._token_file = token_file
        self.timeout = timeout

    def _auth_header(self) -> dict[str, str]:
        if self._token is None:
            self._token = resolve_token(None, self._token_file)
        return {"Authorization": f"Bearer {self._token}"}

    def _request_with_headers(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        auth: bool = True,
        extra_headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        headers = self._auth_header() if auth else {}
        if extra_headers:
            headers.update(extra_headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return resp.read(), {k: str(v) for k, v in resp.headers.items()}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(raw).get("error", raw)
            except ValueError:
                detail = raw
            raise CellJobError(exc.code, str(detail)) from None

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        auth: bool = True,
        extra_headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> bytes:
        return self._request_with_headers(method, path, body, auth=auth, extra_headers=extra_headers, timeout=timeout)[0]

    def health(self) -> dict:
        return json.loads(self._request("GET", "/health", auth=False))

    def readiness(self, *, cell: str | None = None) -> dict:
        q = f"?{urllib.parse.urlencode({'cell': cell})}" if cell is not None else ""
        return json.loads(self._request("GET", f"/readiness{q}"))

    def failures(self, *, arm: str | None = None, kind: str | None = None, limit: int = 20) -> dict:
        q = urllib.parse.urlencode({k: str(v) for k, v in (("arm", arm), ("kind", kind), ("limit", limit)) if v is not None})
        return json.loads(self._request("GET", f"/failures?{q}" if q else "/failures"))

    def latest_failure(self, *, arm: str | None = None, kind: str | None = None) -> dict:
        q = urllib.parse.urlencode({k: str(v) for k, v in (("arm", arm), ("kind", kind)) if v is not None})
        return json.loads(self._request("GET", f"/failures/latest?{q}" if q else "/failures/latest"))

    def failure(self, bundle_id: str) -> dict:
        return json.loads(self._request("GET", f"/failures/{urllib.parse.quote(bundle_id)}"))

    def failure_asset(self, bundle_id: str, filename: str) -> bytes:
        return self._request("GET", f"/failures/{urllib.parse.quote(bundle_id)}/assets/{urllib.parse.quote(filename)}")

    def queue(self) -> dict:
        return json.loads(self._request("GET", "/queue"))

    def frame(self, view: str) -> bytes:
        return self._request("GET", f"/frame/{view}.jpg")

    def frame_with_headers(self, view: str) -> tuple[bytes, dict[str, str]]:
        return self._request_with_headers("GET", f"/frame/{view}.jpg")

    def start(self, job: str, params: dict, *, idempotency_key: str | None = None) -> dict:
        extra = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return json.loads(self._request("POST", f"/jobs/{job}", params, extra_headers=extra))

    def cancel(self, job_id: str, *, timeout: float | None = None) -> dict:
        """Request a cooperative stop (a park at the job's next guarded step, D-1081); not an emergency stop."""
        return json.loads(self._request("POST", f"/jobs/{job_id}/cancel", {}, timeout=timeout))

    def jobs(self) -> dict:
        return json.loads(self._request("GET", "/jobs"))

    def get(self, job_id: str) -> dict:
        return json.loads(self._request("GET", f"/jobs/{job_id}"))

    def wait(self, job_id: str, *, poll_s: float = 1.0, timeout_s: float = 600.0) -> dict:
        deadline = time.monotonic() + timeout_s
        while True:
            state = self.get(job_id)
            if not state.get("running"):
                return state
            if time.monotonic() >= deadline:
                raise TimeoutError(f"job {job_id} still running after {timeout_s}s")
            time.sleep(poll_s)


def start_when_lock_free(client, job: str, params: dict, *, idempotency_key=None, wait_s: float = 0.0,
                         poll_s: float = 5.0, clock=time.monotonic, sleep=time.sleep) -> dict:
    """A refused or ended job's session wrapper keeps the arm lock ~100 s after the API reports the job done
    (2026-11-26); with wait_s > 0 retry only that 409, never another refusal. Opt-in: a held lock may be a live job."""
    deadline = clock() + wait_s
    while True:
        try:
            return client.start(job, params, idempotency_key=idempotency_key)
        except CellJobError as exc:
            if exc.status_code != 409 or "session lock for" not in exc.detail or clock() >= deadline:
                raise
            sleep(poll_s)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", help="cell-job-api base URL (default: ROSY_CELL_JOB_URL or http://127.0.0.1:8781)")
    ap.add_argument("--token-file", type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    sub.add_parser("readiness")
    p_fails = sub.add_parser("failures")
    p_fails.add_argument("--arm")
    p_fails.add_argument("--kind")
    p_fails.add_argument("--limit", type=int, default=20)
    p_latest = sub.add_parser("latest-failure")
    p_latest.add_argument("--arm")
    p_latest.add_argument("--kind")
    sub.add_parser("queue")
    p_get = sub.add_parser("get")
    p_get.add_argument("job_id")
    p_wait = sub.add_parser("wait")
    p_wait.add_argument("job_id")
    p_wait.add_argument("--timeout", type=float, default=600.0)
    p_frame = sub.add_parser("frame")
    p_frame.add_argument("view")
    p_frame.add_argument("--out", type=Path, required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("job")
    p_run.add_argument("--params-json", default="{}")
    p_run.add_argument("--timeout", type=float, default=600.0)
    p_run.add_argument("--idempotency-key")
    p_run.add_argument("--wait", action="store_true")
    p_run.add_argument("--lock-wait", type=float, default=0.0,
                       help="opt-in: seconds to retry a 409 while a finished job's arm session still releases its lock "
                            "(default 0: a held lock may be a live job)")
    args = ap.parse_args(argv)

    client = CellJobClient(args.url, token_file=args.token_file)
    if args.cmd == "health":
        print(json.dumps(client.health()))
        return 0
    if args.cmd == "readiness":
        print(json.dumps(client.readiness()))
        return 0
    if args.cmd == "failures":
        print(json.dumps(client.failures(arm=args.arm, kind=args.kind, limit=args.limit)))
        return 0
    if args.cmd == "latest-failure":
        print(json.dumps(client.latest_failure(arm=args.arm, kind=args.kind)))
        return 0
    if args.cmd == "queue":
        print(json.dumps(client.queue()))
        return 0
    if args.cmd == "get":
        print(json.dumps(client.get(args.job_id)))
        return 0
    if args.cmd == "wait":
        done = client.wait(args.job_id, timeout_s=args.timeout)
        print(json.dumps(done))
        return 0 if done.get("exit") == 0 else 1
    if args.cmd == "frame":
        args.out.write_bytes(client.frame(args.view))
        print(json.dumps({"view": args.view, "out": str(args.out)}))
        return 0
    params = json.loads(args.params_json)
    started = start_when_lock_free(client, args.job, params, idempotency_key=args.idempotency_key, wait_s=args.lock_wait)
    if not args.wait:
        print(json.dumps(started))
        return 0
    done = client.wait(started["id"], timeout_s=args.timeout)
    print(json.dumps(done))
    return 0 if done.get("exit") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
