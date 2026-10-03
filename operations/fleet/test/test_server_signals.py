"""신호등 연동 — 로더, 파서, 콘솔(재단언·scatter), 관제 HTTP 표면.

네트워크도 sleep 도 없다. 장치는 `fake_signals.FakeSignal` 이고, 시계는 주입한다.
이 계층의 다른 시험과 같이 동기 함수 + `asyncio.run()` 이다 (pytest-asyncio 없음).
"""

from __future__ import annotations

import asyncio

import pytest
import yaml
from fastapi.testclient import TestClient

from fake_signals import FakeObserver, FakeSignal, observed_body
from fakes import FakeRobot
from fleet.hub.hub import HubError
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.signals import (
    SignalApiError,
    SignalConsole,
    SignalEndpoint,
    SignalsFileError,
    cross_check,
    load_signals,
    parse_status,
    write_signals,
)
from fleet.swarm.robots import RobotEndpoint

SIG1 = SignalEndpoint("signal_1", "http://127.0.0.1:9081", "t1")
SIG2 = SignalEndpoint("signal_2", "http://127.0.0.1:9082", "t2")
#: 관측까지 붙은 기기 — B0 사이클 지도(램프 → ROI)가 함께 들어간 형태.
SIG_OBS = SignalEndpoint(
    "signal_1", "http://127.0.0.1:9081", "t1",
    observer_url="http://127.0.0.1:8095",
    observer_map={"red": "left", "yellow": "mid", "green": "right"})


def _console(*fakes: FakeSignal, clock=lambda: 0.0) -> SignalConsole:
    eps = [SIG1, SIG2][:len(fakes)]
    return SignalConsole(eps, list(fakes), clock=clock)


def _observed(*, red=True, yellow=False, green=False, pending=False, frozen=False) -> dict:
    """3 ROI 관측 본문 — 기본은 기기 보고와 같은 모양(agree 전제)."""
    lamps = {
        "left": {"lit": red, "group": "red" if red else None, "confidence": 1.0},
        "mid": {"lit": yellow, "group": "orange" if yellow else None, "confidence": 1.0},
        "right": {"lit": green, "group": "green" if green else None, "confidence": 1.0},
    }
    return observed_body(lamps=lamps, pending=pending, frozen=frozen)


def _client(*, signals: SignalConsole = None, robots=(), token=None) -> TestClient:
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    console = FleetConsole(endpoints, list(robots), signal_console=signals)
    return TestClient(create_app(console, console_token=token))


# --- loader -------------------------------------------------------------------

def test_loader_roundtrips_and_keeps_order(tmp_path):
    path = tmp_path / "signals.yaml"
    write_signals(path, [SIG1, SIG2])
    assert load_signals(path) == [SIG1, SIG2]


@pytest.mark.parametrize("row", [
    {"signal_id": "signal_1", "base_url": "http://x", "token": 123},      # 따옴표 없는 토큰
    {"signal_id": "signal_1", "base_url": "10.0.0.5", "token": "t"},      # 스킴 없음
    {"signal_id": "signal_1", "base_url": "http://x"},                    # 토큰 없음
])
def test_loader_rejects_the_shapes_that_bit_us_before(tmp_path, row):
    path = tmp_path / "signals.yaml"
    path.write_text(yaml.safe_dump({"signals": [row]}), encoding="utf-8")
    with pytest.raises(SignalsFileError):
        load_signals(path)


def test_loader_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "signals.yaml"
    row = {"signal_id": "signal_1", "base_url": "http://x", "token": "t"}
    path.write_text(yaml.safe_dump({"signals": [row, dict(row)]}), encoding="utf-8")
    with pytest.raises(SignalsFileError):
        load_signals(path)


def test_loader_keeps_observer_url_and_cycle_map(tmp_path):
    ep = SignalEndpoint("signal_1", "http://x", "t",
                        observer_url="http://127.0.0.1:8095/",
                        observer_map={"red": "left", "green": "right"})
    path = tmp_path / "signals.yaml"
    write_signals(path, [ep])
    assert load_signals(path) == [SignalEndpoint(
        "signal_1", "http://x", "t",
        observer_url="http://127.0.0.1:8095",          # 끝 슬래시는 정규화된다
        observer_map={"red": "left", "green": "right"})]


@pytest.mark.parametrize("row", [
    {"signal_id": "s1", "base_url": "http://x", "token": "t",
     "observer_url": "ftp://observer"},                      # 스킴 없는 관측 URL
    {"signal_id": "s1", "base_url": "http://x", "token": "t",
     "observer_map": {"blue": "left"}},                      # 장치 계약에 없는 램프
    {"signal_id": "s1", "base_url": "http://x", "token": "t",
     "observer_map": {"red": ""}},                           # ROI 이름 없음
])
def test_loader_rejects_bad_observer_config(tmp_path, row):
    """지도를 지어내지 않는다 — 틀린 램프 이름은 여기서 걸러 배포 시점에 드러난다."""
    path = tmp_path / "signals.yaml"
    path.write_text(yaml.safe_dump({"signals": [row]}), encoding="utf-8")
    with pytest.raises(SignalsFileError):
        load_signals(path)


# --- parser -------------------------------------------------------------------

def test_parser_accepts_the_documented_payload():
    status = parse_status("signal_1", {
        "signal_id": "signal_1", "firmware": "1.0.0", "mode": "failsafe", "seq": 17,
        "lamps": {"red": True, "yellow": False, "green": False},
        "secs_since_contact": 11, "faults": ["supervisor_lost"]})
    assert status.mode == "failsafe"
    assert status.lamps == {"red": True, "yellow": False, "green": False}
    assert status.faults == ("supervisor_lost",)
    assert status.seq == 17


@pytest.mark.parametrize("payload", [
    {"lamps": {"red": True, "yellow": False, "green": False}},                    # mode 누락
    {"mode": "manual"},                                                            # lamps 누락
    {"mode": "manual", "lamps": {"red": True, "yellow": False}},                   # green 누락
])
def test_missing_required_fields_are_errors_not_defaults(payload):
    with pytest.raises(SignalApiError):
        parse_status("signal_1", payload)


# --- 3자 교차 검증 (의도 vs 접점 vs 실측, 관측 설계 §3) ---------------------------

def test_cross_check_agree_when_all_three_match():
    status = {"red": True, "yellow": False, "green": False}
    state, faults = cross_check(
        dict(status), status, _observed(red=True),
        lamp_to_roi={"red": "left", "yellow": "mid", "green": "right"})
    assert (state, faults) == ("agree", [])


def test_cross_check_without_intent_skips_the_first_leg():
    """의도가 아직 없으면 1≠2 를 말할 수 없다 — '의도 없음' ≠ '전부 꺼짐'."""
    status = {"red": True, "yellow": False, "green": False}
    assert cross_check(None, status, _observed(red=True),
                       lamp_to_roi={"red": "left"}) == ("agree", [])


def test_cross_check_separates_intent_from_device_report():
    intent = {"red": True, "yellow": False, "green": False}
    status = {"red": False, "yellow": False, "green": True}   # 장치 보고가 다르다
    state, faults = cross_check(intent, status, None)
    assert state == "controller_mismatch"
    assert "cmd_vs_device:red" in faults and "cmd_vs_device:green" in faults


def test_cross_check_flags_a_lamp_the_device_claims_on_but_the_camera_reads_dark():
    status = {"red": True, "yellow": False, "green": False}
    state, faults = cross_check(None, status, _observed(red=False),
                                lamp_to_roi={"red": "left"})
    assert (state, faults) == ("display_mismatch", ["obs_dark:red"])


def test_cross_check_flags_a_ghost_the_camera_sees_but_the_device_denies():
    status = {"red": False, "yellow": False, "green": False}
    state, faults = cross_check(None, status, _observed(red=True),
                                lamp_to_roi={"red": "left"})
    assert (state, faults) == ("display_mismatch", ["obs_ghost:red"])


def test_cross_check_flags_the_wrong_color_not_just_lit():
    """켜졌는지만 아는 검증은 반쪽이다 — 적색 자리가 파란색이면 그것도 불일치."""
    status = {"red": True, "yellow": False, "green": False}
    observed = observed_body(lamps={
        "left": {"lit": True, "group": "blue", "confidence": 1.0}})
    state, faults = cross_check(None, status, observed, lamp_to_roi={"red": "left"})
    assert (state, faults) == ("display_mismatch", ["obs_color:red:blue"])


def test_cross_check_frozen_observation_is_stale_not_a_fault():
    """프레임이 멈춘 관측은 불일치를 말할 수 없다 — 모른다(stale)로 둔다."""
    status = {"red": True, "yellow": False, "green": False}
    state, faults = cross_check(None, status, _observed(red=True, frozen=True),
                                lamp_to_roi={"red": "left"})
    assert (state, faults) == ("stale", ["obs_stale"])


def test_cross_check_pending_observation_is_not_yet_evidence():
    status = {"red": True, "yellow": False, "green": False}
    state, faults = cross_check(None, status, _observed(red=False, pending=True),
                                lamp_to_roi={"red": "left"})
    assert (state, faults) == ("agree", [])       # debounce 확정 전 — 침묵이 증거다


def test_cross_check_without_a_cycle_map_says_unmapped():
    """지도가 없으면 지어내지 않는다 — unmapped 가 agree 가 아니다."""
    status = {"red": True, "yellow": False, "green": False}
    assert cross_check(None, status, _observed(red=True))[0] == "unmapped"


# --- console ------------------------------------------------------------------

def test_poll_marks_the_dead_one_without_losing_the_live_one():
    live, dead = FakeSignal("signal_1"), FakeSignal("signal_2")
    dead.status_error = ConnectionError("gone")
    console = _console(live, dead)
    asyncio.run(console.poll_once())
    snap = console.snapshot()
    assert snap["signal_1"]["online"] is True
    assert snap["signal_1"]["mode"] == "manual"
    assert snap["signal_2"]["online"] is False
    assert snap["signal_2"]["error"]["code"] == "ConnectionError"


def test_failsafe_reasserts_the_last_intent_exactly_once():
    sig = FakeSignal("signal_1")
    console = _console(sig)
    asyncio.run(console.command("signal_1", {
        "mode": "manual", "lamps": {"red": False, "yellow": False, "green": True}}))
    assert len(sig.commands) == 1
    sig.mode = "failsafe"          # 감독자 침묵을 흉내 낸다
    asyncio.run(console.poll_once())
    asyncio.run(console.poll_once())      # 재단언은 한 번이다 — 스톰이 아니라
    reasserts = [c for c in sig.commands if c["seq"] > 1]
    assert len(reasserts) == 1
    assert console.snapshot()["signal_1"]["mode"] == "manual"   # 돌아왔다


def test_reassert_budget_is_not_reset_when_the_device_stays_failsafe():
    sig = FakeSignal("signal_1")
    console = _console(sig)
    asyncio.run(console.command("signal_1", {"mode": "all_red"}))
    sig.mode = "failsafe"

    async def accepts_but_stays_failsafe(body):
        sig.last_seq = body["seq"]
        sig.commands.append(dict(body))
        return sig._status()

    sig.command = accepts_but_stays_failsafe
    before = len(sig.commands)
    asyncio.run(console.poll_once())
    asyncio.run(console.poll_once())
    assert len(sig.commands) == before + 1


def test_a_fresh_command_resets_the_reassert_budget():
    sig = FakeSignal("signal_1")
    console = _console(sig)
    asyncio.run(console.command("signal_1", {"mode": "all_red"}))
    sig.mode = "failsafe"
    asyncio.run(console.poll_once())                     # 재단언 소진
    asyncio.run(console.command("signal_1", {"mode": "all_red"}))   # 운영자 손 — 예산 리셋
    before = len(sig.commands)
    sig.mode = "failsafe"
    asyncio.run(console.poll_once())
    assert len(sig.commands) == before + 1


def test_stale_seq_is_reported_not_retried():
    sig = FakeSignal("signal_1")
    sig.last_seq = 99                             # 장치가 더 앞서 있다 — 다른 클라이언트의 흔적
    console = _console(sig)
    row = asyncio.run(console.command("signal_1", {"mode": "all_red"}))
    assert row["mismatch"] == "stale_seq"
    assert len(sig.commands) == 0                 # 아무것도 안 들어갔다


def test_all_red_scatter_reports_partial_failure():
    good, dead = FakeSignal("signal_1"), FakeSignal("signal_2")

    async def blow_up(body):
        raise ConnectionError("gone")

    dead.command = blow_up
    console = _console(good, dead)
    result = asyncio.run(console.all_red())
    assert result["total"] == 2
    assert result["all_red"] == 1
    assert result["signals"][1]["all_red"] is False


def test_all_red_does_not_report_stale_seq_as_applied():
    sig = FakeSignal("signal_1")
    sig.last_seq = 99
    result = asyncio.run(_console(sig).all_red())
    assert result["all_red"] == 0
    assert result["signals"][0]["all_red"] is False
    assert result["signals"][0]["error"]["code"] == "stale_seq"


def test_unknown_signal_is_a_site_error_not_a_crash():
    console = _console(FakeSignal("signal_1"))
    with pytest.raises(HubError):
        asyncio.run(console.command("signal_99", {"mode": "all_red"}))


def test_refresh_is_throttled_by_the_injected_clock():
    sig = FakeSignal("signal_1")
    now = [0.0]
    console = _console(sig, clock=lambda: now[0])
    asyncio.run(console.refresh())
    asyncio.run(console.refresh())                # 같은 순간 — 두 번 폴링하지 않는다
    assert sig.commands == []
    assert console.snapshot()["signal_1"]["online"] is True
    now[0] = 5.0                                  # 주기가 지났다 — 이제 폴링한다
    asyncio.run(console.refresh())
    assert console.snapshot()["signal_1"]["online"] is True


def test_reassert_does_not_fire_when_the_console_never_commanded():
    """부팅 직후의 failsafe 는 재단언할 의도가 없다 — 아무것도 보내지 않는다."""
    sig = FakeSignal("signal_1")
    sig.mode = "failsafe"
    console = _console(sig)
    asyncio.run(console.poll_once())
    assert sig.commands == []


def test_row_says_verify_absent_when_no_observer_is_configured():
    """관측이 없으면 모른다 — 꺼져 있는 검증을 '합격'으로 그리지 않는다."""
    console = _console(FakeSignal("signal_1"))
    asyncio.run(console.poll_once())
    assert console.snapshot()["signal_1"]["verify"] == {"state": "absent", "faults": []}


def test_poll_pulls_the_observer_and_the_row_reads_agree():
    sig = FakeSignal("signal_1")
    obs = FakeObserver(_observed(red=True))
    console = SignalConsole(
        [SIG_OBS], [sig], clock=lambda: 0.0, observers={"signal_1": obs})
    asyncio.run(console.poll_once())
    assert obs.calls == 1                       # 폴링이 관측을 한 번 당겼다
    verify = console.snapshot()["signal_1"]["verify"]
    assert verify["state"] == "agree"
    assert verify["faults"] == []
    assert verify["observer"]["frozen"] is False


def test_observer_outage_is_unreachable_not_a_fault():
    """카메라가 죽어도 장치 상태는 산다 — 검증만 '모른다'가 된다."""
    sig = FakeSignal("signal_1")
    obs = FakeObserver(error=ConnectionError("camera gone"))
    console = SignalConsole(
        [SIG_OBS], [sig], clock=lambda: 0.0, observers={"signal_1": obs})
    asyncio.run(console.poll_once())
    verify = console.snapshot()["signal_1"]["verify"]
    assert verify["state"] == "unreachable"
    assert verify["error"] == {"code": "ConnectionError",
                               "message": "camera gone", "reachable": False}
    assert console.snapshot()["signal_1"]["online"] is True


def test_device_claims_red_but_the_camera_reads_dark_is_a_display_mismatch():
    sig = FakeSignal("signal_1")                   # 장치 보고: red 켜짐
    obs = FakeObserver(_observed(red=False))       # 실측: 어두움
    console = SignalConsole(
        [SIG_OBS], [sig], clock=lambda: 0.0, observers={"signal_1": obs})
    asyncio.run(console.poll_once())
    verify = console.snapshot()["signal_1"]["verify"]
    assert verify["state"] == "display_mismatch"
    assert verify["faults"] == ["obs_dark:red"]


def test_status_poll_recomputes_the_intent_mismatch():
    """의도≠보고는 폴링마다 다시 본다 — 장치가 명령을 안 따라와도 화면에서 숨지 않는다."""
    sig = FakeSignal("signal_1")
    console = _console(sig)
    asyncio.run(console.command("signal_1", {
        "mode": "manual", "lamps": {"red": False, "yellow": False, "green": True}}))
    sig.lamps = {"red": True, "yellow": False, "green": False}   # 장치가 안 따라왔다
    asyncio.run(console.poll_once())
    assert console.snapshot()["signal_1"]["mismatch"] == "controller_mismatch"


def test_a_poll_does_not_erase_the_stale_seq_ledger():
    """stale_seq 는 다른 클라이언트의 흔적 — 상태 폴링이 그것을 지우면 안 된다."""
    sig = FakeSignal("signal_1")
    sig.last_seq = 99
    console = _console(sig)
    row = asyncio.run(console.command("signal_1", {"mode": "all_red"}))
    assert row["mismatch"] == "stale_seq"
    asyncio.run(console.poll_once())
    assert console.snapshot()["signal_1"]["mismatch"] == "stale_seq"


# --- HTTP 표면 ----------------------------------------------------------------

def test_state_includes_signals_when_a_signal_console_is_attached():
    signals = _console(FakeSignal("signal_1"))
    asyncio.run(signals.poll_once())
    body = _client(signals=signals).get("/api/fleet/state").json()
    assert body["signals"]["signal_1"]["online"] is True


def test_signals_endpoint_returns_detail_and_404_without_a_console():
    assert _client().get("/api/fleet/signals").status_code == 404
    signals = _console(FakeSignal("signal_1"))
    asyncio.run(signals.poll_once())
    body = _client(signals=signals).get("/api/fleet/signals").json()
    assert body["signals"]["signal_1"]["mode"] == "manual"


def test_verify_is_visible_on_the_signals_endpoint():
    """교차 검증 상태도 HTTP 로 나간다 — 화면이 그것을 그릴 수 있어야 검증이다."""
    signals = _console(FakeSignal("signal_1"))
    asyncio.run(signals.poll_once())
    body = _client(signals=signals).get("/api/fleet/signals").json()
    assert body["signals"]["signal_1"]["verify"]["state"] == "absent"


def test_signal_command_endpoint_posts_and_answers_the_row():
    sig = FakeSignal("signal_1")
    signals = _console(sig)
    resp = _client(signals=signals).post(
        "/api/fleet/signals/signal_1/command",
        json={"mode": "manual", "lamps": {"red": False, "yellow": False, "green": True}})
    assert resp.status_code == 200
    assert resp.json()["lamps"]["green"] is True
    assert sig.commands[0]["seq"] == 1


def test_unknown_signal_is_404_not_502():
    signals = _console(FakeSignal("signal_1"))
    resp = _client(signals=signals).post("/api/fleet/signals/signal_99/command",
                                         json={"mode": "all_red"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "UNKNOWN_SIGNAL"


def test_a_refusing_signal_comes_back_as_502_with_the_device_code():
    sig = FakeSignal("signal_1")

    async def refuse(body):
        raise SignalApiError("signal_1", 400, "conflict", "red and green together")

    sig.command = refuse
    signals = _console(sig)
    resp = _client(signals=signals).post(
        "/api/fleet/signals/signal_1/command",
        json={"mode": "manual", "lamps": {"red": True, "yellow": False, "green": True}})
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "conflict"


def test_estop_drives_the_signals_all_red_and_is_200_when_they_die():
    good, dead = FakeSignal("signal_1"), FakeSignal("signal_2")

    async def blow_up(body):
        raise ConnectionError("gone")

    dead.command = blow_up
    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "mode": "IDLE"})
    resp = _client(signals=_console(good, dead), robots=[robot]).post("/api/fleet/estop")
    assert resp.status_code == 200
    body = resp.json()
    assert body["signals"]["all_red"] == 1        # 한 기는 죽어도 한 기는 섰다
    assert body["signals"]["signals"][1]["all_red"] is False


@pytest.mark.parametrize("path,body", [
    ("/api/fleet/signals", None),
    ("/api/fleet/signals/signal_1/command", {"mode": "all_red"}),
])
def test_console_token_guards_the_signal_api(path, body):
    signals = _console(FakeSignal("signal_1"))
    client = _client(signals=signals, token="secret")
    kwargs = {"headers": {"Authorization": "Bearer wrong"}}
    if body is not None:
        kwargs["json"] = body
    method = client.get if body is None else client.post
    resp = method(path, **kwargs)
    assert resp.status_code == 401
