"""Fleet HTTPS client for the Pinky localization pipeline."""

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Optional


class PipelineError(Exception):
    """Structured refusal from verification or Fleet API checks."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _read_token(token_file: Optional[Path]) -> Optional[str]:
    if token_file is not None:
        tok = Path(token_file).read_text(encoding="utf-8").strip()
        if not tok:
            raise PipelineError("EMPTY_TOKEN", f"token file {token_file} is empty")
        return tok
    return os.environ.get("ROSY_FLEET_TOKEN", "").strip() or None


class FleetClient:
    """Minimal stdlib HTTPS JSON client for Fleet API routes (never logs or echoes tokens)."""

    def __init__(self, base_url: str, *, token: Optional[str] = None, ca_file: Optional[Path] = None,
                 insecure: bool = False, timeout_s: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout_s = float(timeout_s)
        self._ssl_ctx = self._build_ssl_context(ca_file=ca_file, insecure=insecure)

    @staticmethod
    def _build_ssl_context(*, ca_file: Optional[Path], insecure: bool) -> ssl.SSLContext:
        if insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return ssl.create_default_context(cafile=str(ca_file)) if ca_file is not None else ssl.create_default_context()

    def request_json(self, method: str, path: str, body: Optional[Mapping[str, Any]] = None) -> Any:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        data: Optional[bytes] = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s, context=self._ssl_ctx) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            code, msg = f"HTTP_{exc.code}", exc.reason or f"HTTP {exc.code}"
            try:
                err = json.loads(exc.read().decode("utf-8"))
                detail = err.get("detail") if isinstance(err, dict) else None
                if isinstance(detail, dict):
                    code = str(detail.get("code") or code)
                    nested = detail.get("detail") if isinstance(detail.get("detail"), dict) else None
                    msg = str(detail.get("message") or (nested or {}).get("message") or detail.get("detail") or msg)
            except Exception:
                pass
            raise PipelineError(code, f"{method} {path}: {msg}") from None
        except urllib.error.URLError as exc:
            raise PipelineError("CONNECT_ERROR", f"{method} {path}: {exc.reason}") from None


# --------------------------------------------------------------------------- D-1022 pure math
