"""D-418: CORE's side of the SSH access hand-over to the root rosy-ssh-access.

CORE never runs chpasswd or touches sshd (D-161). It writes one request file in
its own /run/rosy, which rosy-ssh-access.path watches, and waits at most
WAIT_S for the helper's response beside it. The response is read strictly
(no link, no FIFO, bounded, this request's id) and deleted at once: for
``password_on`` it carries the temporary password.

Standard library only, so the device twin runs this exact code as rosy-core.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import secrets
import stat
import time
from typing import Any, Callable, Optional

SCHEMA = 1
REQUEST_FILE = "/run/rosy/ssh-access.request"
RESPONSE_FILE = "/run/rosy/ssh-access.response"
#: The contract's bound on how long CORE waits for the helper.
WAIT_S = 10.0
POLL_S = 0.05
MAX_RESPONSE_BYTES = 64 * 1024
ACTIONS = ("list", "add", "revoke", "password_on", "password_off", "password_status")
#: What the helper may answer, and the error codes it may name (rosy-ssh-access.py).
STATUSES = {200, 201, 204, 404, 409, 422, 503}
ERRORS = {"SSH_INVALID", "SSH_LABEL_EXISTS", "SSH_KEY_EXISTS", "SSH_KEYS_FULL", "SSH_KEY_NOT_FOUND",
          "SSH_ACCESS_UNAVAILABLE"}


class HandoffUnavailable(RuntimeError):
    """No usable answer: the request could not be written, or nothing answered in time."""


def build_request(action: str, by: str, params: dict[str, Any], *, request_id: Optional[str] = None,
                  now: Optional[datetime] = None) -> dict[str, Any]:
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {"schema": SCHEMA, "request_id": request_id or secrets.token_hex(8), "action": action,
            "requested_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "by": by, **params}


def write_request(path: str, request: dict[str, Any]) -> None:
    """Beside the target with O_EXCL | O_NOFOLLOW, then rename over it (one inotify event)."""
    directory = os.path.dirname(path) or "."
    temporary = os.path.join(directory, f".ssh-access.request.{secrets.token_hex(6)}")
    payload = json.dumps(request, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def read_response(path: str, request_id: str) -> Optional[dict[str, Any]]:
    """The helper's answer to `request_id`, validated, or None (absent, another request's, malformed)."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
        | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RESPONSE_BYTES:
            return None
        raw = os.read(descriptor, MAX_RESPONSE_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("request_id") != request_id:
        return None
    status, error, message, result = data.get("status"), data.get("error"), data.get("message"), data.get("result")
    if type(status) is not int or status not in STATUSES or not isinstance(message, str):
        return None
    if (error is None) != (status < 400) or (error is not None and error not in ERRORS):
        return None
    if result is not None and not isinstance(result, dict):
        return None
    return {"status": status, "error": error, "message": message[:300], "result": result}


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def exchange(action: str, by: str, params: dict[str, Any], *, request_path: str = REQUEST_FILE,
             response_path: str = RESPONSE_FILE, wait_s: float = WAIT_S, poll_s: float = POLL_S,
             clock: Callable[[], float] = time.monotonic,
             sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Write one request and return the helper's validated answer; HandoffUnavailable otherwise.

    One exchange at a time: the caller holds a lock (there is one request file).
    """
    request = build_request(action, by, params)
    _unlink(response_path)  # an answer to an earlier, abandoned request
    try:
        write_request(request_path, request)
    except OSError as exc:
        raise HandoffUnavailable("요청 파일을 쓰지 못했습니다") from exc
    deadline = clock() + wait_s
    while True:
        answer = read_response(response_path, request["request_id"])
        if answer is not None:
            _unlink(response_path)  # read once: a password must not stay on disk
            return answer
        if clock() >= deadline:
            # Withdrawn, so a helper that starts late does not apply what nobody waits for.
            _unlink(request_path)
            raise HandoffUnavailable(f"rosy-ssh-access 가 {wait_s:.0f} s 안에 답하지 않았습니다")
        sleep(poll_s)
