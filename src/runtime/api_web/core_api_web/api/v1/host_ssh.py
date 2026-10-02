"""로봇 SSH 접속 API (D-418). administrator 전용.

CORE 는 비특권이다(D-161). 키 등록·회수와 임시 비밀번호는 요청 파일을 써서 root
rosy-ssh-access 에 넘기고(ssh_handoff), 최대 10 s 답을 기다린다. 도우미가 형식·
개수·만료를 따로 다시 검사한다. host key 공개키만 CORE 가 직접 읽는다(0644).
"""

from __future__ import annotations

import base64
import glob
import os
import re
import socket
import stat
import threading
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1 import ssh_handoff
from core_api_web.api.v1.common import admin
from core_common.protocol.schemas import (
    SSH_LABEL_PATTERN,
    SshHostKeys,
    SshKeyAdded,
    SshKeyAddRequest,
    SshKeyList,
    SshPasswordIssued,
    SshPasswordRequest,
    SshPasswordStatus,
)

ssh_router = APIRouter(prefix="/ssh", tags=["host"])

HOST_KEY_DIR = "/etc/ssh"
HOST_KEY_TYPES = ("ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521", "ssh-rsa")
MAX_HOST_KEY_BYTES = 16 * 1024
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
#: One request file, so one exchange at a time.
_exchange_lock = threading.Lock()


def wait_seconds(config: Optional[dict]) -> float:
    """The configured wait, never longer than the contract's 10 s."""
    cfg = (config or {}).get("ssh_access", {}) or {}
    try:
        configured = float(cfg.get("wait_s", ssh_handoff.WAIT_S))
    except (TypeError, ValueError):
        configured = ssh_handoff.WAIT_S
    return max(0.1, min(configured, ssh_handoff.WAIT_S))


def _paths(svc: CoreServicesLike) -> tuple[str, str, str]:
    cfg = (svc.config or {}).get("ssh_access", {}) or {}
    return (str(cfg.get("request_path", ssh_handoff.REQUEST_FILE)),
            str(cfg.get("response_path", ssh_handoff.RESPONSE_FILE)),
            str(cfg.get("host_key_dir", HOST_KEY_DIR)))


def _invalid(exc: ValidationError) -> ApiError:
    fields = sorted({".".join(str(part) for part in error.get("loc", ())) or "body" for error in exc.errors()})
    return ApiError("SSH_INVALID", 422, "공개키·라벨·기간 형식이 계약과 맞지 않습니다", {"fields": fields})


def _parse(model: type[BaseModel], body: Any) -> BaseModel:
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        raise _invalid(exc) from exc


def requester(auth: AuthContext) -> str:
    """`added_by`: the token's label, printable and at most 128 characters (the helper refuses others)."""
    shown = "".join(ch for ch in (auth.label or "") if ch.isprintable())[:128]
    return shown or auth.token_id[:128]


def _call(svc: CoreServicesLike, auth: AuthContext, action: str, params: dict[str, Any]) -> dict[str, Any]:
    request_path, response_path, _keys = _paths(svc)
    wait_s = wait_seconds(svc.config)
    if not _exchange_lock.acquire(timeout=wait_s):
        raise ApiError("SSH_ACCESS_UNAVAILABLE", 503, "다른 SSH 접속 요청을 처리하는 중입니다")
    try:
        answer = ssh_handoff.exchange(action, requester(auth), params,
                                      request_path=request_path, response_path=response_path, wait_s=wait_s)
    except ssh_handoff.HandoffUnavailable as exc:
        raise ApiError("SSH_ACCESS_UNAVAILABLE", 503, str(exc)) from exc
    finally:
        _exchange_lock.release()
    if answer["error"] is not None:
        raise ApiError(answer["error"], answer["status"], answer["message"])
    return answer


def _result(model: type[BaseModel], answer: dict[str, Any]) -> dict[str, Any]:
    try:
        return model.model_validate(answer["result"]).model_dump()
    except ValidationError as exc:
        raise ApiError("SSH_ACCESS_UNAVAILABLE", 503, "rosy-ssh-access 의 답이 계약과 맞지 않습니다") from exc


def _read_public_line(path: str) -> Optional[str]:
    """`<type> <base64>` from a host key .pub file, or None. Never through a link or a FIFO."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_HOST_KEY_BYTES:
            return None
        raw = os.read(descriptor, MAX_HOST_KEY_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    words = raw.decode("ascii", "replace").strip().split()
    if len(words) < 2 or words[0] not in HOST_KEY_TYPES:
        return None
    try:
        base64.b64decode(words[1], validate=True)
    except ValueError:
        return None
    return f"{words[0]} {words[1]}"


@ssh_router.get("/host-keys")
def ssh_host_keys(_: AuthContext = Depends(admin), svc: CoreServicesLike = Depends(get_services)):
    """로봇 host key 공개키. 등록 도구가 처음 접속 전에 known_hosts 를 쓴다(TOFU 없음)."""
    _request, _response, directory = _paths(svc)
    keys = [line for path in sorted(glob.glob(os.path.join(directory, "ssh_host_*_key.pub")))
            if (line := _read_public_line(path)) is not None]
    return SshHostKeys(hostname=socket.gethostname(), host_keys=keys).model_dump()


@ssh_router.get("/keys")
def ssh_keys(auth: AuthContext = Depends(admin), svc: CoreServicesLike = Depends(get_services)):
    """관리 키 목록(라벨·종류·지문·추가 시각·만료·추가한 토큰 라벨)."""
    return _result(SshKeyList, _call(svc, auth, "list", {}))


@ssh_router.post("/keys")
def ssh_key_add(body: Any = Body(None), auth: AuthContext = Depends(admin),
                svc: CoreServicesLike = Depends(get_services)):
    """공개키 등록. 만료는 sshd 가 그 줄의 expiry-time 으로 직접 강제한다."""
    request = _parse(SshKeyAddRequest, body)
    answer = _call(svc, auth, "add", request.model_dump())
    return JSONResponse(status_code=201, content=_result(SshKeyAdded, answer))


@ssh_router.delete("/keys/{label}")
def ssh_key_revoke(label: str, auth: AuthContext = Depends(admin), svc: CoreServicesLike = Depends(get_services)):
    """라벨로 회수. 없는 라벨은 404."""
    if not re.fullmatch(SSH_LABEL_PATTERN, label):
        raise ApiError("SSH_KEY_NOT_FOUND", 404, f"라벨 {label[:48]!r} 인 키가 없습니다")
    _call(svc, auth, "revoke", {"label": label})
    return Response(status_code=204)


@ssh_router.post("/password")
def ssh_password_on(body: Any = Body(None), auth: AuthContext = Depends(admin),
                    svc: CoreServicesLike = Depends(get_services)):
    """rosy 계정 임시 비밀번호(최대 60분, 사설 대역만). 비밀번호는 이 응답에만 나온다."""
    request = _parse(SshPasswordRequest, body)
    answer = _call(svc, auth, "password_on", request.model_dump())
    return JSONResponse(status_code=200, content=_result(SshPasswordIssued, answer), headers=NO_STORE)


@ssh_router.get("/password")
def ssh_password_status(auth: AuthContext = Depends(admin), svc: CoreServicesLike = Depends(get_services)):
    """임시 비밀번호가 켜져 있는지와 만료 시각. 비밀번호는 싣지 않는다."""
    return _result(SshPasswordStatus, _call(svc, auth, "password_status", {}))


@ssh_router.delete("/password")
def ssh_password_off(auth: AuthContext = Depends(admin), svc: CoreServicesLike = Depends(get_services)):
    """지금 끈다: shadow `*`, Match drop-in 제거, sshd 다시 읽기."""
    _call(svc, auth, "password_off", {})
    return Response(status_code=204)
