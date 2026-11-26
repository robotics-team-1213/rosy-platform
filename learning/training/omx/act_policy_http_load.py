"""Bounded JSON body reading and runtime model swap for act_policy_http_server.

POST /arms/{arm}/load {"dir", "sha256"} verifies the checkpoint exactly as startup does
(PolicyRegistry.load_entry), builds a new entry, and only then swaps it in. Any failure
leaves the served entry untouched. The env-file write-back runs only after a successful swap.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Sequence

LOAD_PATH = re.compile(r"/arms/([A-Za-z0-9_][A-Za-z0-9_.-]{0,63})/load")
ENV_KEY = "ROSY_ACT_HTTP_ARGS="
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_LOAD_LOCK = threading.Lock()  # one checkpoint load at a time; /infer keeps serving the old entry meanwhile


def read_json_body(handler: Any, max_body_bytes: int) -> tuple[Any, tuple[int, str] | None]:
    """Return (payload, None) or (None, (status, error)) for a Content-Length-bounded JSON body."""
    if "Transfer-Encoding" in handler.headers:
        return None, (400, "Transfer-Encoding not supported")
    raw_lens = handler.headers.get_all("Content-Length") or []
    if not raw_lens:
        return None, (411, "Content-Length required")
    if len(raw_lens) > 1:
        return None, (400, "multiple Content-Length headers")
    raw_len = raw_lens[0].strip(" \t")
    if not raw_len or not raw_len.isascii() or not raw_len.isdigit():
        return None, (400, "invalid Content-Length")
    norm_len = raw_len.lstrip("0") or "0"
    if len(norm_len) > len(str(max_body_bytes)) or int(norm_len) > max_body_bytes:
        return None, (413, "request body exceeds max_body_bytes")
    content_len = int(norm_len)
    raw_body = handler.rfile.read(content_len)
    if len(raw_body) != content_len:
        return None, (400, "truncated request body")
    try:
        return json.loads(raw_body.decode("utf-8")), None
    except Exception:
        return None, (400, "invalid JSON")


def persist_arm(env_file: Path | None, arm_id: str, policy_dir: Path, revision: str) -> dict[str, Any]:
    """Rewrite this arm's --arm token in the service env file atomically; never raises."""
    if env_file is None:
        return {"persisted": False, "reason": "no env file configured; the previous model returns at restart"}
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines(keepends=True)
        token = re.compile(r"(--arm[ =])" + re.escape(arm_id) + r"=[^\s\"']+")
        hits = [i for i, line in enumerate(lines) if line.startswith(ENV_KEY) and token.search(line)]
        if len(hits) != 1 or len(token.findall(lines[hits[0]])) != 1:
            return {"persisted": False, "reason": f"env file needs exactly one --arm {arm_id}= token in {ENV_KEY.rstrip('=')}"}
        if any(ch.isspace() or ch in "\"'" for ch in str(policy_dir)):
            return {"persisted": False, "reason": "policy dir contains whitespace or quotes; not written"}
        lines[hits[0]] = token.sub(lambda m: f"{m[1]}{arm_id}={policy_dir}:{revision}", lines[hits[0]])
        fd, tmp = tempfile.mkstemp(dir=env_file.parent, prefix=f".{env_file.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("".join(lines))
            os.chmod(tmp, env_file.stat().st_mode & 0o777)
            os.replace(tmp, env_file)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except Exception as exc:
        return {"persisted": False, "reason": f"env write failed: {type(exc).__name__}"}
    return {"persisted": True}


def handle_load(
    registry: Any, arm_id: str, body: Any, *, roots: Sequence[Path], env_file: Path | None,
) -> tuple[int, dict[str, Any]]:
    if not roots:
        return 403, {"ok": False, "error": "model load disabled: no allowed load roots configured"}
    if registry.revision_of(arm_id) is None:
        return 404, {"ok": False, "error": f"unknown arm_id {arm_id!r}"}
    if not isinstance(body, dict) or set(body) != {"dir", "sha256"}:
        return 400, {"ok": False, "error": "body must be exactly {dir, sha256}"}
    revision, raw_dir = body["sha256"], body["dir"]
    if not isinstance(revision, str) or not _HEX64.match(revision):
        return 400, {"ok": False, "error": "sha256 must be 64-char lowercase hex"}
    if not isinstance(raw_dir, str) or not raw_dir.strip() or not Path(raw_dir).is_absolute():
        return 400, {"ok": False, "error": "dir must be an absolute path"}
    policy_dir = Path(raw_dir).resolve()  # resolve first so symlinks and .. cannot leave the root
    if not any(policy_dir.is_relative_to(root) for root in roots):
        return 403, {"ok": False, "error": "dir is outside the allowed load roots"}
    if not _LOAD_LOCK.acquire(blocking=False):
        return 409, {"ok": False, "error": "another model load is in progress"}
    try:
        try:
            entry = registry.load_entry(arm_id, policy_dir, revision)
        except ValueError as exc:
            return 422, {"ok": False, "error": f"load refused: {exc}", "kept_revision": registry.revision_of(arm_id)}
        except Exception as exc:
            return 500, {"ok": False, "error": f"load failed: {type(exc).__name__}", "kept_revision": registry.revision_of(arm_id)}
        previous = registry.swap(entry)
        saved = persist_arm(env_file, arm_id, policy_dir, revision)
    finally:
        _LOAD_LOCK.release()
    return 200, {"ok": True, "arm_id": arm_id, "dir": str(policy_dir), "revision": revision,
                 "previous_revision": previous.revision, **saved}
