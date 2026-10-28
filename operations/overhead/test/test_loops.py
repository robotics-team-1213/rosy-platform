"""루프 사망 감시(loops.py)와 /readyz — /healthz는 프로세스 생존 그대로.

Fleet 루프 감시의 vision 쌍둥이(자체 포함, fleet import 없음): 예외로 끝난 루프만
사망으로 보고, 카메라 연결이 닫히며 정상 복귀하는 상태 루프·stop 이벤트로 끝나는
config 동기화는 잊는다. 변이: 사망 표시를 지우면 readyz 시험이 red.
"""

from __future__ import annotations

import asyncio
import functools
import logging

import pytest

import httpx

from rosy_vision import protocol
from rosy_vision.ingest import IngestServer
from rosy_vision.loops import DEAD, LoopWatch

TOKEN = "test-token"


def run_async(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        asyncio.run(fn(*args, **kwargs))

    return wrapper


async def _raise_after():
    await asyncio.sleep(0)
    raise RuntimeError("expected loop death")


async def _return_soon():
    await asyncio.sleep(0)


class _Harness:
    """IngestServer + ws 소켓 한 벌 (test_ingest._Harness 패턴)."""

    def __init__(self):
        self.server = IngestServer({"overhead-1": TOKEN})
        self.ws_server = None
        self.url = None

    async def __aenter__(self) -> "_Harness":
        self.ws_server = await self.server.start("127.0.0.1", 0)
        port = self.ws_server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}{protocol.WS_PATH}"
        return self

    async def __aexit__(self, *exc):
        self.ws_server.close()
        await self.ws_server.wait_closed()


def test_a_failing_loop_is_marked_dead_while_clean_and_cancelled_ends_are_forgotten(caplog):
    async def exercise():
        watch = LoopWatch()
        with caplog.at_level(logging.ERROR, logger="rosy_vision.loops"):
            boom = watch.supervised("boom", _raise_after())
            clean = watch.supervised("clean", _return_soon())
            cancelled = watch.supervised("cancelled", asyncio.Event().wait())
            cancelled.cancel()
            await asyncio.gather(boom, clean, cancelled, return_exceptions=True)
        return watch

    watch = asyncio.run(exercise())
    assert watch.status() == {"boom": DEAD}
    assert watch.dead() == ["boom"]
    assert any("'boom' ended" in record.getMessage() for record in caplog.records)


def test_a_replaced_loops_late_callback_never_erases_the_new_deaths():
    """재연결이 이름을 재사용한다 — 옛 태스크의 늦은 콜백이 새 사망을 지우면 안 된다."""

    async def exercise():
        watch = LoopWatch()
        replaced = watch.supervised("status:overhead-1", asyncio.Event().wait())
        successor = watch.supervised("status:overhead-1", _raise_after())
        for _ in range(100):  # settle: 태스크 완료 뒤에도 콜백은 다음 루프 바퀴에 돈다
            if "status:overhead-1" in watch.dead():
                break
            await asyncio.sleep(0)
        assert watch.dead() == ["status:overhead-1"]
        replaced.cancel()  # 옛 연결 정리 콜백이 늦게 도착한다
        with pytest.raises(asyncio.CancelledError):
            await replaced
        await asyncio.sleep(0)  # 취소 콜백이 한 바퀴 돌게
        return watch

    watch = asyncio.run(exercise())
    assert watch.dead() == ["status:overhead-1"]  # 사망 기록이 살아 있다


@run_async
async def test_readyz_flips_to_503_only_when_a_watched_loop_died():
    async with _Harness() as h:
        base = h.url.rsplit(protocol.WS_PATH, 1)[0].replace("ws://", "http://")
        async with httpx.AsyncClient() as client:
            healthy = await client.get(f"{base}/readyz")
            assert healthy.status_code == 200
            assert healthy.json() == {"status": "ok"}

            h.server.loop_watch.supervised("status:overhead-1", _raise_after())
            await asyncio.sleep(0.05)  # 사망 콜백이 표를 채우게
            degraded = await client.get(f"{base}/readyz")
            assert degraded.status_code == 503
            assert degraded.json() == {"status": "not_ready", "dead": ["status:overhead-1"]}

            healthz = await client.get(f"{base}/healthz")
            assert healthz.status_code == 200
            assert healthz.json() == {"status": "ok"}
