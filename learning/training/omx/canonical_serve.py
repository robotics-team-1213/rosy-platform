"""Put a finished canonical train_stage checkpoint on the AI PC ACT server (POST /arms/{arm}/load).

The Learning server only forwards the run's own checkpoint dir and weights sha256; the ACT
server re-verifies both, checks its allowed root, and keeps the old model on any failure.
"""
from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.request

from canonical_telemetry import load_peer_token
from canonical_watch import validate_peer_url
from experiment_io import identifier

LOAD_TIMEOUT_S = 180  # a GPU checkpoint load on the AI PC takes seconds to tens of seconds
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def parse_config(raw) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"url", "token_file"}:
        raise ValueError("act_serve requires exactly url and token_file")
    token_file = Path(raw["token_file"])
    if not token_file.is_absolute():
        raise ValueError("act_serve.token_file must be absolute")
    return {"url": validate_peer_url(raw["url"]), "token_file": token_file}


def serve_run(service, rid: str) -> dict:
    """Send one succeeded train_stage run to the ACT server; returns its verdict, never the token."""
    cfg = getattr(service, "act_serve", None)
    if cfg is None:
        raise ValueError("ACT 서빙 서버가 설정되지 않았습니다 (canonical config act_serve).")
    rid = identifier(rid)
    run = service.get_run(rid)
    sha = (run.get("result") or {}).get("policy_sha256")
    if run["kind"] != "train_stage" or run["status"] != "succeeded" or not isinstance(sha, str):
        raise ValueError("완료된 train_stage 작업만 서빙에 올릴 수 있습니다.")
    ckpt = (service.root / "runs" / rid / "output" / "train" / "checkpoints" / "last" / "pretrained_model").resolve()
    body = json.dumps({"dir": str(ckpt), "sha256": sha}).encode("utf-8")
    req = urllib.request.Request(cfg["url"] + f"/arms/{run['arm_id']}/load", data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + load_peer_token(cfg["token_file"])})
    try:
        with _OPENER.open(req, timeout=LOAD_TIMEOUT_S) as resp:
            status, raw = resp.status, resp.read(65536)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(65536)
    except (OSError, urllib.error.URLError) as exc:
        return {"ok": False, "run_id": rid, "arm_id": run["arm_id"], "sha256": sha,
                "error": f"ACT 서버에 연결하지 못했습니다 ({type(exc).__name__})."}
    try:
        reply = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        reply = {"error": f"ACT 서버 응답을 읽지 못했습니다 (HTTP {status})."}
    reply = reply if isinstance(reply, dict) else {}
    return {"ok": status == 200 and reply.get("ok") is True, "http_status": status, "run_id": rid,
            "arm_id": run["arm_id"], "sha256": sha, "reply": reply}
