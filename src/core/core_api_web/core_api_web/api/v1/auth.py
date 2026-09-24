"""core_api_web.api.v1.auth — D-193 로그인 코드 페어링과 토큰 수명주기.

CORE는 물리 로그인 코드를 만들지 않는다(D-161). root 발급자
`rosy-login-code` 가 쓴 검증자 파일 `/run/rosy-boot/login-code.json` 을
읽기만 하고, 코드를 쓰거나 폐기하면 자기 런타임 디렉터리의
`/run/rosy/login-code-state.json` 에 `{code_id, state}` 하나를 남긴다. root는
그 신호를 보고 LCD·콘솔의 코드를 지운다.

관리자가 다른 기기를 붙일 때 쓰는 등록 코드는 예외다. 이미 관리자인 호출자가
요청한 것이라 CORE 메모리에만 5분 동안 둔다.
"""

from __future__ import annotations

import collections
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import stat
import threading
import time
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from core_api_web.api.deps import (
    PAIRED_SOURCES,
    ROLE_RANK,
    TOKEN_WRITE_LOCK,
    AuthContext,
    CoreServicesLike,
    auth_entries,
    expires_before,
    generate_token,
    get_services,
    new_token_record,
    persist_token_records,
    token_alive,
    utc_after,
)
from core_api_web.api.errors import ApiError, error_body
from core_api_web.api.v1.common import admin, viewer

auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

#: root 발급자가 쓰는 검증자 파일 (root:rosy-core 0640, tmpfs).
CODE_FILE = "/run/rosy-boot/login-code.json"
#: CORE 자신의 신호 파일. /run/rosy 는 rosy-core.service 의 RuntimeDirectory 다.
STATE_FILE = "/run/rosy/login-code-state.json"
BOOT_ID_FILE = "/proc/sys/kernel/random/boot_id"

#: 코드 형식. rosy-login-code.py 의 ALPHABET·CODE_LENGTH 와 같아야 한다.
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8
CODE_RE = re.compile(f"^[{ALPHABET}]{{{CODE_LENGTH}}}$")
CODE_ID_RE = re.compile(r"^[0-9a-f]{16}$")

#: scrypt 매개변수. 파일이 다른 값을 적으면 받지 않는다 — 비용을 파일이 정하게 두지 않는다.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 64 * 1024 * 1024

MAX_BODY_BYTES = 1024
MAX_CODE_FILE_BYTES = 4096
MAX_STATE_BYTES = 256  # same cap root applies to this file (rosy-login-code.py)
#: D-193 보안 리뷰 M1: scrypt(N=2^14, r=8) takes 16 MiB; at most two at once, so
#: a burst of pairing requests cannot push CORE out of memory.
SCRYPT_SLOTS = threading.BoundedSemaphore(2)
PER_IP_LIMIT = 5
GLOBAL_LIMIT = 30
RATE_WINDOW_S = 60.0
MAX_WRONG_ATTEMPTS = 5
ENROLLMENT_TTL_S = 300.0
MAX_ENROLLMENT_CODES = 8
DEFAULT_LIFETIME_HOURS = {"viewer": 168.0, "operator": 168.0, "administrator": 24.0}

#: D-193 4: 사설·AP 대역과 루프백만 받는다. AP(10.42.0.0/24)는 10/8 안에 있다.
ALLOWED_NETWORKS = tuple(ipaddress.ip_network(net) for net in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128",
))

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

_log = logging.getLogger(__name__)


def normalize_code(text: str) -> str:
    """사람이 친 코드 → 8자 대문자. 하이픈·공백은 버린다."""
    return "".join(ch for ch in str(text) if ch not in "- \t").upper()


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def scrypt_digest(code: str, salt: bytes, *, n: int = SCRYPT_N, r: int = SCRYPT_R,
                  p: int = SCRYPT_P, dklen: int = SCRYPT_DKLEN) -> bytes:
    """발급자와 같은 검증자. 입력은 정규화된 8자 코드다."""
    return hashlib.scrypt(code.encode("ascii"), salt=salt, n=n, r=r, p=p, dklen=dklen,
                          maxmem=SCRYPT_MAXMEM)


def client_allowed(host: Optional[str]) -> bool:
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in ALLOWED_NETWORKS)


class _Window:
    """고정 길이 창 안의 요청 시각. 넘치면 다음에 비는 때까지의 초를 준다."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self.hits: collections.deque[float] = collections.deque()

    def retry_after(self, now: float) -> Optional[float]:
        while self.hits and now - self.hits[0] >= self.window:
            self.hits.popleft()
        if len(self.hits) >= self.limit:
            return self.window - (now - self.hits[0])
        return None


class PairingState:
    """앱마다 하나. 속도 제한, 틀린 시도, 소비된 코드, 등록 코드를 들고 있다."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.code_file = CODE_FILE
        self.state_file = STATE_FILE
        self.boot_id_file = BOOT_ID_FILE
        self.lock = threading.Lock()
        self.per_ip: dict[str, _Window] = {}
        self.global_window = _Window(GLOBAL_LIMIT, RATE_WINDOW_S)
        self.failures: dict[str, int] = {}
        self.spent: set[str] = set()
        self.enrollment: dict[str, dict[str, Any]] = {}

    # --- rate limit -------------------------------------------------------

    def admit(self, host: str) -> Optional[float]:
        """None 이면 받는다. 아니면 Retry-After 초."""
        now = self.clock()
        with self.lock:
            if len(self.per_ip) > 1024:
                for key in [key for key, win in self.per_ip.items()
                            if win.retry_after(now) is None and not win.hits]:
                    del self.per_ip[key]
            window = self.per_ip.setdefault(host, _Window(PER_IP_LIMIT, RATE_WINDOW_S))
            wait = window.retry_after(now)
            global_wait = self.global_window.retry_after(now)
            if wait is not None or global_wait is not None:
                return max(wait or 0.0, global_wait or 0.0)
            window.hits.append(now)
            self.global_window.hits.append(now)
            return None

    # --- the physical code -------------------------------------------------

    def _boot_id(self) -> Optional[str]:
        try:
            with open(self.boot_id_file, encoding="ascii") as handle:
                return handle.read().strip() or None
        except OSError:
            return None

    def physical_code(self) -> Optional[dict[str, Any]]:
        """root가 쓴 검증자. 매번 새로 읽는다(캐시 없음). 쓸 수 없으면 None."""
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
            | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(self.code_file, flags)
        except OSError:
            return None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CODE_FILE_BYTES:
                return None
            raw = os.read(descriptor, MAX_CODE_FILE_BYTES + 1)
        except OSError:
            return None
        finally:
            os.close(descriptor)
        if len(raw) > MAX_CODE_FILE_BYTES:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
            kdf = data["kdf"]
            code = {
                "code_id": str(data["code_id"]),
                "role": str(data["role"]),
                "source": str(data.get("source") or "pair-physical"),
                "salt": bytes.fromhex(str(kdf["salt"])),
                "digest": bytes.fromhex(str(data["digest"])),
                "boot_id": str(data["boot_id"]),
                "expires_monotonic": float(data["expires_monotonic"]),
            }
            params_ok = (kdf.get("name") == "scrypt" and kdf.get("n") == SCRYPT_N
                         and kdf.get("r") == SCRYPT_R and kdf.get("p") == SCRYPT_P
                         and kdf.get("dklen") == SCRYPT_DKLEN)
        except (UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError):
            return None
        if (not params_ok or not CODE_ID_RE.fullmatch(code["code_id"])
                or code["role"] not in ROLE_RANK or code["source"] != "pair-physical"
                or len(code["digest"]) != SCRYPT_DKLEN or not code["salt"]):
            return None
        if code["code_id"] in self.spent:
            return None
        # D-193 보안 리뷰 M1: what CORE already recorded for this code survives a
        # CORE restart (RuntimeDirectoryPreserve=restart): a used or burned code
        # stays dead and failed attempts keep counting.
        own = self.own_state()
        if own is not None and own["code_id"] == code["code_id"]:
            if own["state"] in {"used", "burned"} or own["attempts"] >= MAX_WRONG_ATTEMPTS:
                with self.lock:
                    self.spent.add(code["code_id"])
                return None
            with self.lock:
                self.failures[code["code_id"]] = max(self.failures.get(code["code_id"], 0), own["attempts"])
        # D-193 3: 같은 부팅이고 monotonic 시계가 만료 전일 때만 유효하다.
        if code["boot_id"] != self._boot_id() or not self.clock() < code["expires_monotonic"]:
            return None
        return code

    def own_state(self) -> Optional[dict[str, Any]]:
        """CORE's own state file, read as strictly as root reads it, or None."""
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
            | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(self.state_file, flags)
        except OSError:
            return None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STATE_BYTES:
                return None
            raw = os.read(descriptor, MAX_STATE_BYTES + 1)
        except OSError:
            return None
        finally:
            os.close(descriptor)
        try:
            data = json.loads(raw.decode("ascii")) if len(raw) <= MAX_STATE_BYTES else None
        except (UnicodeDecodeError, ValueError):
            return None
        if not isinstance(data, dict) or not CODE_ID_RE.fullmatch(str(data.get("code_id", ""))):
            return None
        attempts = data.get("attempts", 0)
        if data.get("state") not in {"used", "burned", "failing"} or not isinstance(attempts, int) \
                or isinstance(attempts, bool) or attempts < 0:
            return None
        return {"code_id": data["code_id"], "state": data["state"], "attempts": attempts}

    def signal_root(self, code_id: str, state: str, attempts: Optional[int] = None) -> None:
        """CORE → root 신호. 실패해도 코드는 CORE 안에서 이미 소비됐다.

        `failing` (with `attempts`) is CORE's own bookkeeping; root knows only
        `used` and `burned` and ignores anything else.
        """
        directory = os.path.dirname(self.state_file) or "."
        temporary = os.path.join(directory, f".login-code-state.{secrets.token_hex(6)}")
        record: dict[str, Any] = {"code_id": code_id, "state": state}
        if attempts is not None:
            record["attempts"] = attempts
        payload = json.dumps(record, sort_keys=True) + "\n"
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(temporary, flags, 0o644)
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(payload)
            os.replace(temporary, self.state_file)
        except OSError as exc:
            _log.warning("login code state not written: %s", type(exc).__name__)
            try:
                os.unlink(temporary)
            except OSError:
                pass

    # --- enrollment codes (CORE memory only) -------------------------------

    def live_enrollment(self) -> list[tuple[str, dict[str, Any]]]:
        now = self.clock()
        for code_id in [key for key, item in self.enrollment.items() if item["expires"] <= now]:
            del self.enrollment[code_id]
        return list(self.enrollment.items())

    def add_enrollment(self, code: str, role: str, issuer: str,
                       issuer_expires_at: Optional[str] = None) -> tuple[str, float]:
        code_id = secrets.token_hex(8)
        salt = secrets.token_bytes(16)
        with self.lock:
            live = self.live_enrollment()
            if len(live) >= MAX_ENROLLMENT_CODES:
                oldest = min(live, key=lambda pair: pair[1]["expires"])[0]
                del self.enrollment[oldest]
            self.enrollment[code_id] = {
                "salt": salt,
                "digest": hashlib.sha256(salt + code.encode("ascii")).digest(),
                "role": role,
                "issuer": issuer,
                # D-193 보안 리뷰 M2: a token enrolled by a paired admin ends with it.
                "issuer_expires_at": issuer_expires_at,
                "expires": self.clock() + ENROLLMENT_TTL_S,
            }
        return code_id, ENROLLMENT_TTL_S


def _pairing(request: Request) -> PairingState:
    state = getattr(request.app.state, "pairing", None)
    if state is None:
        state = request.app.state.pairing = PairingState()
    return state


def _lifetime_seconds(config: dict, role: str) -> float:
    """역할별 페어링 토큰 수명. 양수가 아닌 설정은 기본값 — 만료 없는 페어링은 없다."""
    configured = (((config.get("auth") or {}).get("pairing") or {})
                  .get("token_lifetime_hours") or {})
    hours = configured.get(role) if isinstance(configured, dict) else None
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        hours = DEFAULT_LIFETIME_HOURS[role]
    if not math.isfinite(hours) or hours <= 0:
        hours = DEFAULT_LIFETIME_HOURS[role]
    return hours * 3600.0


def _error(status: int, code: str, message: str, headers: Optional[dict] = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(code, message),
                        headers={**NO_STORE, **(headers or {})})


async def _read_body(request: Request) -> Optional[bytes]:
    """본문을 최대 MAX_BODY_BYTES 까지만 읽는다. 넘으면 None."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY_BYTES:
                return None
        except ValueError:
            return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return None
    return bytes(body)


def _match(state: PairingState, code: str,
           config: dict) -> tuple[Optional[dict[str, Any]], dict[str, bool]]:
    """(맞은 코드, 틀렸을 때 시도를 셀 코드 id → 물리 코드인가). 스레드풀에서 돈다."""
    candidates: dict[str, bool] = {}
    with state.lock:
        enrollment = state.live_enrollment()
        # D-193 보안 리뷰 L7: an enrollment code dies with its issuer's token.
        for code_id, item in list(enrollment):
            if not token_alive(config, item["issuer"]):
                state.enrollment.pop(code_id, None)
                enrollment.remove((code_id, item))
    for code_id, item in enrollment:
        candidates[code_id] = False
        presented = hashlib.sha256(item["salt"] + code.encode("ascii")).digest()
        if hmac.compare_digest(presented, item["digest"]):
            return ({"code_id": code_id, "role": item["role"], "source": "pair-admin",
                     "paired_via": item["issuer"], "issuer_expires_at": item["issuer_expires_at"]},
                    candidates)
    physical = state.physical_code()
    if physical is not None:
        candidates[physical["code_id"]] = True
        with SCRYPT_SLOTS:
            presented = scrypt_digest(code, physical["salt"])
        if hmac.compare_digest(presented, physical["digest"]):
            return ({"code_id": physical["code_id"], "role": physical["role"],
                     "source": "pair-physical", "paired_via": physical["code_id"],
                     "issuer_expires_at": None}, candidates)
    return None, candidates


class PairRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    label: str = Field(default="", max_length=64)


@auth_router.post("/pair", status_code=201)
async def pair(request: Request, svc: CoreServicesLike = Depends(get_services)):
    """로그인 코드 → 이 브라우저 전용 만료 토큰 (인증 없음, D-193 4)."""
    host = request.client.host if request.client else ""
    if not client_allowed(host):
        return _error(403, "FORBIDDEN", "pairing is accepted only from the robot LAN")
    state = _pairing(request)
    wait = state.admit(host)
    if wait is not None:
        return _error(429, "RATE_LIMITED", "too many pairing attempts",
                      {"Retry-After": str(max(1, math.ceil(wait)))})
    raw = await _read_body(request)
    if raw is None:
        return _error(413, "VALIDATION_ERROR", f"request body is larger than {MAX_BODY_BYTES} bytes")
    try:
        body = PairRequest.model_validate_json(raw)
    except ValueError:
        return _error(400, "VALIDATION_ERROR", "body must be {code, label?}")
    code = normalize_code(body.code)
    if not CODE_RE.fullmatch(code):
        return _error(400, "VALIDATION_ERROR", "a login code is 8 characters like ABCD-EFGH")

    matched, candidates = await run_in_threadpool(_match, state, code, svc.config)
    burned: list[tuple[str, bool]] = []  # (code_id, physical)
    failing: list[tuple[str, int]] = []  # physical code still alive after a miss
    # D-193 보안 리뷰 L4: while an administrator's enrollment code is live, a miss
    # counts against it, not the boot code: one visitor cannot burn both, and the
    # enrollment code is the one its issuer can simply reissue.
    enrollment_live = any(not physical for physical in candidates.values())
    with state.lock:
        if matched is not None and matched["code_id"] in state.spent:
            matched = None  # another request used it while this one was hashing
        if matched is None:
            for code_id, physical in candidates.items():
                if code_id in state.spent or (physical and enrollment_live):
                    continue
                state.failures[code_id] = state.failures.get(code_id, 0) + 1
                if state.failures[code_id] >= MAX_WRONG_ATTEMPTS:
                    state.spent.add(code_id)
                    state.enrollment.pop(code_id, None)
                    burned.append((code_id, physical))
                elif physical:
                    failing.append((code_id, state.failures[code_id]))
        else:
            state.spent.add(matched["code_id"])
            state.enrollment.pop(matched["code_id"], None)
    for code_id, attempts in failing:
        # Persisted so a CORE restart does not reset the count (M1); root ignores it.
        state.signal_root(code_id, "failing", attempts)
    for code_id, physical in burned:
        if physical:  # root clears only the code it issued; enrollment codes live here
            state.signal_root(code_id, "burned")
        svc.events.publish("auth.code_burned", severity="warning", source="api",
                           data={"code_id": code_id, "attempts": MAX_WRONG_ATTEMPTS})
    if matched is None:
        return _error(401, "UNAUTHORIZED", "invalid or expired login code")

    if matched["source"] == "pair-physical":
        state.signal_root(matched["code_id"], "used")
    role = matched["role"]
    token = generate_token()
    expires_at = expires_before(utc_after(_lifetime_seconds(svc.config, role)),
                                matched["issuer_expires_at"])
    label = body.label.strip() or ("robot screen login" if matched["source"] == "pair-physical"
                                   else "enrolled device")
    record = new_token_record(token, role, label, source=matched["source"],
                              expires_at=expires_at, paired_via=matched["paired_via"])
    with TOKEN_WRITE_LOCK:
        records = auth_entries(svc.config)
        records.append(record)
        persist_token_records(svc, records)
    # 코드도 토큰도 싣지 않는다. 누가(id) 어떤 권한으로 언제까지 붙었는지만 남긴다.
    svc.events.publish("auth.paired", severity="warning", source="api",
                       data={"id": record["id"], "role": role, "source": matched["source"],
                             "expires_at": expires_at})
    return JSONResponse(status_code=201, headers=NO_STORE, content={
        "id": record["id"],
        "token": token,  # 원문이 나가는 유일한 지점이다
        "role": role,
        "label": record["label"],
        "source": record["source"],
        "expires_at": expires_at,
    })


@auth_router.get("/whoami")
def whoami(auth: AuthContext = Depends(viewer)):
    """D-193 5: 대시보드가 역할을 추측하지 않고 묻는다."""
    return JSONResponse(headers=NO_STORE, content={
        "id": auth.token_id,
        "role": auth.role,
        "label": auth.label,
        "source": auth.source,
        "created_at": auth.created_at,
        "expires_at": auth.expires_at,
    })


@auth_router.post("/logout", status_code=204)
def logout(auth: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """자기 페어링 토큰만 지운다. 카드·수동 토큰은 설정 화면에서 회수한다."""
    if auth.source not in PAIRED_SOURCES:
        raise ApiError("VALIDATION_ERROR", 409,
                       "only a paired browser token can log out; revoke other tokens in settings")
    with TOKEN_WRITE_LOCK:
        records = auth_entries(svc.config)
        persist_token_records(svc, [item for item in records if item["id"] != auth.token_id])
    svc.events.publish("config.changed", severity="warning", source="api",
                       data={"key": "auth.tokens", "id": auth.token_id, "deleted": True})
    return Response(status_code=204, headers=NO_STORE)


class EnrollmentRequest(BaseModel):
    role: str = "operator"


@auth_router.post("/enrollment-codes", status_code=201)
def create_enrollment_code(body: EnrollmentRequest, request: Request,
                           auth: AuthContext = Depends(admin),
                           svc: CoreServicesLike = Depends(get_services)):
    """관리자가 자기 화면에서 다른 기기용 코드를 받는다. 5분, CORE 메모리에만."""
    role = body.role.strip()
    if role not in ROLE_RANK:
        raise ApiError("VALIDATION_ERROR", 400, "role must be viewer, operator or administrator")
    if ROLE_RANK[role] > auth.rank:
        raise ApiError("FORBIDDEN", 403, "an enrollment code cannot exceed the issuer's role")
    code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    code_id, ttl = _pairing(request).add_enrollment(code, role, auth.token_id, auth.expires_at)
    svc.events.publish("auth.enrollment_code_issued", severity="warning", source="api",
                       data={"code_id": code_id, "role": role, "by": auth.token_id})
    return JSONResponse(status_code=201, headers=NO_STORE, content={
        "code": format_code(code),
        "code_id": code_id,
        "role": role,
        "expires_in_s": int(ttl),
    })
