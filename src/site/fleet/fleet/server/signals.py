"""Fleet 콘솔과 신호등 컨트롤러(ROSY-SIGNAL-001)의 연결 — gather 와 scatter.

`swarm/` 이 로봇 계약 전용이듯, 이 모듈은 신호등 계약 전용이다. `swarm.transport` 가
"로봇 계약을 부르는 유일한 곳"인 규칙을 지키려고 굳이 새 파일을 냈다 — 다른 계약이
그 파일에 스며들면 경계가 무너진다.

장치 쪽 규칙은 장치가 지킨다: 부팅·감독자 침묵 → 적색 점멸. 여기서 하는 일은
(1) 상태를 모으고, (2) 명령을 내리고, (3) `mode=failsafe` 를 보면 **운영자의 마지막
의도를 한 번만 다시 내려보내는 것**이다. 무한 재시도는 명령 스톰이고, 스톰은 장치의
하트비트 예산을 잡아먹는다.

폴링은 상시 루프가 아니라 **요청 시 갱신**이다 — `refresh()` 가 주기 제한(2 s)을 두고
한 틱을 돌리고, 관제 UI 가 `/api/fleet/state` 를 계속 당기는 것이 그 주기를 만든다.
관제가 보지 않으면 장치는 스스로 페일세이프로 간다. 그것은 고장이 아니라 장치 계약의
뜻대로다: 아무도 감독하지 않는 신호는 신뢰할 수 없음을 보여야 한다.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence

import httpx
import yaml

from fleet.hub.hub import HubError

POLL_INTERVAL_S = 2.0     # 장치 하트비트 타임아웃(10 s)의 5 배 밀도
HTTP_TIMEOUT_S = 1.5      # 폴링이 로봇 gather 를 지연시키지 않게 짧게
REASSERT_LIMIT = 1        # failsafe 재단언은 실패해도 한 번 — 나머지는 운영자 몫
#: 장치 램프 이름 → 관측 색상군 기대치. 노란 램프는 관측에서 orange 군으로, 청록
#: 계열 녹색은 green/blue 경계로 온다 — 3자 교차 검증(관측 설계 §3)의 대조표다.
EXPECTED_GROUPS: dict[str, tuple[str, ...]] = {
    "red": ("red",),
    "yellow": ("orange",),
    "green": ("green", "blue"),
}


class SignalsFileError(ValueError):
    """signals.yaml 을 읽을 수 없다."""


@dataclass(frozen=True)
class SignalEndpoint:
    signal_id: str
    base_url: str   # 끝 슬래시 없음
    token: str
    #: 관측 서비스의 `/observed` — 없으면 3자 교차 검증은 꺼진다(verify=absent).
    observer_url: Optional[str] = None
    #: 장치 램프 이름 → 관측 ROI 이름. B0 사이클 지도(운영자)가 채운다.
    observer_map: Optional[dict] = None


_REQUIRED = ("signal_id", "base_url", "token")


def _endpoint(signal_id, base_url, token, where: str, *,
              observer_url: Optional[str] = None,
              observer_map: Optional[dict] = None) -> SignalEndpoint:
    """`swarm.robots._endpoint` 와 같은 규칙 — 두 로더가 갈라지면 배포가 갈라진다.

    토큰은 따옴표 문자열이어야 한다(YAML 1.1 이 `01234567` 을 8진으로, `yes` 를
    불로 읽는 문제는 robots.yaml 쪽에서 이미 겪은 것이다). 스킴이 없으면 URL 이
    조용히 깨진다 — 연결 시점이 아니라 여기서 거절한다.
    """
    if not signal_id or not base_url or not token:
        raise SignalsFileError(f"{where}: signal_id, base_url and token are all required")
    for key, value in (("base_url", base_url), ("token", token)):
        if not isinstance(value, str):
            raise SignalsFileError(f"{where}: '{key}' must be a quoted string, not {type(value).__name__}")
    base_url = base_url.rstrip("/")
    if not base_url.lower().startswith(("http://", "https://")):
        raise SignalsFileError(f"{where}: base_url needs an http:// or https:// scheme")
    if observer_url is not None:
        if not isinstance(observer_url, str) or not observer_url.lower().startswith(
                ("http://", "https://")):
            raise SignalsFileError(f"{where}: observer_url needs an http(s) scheme")
        observer_url = observer_url.rstrip("/")
    if observer_map is not None:
        if not isinstance(observer_map, dict) or not observer_map:
            raise SignalsFileError(f"{where}: observer_map must be a non-empty mapping")
        bad_keys = [k for k in observer_map if k not in EXPECTED_GROUPS]
        bad_vals = [v for v in observer_map.values()
                    if not isinstance(v, str) or not v]
        if bad_keys or bad_vals:
            raise SignalsFileError(
                f"{where}: observer_map maps device lamps red/yellow/green to ROI names")
        observer_map = dict(observer_map)
    return SignalEndpoint(str(signal_id), base_url, token, observer_url, observer_map)


def load_signals(path: Path) -> list[SignalEndpoint]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SignalsFileError(f"{path}: cannot read signals file: {exc}") from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise SignalsFileError(f"{path}: not valid YAML: {exc}") from exc
    rows = data.get("signals") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise SignalsFileError(f"{path}: needs a non-empty 'signals' list")
    seen: set[str] = set()
    out: list[SignalEndpoint] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SignalsFileError(f"{path}: signals[{i}] is not a mapping")
        for key in _REQUIRED:
            if not row.get(key):
                raise SignalsFileError(f"{path}: signals[{i}] is missing '{key}'")
        endpoint = _endpoint(row["signal_id"], row["base_url"], row["token"],
                             f"{path}: signals[{i}]",
                             observer_url=row.get("observer_url"),
                             observer_map=row.get("observer_map"))
        if endpoint.signal_id in seen:
            raise SignalsFileError(f"{path}: duplicate signal_id {endpoint.signal_id!r}")
        seen.add(endpoint.signal_id)
        out.append(endpoint)
    return out


def write_signals(path: Path, signals: list[SignalEndpoint]) -> None:
    """로더가 받아들이는 signals.yaml 을 쓴다. 쓰기 전에 로더 규칙을 통과시킨다."""
    if not signals:
        raise SignalsFileError("every signal needs signal_id, base_url and token")
    normalized = [_endpoint(s.signal_id, s.base_url, s.token, f"signals[{i}]",
                            observer_url=s.observer_url, observer_map=s.observer_map)
                  for i, s in enumerate(signals)]
    ids = [s.signal_id for s in normalized]
    if len(set(ids)) != len(ids):
        raise SignalsFileError(f"duplicate signal_id in {ids}")
    rows: list[dict[str, Any]] = []
    for s in normalized:
        row: dict[str, Any] = {"signal_id": s.signal_id, "base_url": s.base_url,
                               "token": s.token}
        if s.observer_url is not None:
            row["observer_url"] = s.observer_url
        if s.observer_map is not None:
            row["observer_map"] = dict(s.observer_map)
        rows.append(row)
    target = Path(path)
    text = yaml.safe_dump({"signals": rows}, sort_keys=False)
    # robots.yaml 과 같은 등급의 비밀 파일이다 — 소유자만 읽게 연다(POSIX).
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass  # Windows 는 chmod 를 무시한다 — robots.py 와 같은 태도다


class SignalApiError(Exception):
    """신호등이 4xx/5xx 를 돌려줬다. 장치 본문의 `error` 코드를 그대로 옮긴다."""

    def __init__(self, signal_id: str, status: int, code: str, message: str,
                 last_seq: Optional[int] = None) -> None:
        super().__init__(f"{signal_id}: {code} ({status}) {message}")
        self.signal_id = signal_id
        self.status = status
        self.code = code
        self.message = message
        self.last_seq = last_seq  # 409 stale_seq 때 장치가 알려 주는 장치 쪽 마지막 seq


@dataclass(frozen=True)
class SignalStatus:
    signal_id: str
    mode: str
    lamps: dict[str, bool]          # {"red": .., "yellow": .., "green": ..} — 구동값
    seq: int                        # 장치가 마지막으로 수용한 명령 seq (부팅 후 0)
    faults: tuple[str, ...]
    secs_since_contact: Optional[int]
    firmware: Optional[str]

    def as_row(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "lamps": dict(self.lamps),
            "seq": self.seq,
            "faults": list(self.faults),
            "secs_since_contact": self.secs_since_contact,
            "firmware": self.firmware,
        }


def parse_status(signal_id: str, payload: Any) -> SignalStatus:
    """장치 본문 → `SignalStatus`. `mode`·`lamps` 는 필수다 — 누락은 false 가 아니라
    오류다(독의 `load_present` 교훈: "모른다"와 "꺼져 있다"를 합치면 안 된다)."""
    if not isinstance(payload, dict):
        raise SignalApiError(signal_id, 200, "BAD_RESPONSE",
                             f"expected a JSON object, got {type(payload).__name__}")
    mode = payload.get("mode")
    lamps = payload.get("lamps")
    if not isinstance(mode, str) or not mode:
        raise SignalApiError(signal_id, 200, "BAD_RESPONSE", "missing 'mode'")
    if not isinstance(lamps, dict) or any(k not in lamps for k in ("red", "yellow", "green")):
        raise SignalApiError(signal_id, 200, "BAD_RESPONSE",
                             "missing 'lamps' with red/yellow/green")
    faults = payload.get("faults")
    contact = payload.get("secs_since_contact")
    seq = payload.get("seq", 0)
    return SignalStatus(
        signal_id=signal_id,
        mode=mode,
        lamps={k: bool(lamps[k]) for k in ("red", "yellow", "green")},
        seq=int(seq) if isinstance(seq, (int, float)) else 0,
        faults=tuple(str(f) for f in faults) if isinstance(faults, list) else (),
        secs_since_contact=int(contact) if isinstance(contact, (int, float)) else None,
        firmware=str(payload["firmware"]) if "firmware" in payload else None,
    )


def cross_check(intent_lamps: Optional[dict], status_lamps: dict,
                observed: Optional[dict] = None, *,
                lamp_to_roi: Optional[Mapping[str, str]] = None) -> tuple[str, list[str]]:
    """3자 교차 검증(관측 설계 §3)의 순수 판정 — 소비자(폴링·UI)가 붙여 쓴다.

    (1) 의도 vs (2) 장치 보고 → `controller_mismatch`, (2) vs (3) 관측 실측 →
    `display_mismatch`. `intent_lamps` 는 아직 없을 수 있다(None 이면 1≠2 를
    건너뛴다 — "의도 없음"과 "의도 전부 꺼짐"은 같지 않다). `observed` 는 관측
    `/observed` 본문이고, ROI 이름은 `lamp_to_roi`(램프→ROI)로 옮긴다 — 매핑은
    사이클 지도(운영자)의 것이며 여기서 지어내지 않는다. 관측이 `frozen` 이면
    오래된 증거라 불일치를 말할 수 없다(`stale` 로 답한다).
    """

    def _on(lamps: dict, key: str) -> bool:
        return bool(lamps.get(key))

    if intent_lamps is not None:
        disagree = [lamp for lamp in EXPECTED_GROUPS
                    if _on(intent_lamps, lamp) != _on(status_lamps, lamp)]
        if disagree:
            return "controller_mismatch", [f"cmd_vs_device:{lamp}" for lamp in disagree]
    if observed is None:
        return "agree", []
    if not isinstance(observed, dict) or not isinstance(observed.get("stable"), dict):
        return "bad_response", ["obs_shape"]
    if observed.get("frozen"):
        return "stale", ["obs_stale"]
    mapping = dict(lamp_to_roi or {})
    if not mapping:
        return "unmapped", []
    stable = observed["stable"]
    faults: list[str] = []
    for lamp, roi in mapping.items():
        expected = EXPECTED_GROUPS.get(lamp)
        if expected is None:
            continue                    # 지도의 오타는 여기서 새 판정을 만들지 않는다
        row = stable.get(roi)
        if not isinstance(row, dict):
            faults.append(f"obs_missing:{lamp}")
            continue
        if row.get("pending"):
            continue                     # debounce 확정 전 — 불일치를 말할 수 없다
        lit = bool(row.get("lit"))
        if _on(status_lamps, lamp) and not lit:
            faults.append(f"obs_dark:{lamp}")
        elif not _on(status_lamps, lamp) and lit:
            faults.append(f"obs_ghost:{lamp}")
        elif lit and row.get("group") not in expected:
            faults.append(f"obs_color:{lamp}:{row.get('group')}")
    return ("display_mismatch", faults) if faults else ("agree", [])


class SignalClient(Protocol):
    signal_id: str

    async def status(self) -> SignalStatus: ...
    async def command(self, body: dict) -> SignalStatus: ...
    async def aclose(self) -> None: ...


class HttpSignalClient:
    """장치 계약(ROSY-SIGNAL-001)의 클라이언트. 토큰은 `X-Rosy-Token` 헤더로 간다.

    토큰 유효 요청만이 장치의 하트비트로 섞인다 — 이 헤더가 곧 감독의 증거다.
    """

    def __init__(self, endpoint: SignalEndpoint, *, http: Optional[httpx.AsyncClient] = None,
                 timeout_s: float = HTTP_TIMEOUT_S) -> None:
        self.signal_id = endpoint.signal_id
        self._ep = endpoint
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(base_url=endpoint.base_url, timeout=timeout_s)

    def _headers(self) -> dict[str, str]:
        return {"X-Rosy-Token": self._ep.token}

    def _check(self, resp: httpx.Response) -> dict:
        if resp.status_code < 400:
            try:
                data = resp.json()
            except ValueError as exc:
                raise SignalApiError(self.signal_id, resp.status_code, "BAD_RESPONSE",
                                     f"expected a JSON object, got {resp.text[:120]!r}") from exc
            if not isinstance(data, dict):
                raise SignalApiError(self.signal_id, resp.status_code, "BAD_RESPONSE",
                                     f"expected a JSON object, got {type(data).__name__}")
            return data
        code, message, last_seq = f"HTTP_{resp.status_code}", resp.text, None
        try:
            err = resp.json().get("error")
            if err:
                code = str(err)
                body = resp.json()
                if isinstance(body.get("last_seq"), int):
                    last_seq = body["last_seq"]
                message = str(body.get("message") or message)
        except (ValueError, AttributeError):
            pass
        raise SignalApiError(self.signal_id, resp.status_code, code, message, last_seq)

    async def status(self) -> SignalStatus:
        resp = await self._http.get("/status", headers=self._headers())
        return parse_status(self.signal_id, self._check(resp))

    async def command(self, body: dict) -> SignalStatus:
        resp = await self._http.post("/command", json=body, headers=self._headers())
        return parse_status(self.signal_id, self._check(resp))

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()


class SignalObserver(Protocol):
    """관측 서비스(`/observed`) 클라이언트 — 읽기 전용 증거 공급자."""

    async def observed(self) -> dict: ...
    async def aclose(self) -> None: ...


class ObserverError(Exception):
    """관측 서버에 못 다가갔다(또는 엉망인 응답). 교차 검증은 이를 '모른다'로 둔다."""

    def __init__(self, code: str, message: str, *, reachable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.reachable = reachable      # 서버가 대답했으면(4xx/5xx) 다가간 것은 맞다


class HttpSignalObserver:
    """관측 서비스의 `/observed` 클라이언트. 토큰도 명령 경로도 없다 — 읽기 하나."""

    def __init__(self, base_url: str, *, http: Optional[httpx.AsyncClient] = None,
                 timeout_s: float = HTTP_TIMEOUT_S) -> None:
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(base_url=base_url.rstrip("/"),
                                               timeout=timeout_s)

    async def observed(self) -> dict:
        try:
            resp = await self._http.get("/observed")
        except httpx.HTTPError as exc:
            raise ObserverError("OBSERVER_UNREACHABLE", str(exc)) from exc
        if resp.status_code >= 400:
            raise ObserverError(f"HTTP_{resp.status_code}", resp.text[:120],
                                reachable=True)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ObserverError("BAD_RESPONSE", "observer did not answer JSON") from exc
        if not isinstance(data, dict):
            raise ObserverError("BAD_RESPONSE",
                                f"expected object, got {type(data).__name__}")
        return data

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()


class SignalConsole:
    """신호등 N기의 상태 캐시 + 운영자 의도 기억 + failsafe 재단언.

    재단언이 "무한 재시도"가 아닌 이유: 장치가 페일세이프에 들어간 데에는 이유가
    있다(부팅, 침묵, 불일치). 한 번의 재단언으로 안 돌아온다면 그 이유가 아직 살아
    있다는 뜻이고, 화면은 그 사실을 보여 주고 운영자 손을 기다리는 것이 맞다.
    """

    def __init__(self, endpoints: Sequence[SignalEndpoint], clients: Sequence[SignalClient],
                 *, clock=time.monotonic, poll_interval_s: float = POLL_INTERVAL_S,
                 observers: Optional[Mapping[str, SignalObserver]] = None) -> None:
        if len(endpoints) != len(clients):
            raise ValueError("endpoints and clients must line up one for one")
        self._clients: dict[str, SignalClient] = {
            ep.signal_id: client for ep, client in zip(endpoints, clients)
        }
        self._order = [ep.signal_id for ep in endpoints]
        #: 관측 클라이언트 — endpoint.observer_url 이 있으면 자동으로 붙는다(없으면
        #: 교차 검증은 꺼진다). 시험은 `observers` 로 가짜를 주입한다.
        self._observers: dict[str, Optional[SignalObserver]] = {}
        self._observer_map: dict[str, Optional[dict]] = {}
        for ep in endpoints:
            observer = (observers or {}).get(ep.signal_id)
            if observer is None and ep.observer_url:
                observer = HttpSignalObserver(ep.observer_url)
            self._observers[ep.signal_id] = observer
            self._observer_map[ep.signal_id] = (
                dict(ep.observer_map) if ep.observer_map else None)
        self._observed: dict[str, Optional[dict]] = {sid: None for sid in self._order}
        self._observer_error: dict[str, Optional[dict]] = {sid: None for sid in self._order}
        self._clock = clock
        self._poll_interval_s = poll_interval_s
        self._status: dict[str, Optional[SignalStatus]] = {sid: None for sid in self._order}
        self._online: dict[str, bool] = {sid: False for sid in self._order}
        self._error: dict[str, Optional[dict]] = {sid: None for sid in self._order}
        self._intent: dict[str, dict] = {}      # 마지막 성공 명령 (seq 빼고)
        self._seq: dict[str, int] = {sid: 0 for sid in self._order}
        self._reasserts: dict[str, int] = {sid: 0 for sid in self._order}
        self._mismatch: dict[str, Optional[str]] = {sid: None for sid in self._order}
        self._last_poll = float("-inf")

    @property
    def signal_ids(self) -> list[str]:
        return list(self._order)

    def _client(self, signal_id: str) -> SignalClient:
        client = self._clients.get(signal_id)
        if client is None:
            raise HubError("UNKNOWN_SIGNAL", signal_id)
        return client

    # --- scatter ---------------------------------------------------------------

    async def command(self, signal_id: str, body: dict, *, _is_reassert: bool = False) -> dict:
        """운영자 명령 한 건. `seq` 는 콘솔이 채운다 — 장치의 단조 검사는 장치 몫이다."""
        client = self._client(signal_id)
        seq = self._seq.get(signal_id, 0) + 1
        full = {"seq": seq, **body}
        try:
            status = await client.command(full)
        except SignalApiError as exc:
            if exc.code == "stale_seq":
                # 장치의 장부가 우리 것보다 앞서 있다(다른 클라이언트의 흔적, 또는
                # 우리가 놓친 재시작). 장치 진실을 채택하고 불일치로 남긴다 — 조용히
                # 밀어 붙이면 운영자는 왜 명령이 안 먹는지 영영 모른다.
                if exc.last_seq is not None:
                    self._seq[signal_id] = exc.last_seq
                self._mismatch[signal_id] = "stale_seq"
                return self._row(signal_id)
            raise
        self._seq[signal_id] = seq
        self._intent[signal_id] = {k: v for k, v in body.items() if k != "seq"}
        if not _is_reassert:
            self._reasserts[signal_id] = 0
        self._mismatch[signal_id] = None
        self._record(signal_id, status)
        return self._row(signal_id)

    async def all_red(self) -> dict:
        """전 기기 `all_red`. e-stop 의 신호등 반쪽이다 — 한 기가 죽어도 나머지에
        내리고, 누가 섰는지는 본문으로 돌려준다(로봇 e-stop 과 같은 규칙)."""
        results = await asyncio.gather(
            *(self._scatter_all_red(sid) for sid in self._order),
            return_exceptions=True,
        )
        rows, ok = [], 0
        for signal_id, result in zip(self._order, results):
            if isinstance(result, BaseException):
                rows.append({"signal_id": signal_id, "all_red": False,
                             "error": _error_of(result)})
            else:
                ok += 1
                rows.append(result)
        return {"all_red": ok, "total": len(rows), "signals": rows}

    async def _scatter_all_red(self, signal_id: str) -> dict:
        row = await self.command(signal_id, {"mode": "all_red"})
        if row.get("mismatch") == "stale_seq":
            raise SignalApiError(
                signal_id, 409, "stale_seq", "all_red was not applied",
                self._seq.get(signal_id),
            )
        return {"signal_id": signal_id, "all_red": True}

    # --- gather ----------------------------------------------------------------

    async def poll_once(self) -> None:
        """모든 기기를 한 번씩 본다. 한 기가 죽어도 나머지는 갱신된다."""
        results = await asyncio.gather(
            *(self._client(sid).status() for sid in self._order),
            return_exceptions=True,
        )
        for signal_id, result in zip(self._order, results):
            if isinstance(result, BaseException):
                self._online[signal_id] = False
                self._error[signal_id] = _error_of(result)
            else:
                self._record(signal_id, result)
        await self._observe_all()          # 3자 교차 검증의 3 번째 증거(관측 실측)
        await self._reassert_failsafes()

    async def _observe_all(self) -> None:
        """관측 폴링 — 한 기의 침묵이 다른 기의 실측을 지우지 않게 개별 실패를 흡수한다."""
        sids = [sid for sid in self._order if self._observers.get(sid) is not None]
        if not sids:
            return
        results = await asyncio.gather(
            *(self._observers[sid].observed() for sid in sids), return_exceptions=True)
        for sid, result in zip(sids, results):
            if isinstance(result, BaseException):
                self._observed[sid] = None
                self._observer_error[sid] = _observer_error_of(result)
            else:
                self._observed[sid] = result
                self._observer_error[sid] = None

    async def refresh(self) -> None:
        """주기 제한이 걸린 폴링. UI 의 `/api/fleet/state` 가 이 주기를 만든다."""
        now = self._clock()
        if now - self._last_poll < self._poll_interval_s:
            return
        self._last_poll = now
        await self.poll_once()

    async def _reassert_failsafes(self) -> None:
        for signal_id in self._order:
            status = self._status.get(signal_id)
            if status is None or not self._online[signal_id]:
                continue
            if status.mode != "failsafe":
                # 살아 돌아왔으면 이 실패 에피소드는 끝난 것이다.
                self._reasserts[signal_id] = 0
                continue
            intent = self._intent.get(signal_id)
            if not intent or self._reasserts[signal_id] >= REASSERT_LIMIT:
                continue
            self._reasserts[signal_id] += 1
            try:
                await self.command(signal_id, dict(intent), _is_reassert=True)
            except Exception:
                pass  # 재단언 실패는 다음 폴링의 상태로 보인다 — 여기서 소리치지 않는다

    # --- 상태 -------------------------------------------------------------------

    def _record(self, signal_id: str, status: SignalStatus) -> None:
        self._status[signal_id] = status
        self._online[signal_id] = True
        self._error[signal_id] = None
        self._recompute_mismatch(signal_id, status)

    def _recompute_mismatch(self, signal_id: str, status: SignalStatus) -> None:
        """의도 vs 장치 보고를 다시 본다 — 단, `stale_seq` 장부는 `command()` 가 쥔다.
        여기서 덮으면 운영자가 추적할 단서(다른 클라이언트의 흔적)가 사라진다."""
        if self._mismatch.get(signal_id) == "stale_seq":
            return
        intent = self._intent.get(signal_id) or {}
        lamps = intent.get("lamps")
        if not isinstance(lamps, dict) or intent.get("mode") != status.mode:
            self._mismatch[signal_id] = None
            return
        state, _ = cross_check(lamps, status.lamps)
        self._mismatch[signal_id] = state if state != "agree" else None

    def _verify_row(self, signal_id: str) -> dict:
        """3자 교차 검증의 현재 상태. 관측이 없으면 `absent` — 지어낸 답은 없다."""
        if self._observers.get(signal_id) is None:
            return {"state": "absent", "faults": []}
        error = self._observer_error.get(signal_id)
        if error is not None:
            return {"state": "unreachable", "faults": [], "error": error}
        observed = self._observed.get(signal_id)
        if observed is None:
            return {"state": "absent", "faults": []}
        summary = {"frame_id": observed.get("frame_id"),
                   "content_age_s": observed.get("age_s"),
                   "frozen": bool(observed.get("frozen"))}
        status = self._status.get(signal_id)
        if status is None:
            return {"state": "unknown", "faults": [], "observer": summary}
        intent = self._intent.get(signal_id) or {}
        intent_lamps = intent.get("lamps") if isinstance(intent.get("lamps"), dict) else None
        state, faults = cross_check(intent_lamps, status.lamps, observed,
                                    lamp_to_roi=self._observer_map.get(signal_id))
        return {"state": state, "faults": faults, "observer": summary}

    def _row(self, signal_id: str) -> dict:
        status = self._status.get(signal_id)
        row: dict[str, Any] = {
            "signal_id": signal_id,
            "online": self._online[signal_id],
            "intent": self._intent.get(signal_id),
            "mismatch": self._mismatch[signal_id],
            "verify": self._verify_row(signal_id),
        }
        if status is not None:
            row.update(status.as_row())
        if self._error[signal_id] is not None:
            row["error"] = self._error[signal_id]
        return row

    def snapshot(self) -> dict:
        """캐시를 읽는다 — 폴링을 기다리지 않는다. UI 의 한 번의 poll 로 그려진다."""
        return {sid: self._row(sid) for sid in self._order}

    async def aclose(self) -> None:
        targets: list[Any] = list(self._clients.values())
        targets += [o for o in self._observers.values() if o is not None]
        await asyncio.gather(*(t.aclose() for t in targets), return_exceptions=True)


def _error_of(exc: BaseException) -> dict:
    if isinstance(exc, SignalApiError):
        return {"code": exc.code, "message": str(exc), "reachable": True,
                "signal_id": exc.signal_id}
    return {"code": type(exc).__name__, "message": str(exc), "reachable": False}


def _observer_error_of(exc: BaseException) -> dict:
    if isinstance(exc, ObserverError):
        return {"code": exc.code, "message": exc.message, "reachable": exc.reachable}
    return {"code": type(exc).__name__, "message": str(exc), "reachable": False}
