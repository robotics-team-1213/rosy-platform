"""신호등 컨트롤러(ROSY-SIGNAL-001) 응답 파서·3자 교차 검증·관측 클라이언트 도우미."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

import httpx

from fleet.server.signal_config import EXPECTED_GROUPS

HTTP_TIMEOUT_S = 1.5      # 폴링이 로봇 gather 를 지연시키지 않게 짧게


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
        return "absent", []
    if not isinstance(observed, dict) or not isinstance(observed.get("stable"), dict):
        return "bad_response", ["obs_shape"]
    if observed.get("frozen"):
        return "stale", ["obs_stale"]
    mapping = dict(lamp_to_roi or {})
    if not mapping:
        return "unmapped", []
    stable = observed["stable"]
    if any(isinstance(stable.get(roi), dict) and stable[roi].get("pending")
           for roi in mapping.values()):
        return "pending", []
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
        if not isinstance(row.get("lit"), bool):
            return "unknown", []
        lit = bool(row.get("lit"))
        if _on(status_lamps, lamp) and not lit:
            faults.append(f"obs_dark:{lamp}")
        elif not _on(status_lamps, lamp) and lit:
            faults.append(f"obs_ghost:{lamp}")
        elif lit and row.get("group") not in expected:
            faults.append(f"obs_color:{lamp}:{row.get('group')}")
    return ("display_mismatch", faults) if faults else ("agree", [])


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


def signal_error_of(exc: BaseException) -> dict:
    if isinstance(exc, SignalApiError):
        return {"code": exc.code, "message": str(exc), "reachable": True,
                "signal_id": exc.signal_id}
    return {"code": type(exc).__name__, "message": str(exc), "reachable": False}


def signal_observer_error_of(exc: BaseException) -> dict:
    if isinstance(exc, ObserverError):
        return {"code": exc.code, "message": exc.message, "reachable": exc.reachable}
    return {"code": type(exc).__name__, "message": str(exc), "reachable": False}
