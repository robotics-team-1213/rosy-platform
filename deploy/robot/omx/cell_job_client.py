#!/usr/bin/env python3
"""HTTP client and CLI for `cell_job_api.py` (:8781) — zero-SSH guarded cell control."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
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

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        auth: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> bytes:
        headers = self._auth_header() if auth else {}
        if extra_headers:
            headers.update(extra_headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(raw).get("error", raw)
            except ValueError:
                detail = raw
            raise CellJobError(exc.code, str(detail)) from None

    def health(self) -> dict:
        return json.loads(self._request("GET", "/health", auth=False))

    def queue(self) -> dict:
        return json.loads(self._request("GET", "/queue"))

    def frame(self, view: str) -> bytes:
        return self._request("GET", f"/frame/{view}.jpg")

    def start(self, job: str, params: dict, *, idempotency_key: str | None = None) -> dict:
        extra = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return json.loads(self._request("POST", f"/jobs/{job}", params, extra_headers=extra))

    def jobs(self) -> dict:
        return json.loads(self._request("GET", "/jobs"))

    def get(self, job_id: str) -> dict:
        return json.loads(self._request("GET", f"/jobs/{job_id}"))

    def wait(self, job_id: str, *, poll_s: float = 1.0, timeout_s: float = 300.0) -> dict:
        deadline = time.monotonic() + timeout_s
        while True:
            state = self.get(job_id)
            if not state.get("running"):
                return state
            if time.monotonic() >= deadline:
                raise TimeoutError(f"job {job_id} still running after {timeout_s}s")
            time.sleep(poll_s)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", help="cell-job-api base URL (default: ROSY_CELL_JOB_URL or http://127.0.0.1:8781)")
    ap.add_argument("--token-file", type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    sub.add_parser("queue")
    p_frame = sub.add_parser("frame")
    p_frame.add_argument("view")
    p_frame.add_argument("--out", type=Path, required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("job")
    p_run.add_argument("--params-json", default="{}")
    p_run.add_argument("--wait", action="store_true")
    args = ap.parse_args(argv)

    client = CellJobClient(args.url, token_file=args.token_file)
    if args.cmd == "health":
        print(json.dumps(client.health()))
        return 0
    if args.cmd == "queue":
        print(json.dumps(client.queue()))
        return 0
    if args.cmd == "frame":
        args.out.write_bytes(client.frame(args.view))
        print(json.dumps({"view": args.view, "out": str(args.out)}))
        return 0
    params = json.loads(args.params_json)
    started = client.start(args.job, params)
    if not args.wait:
        print(json.dumps(started))
        return 0
    done = client.wait(started["id"])
    print(json.dumps(done))
    return 0 if done.get("exit") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
