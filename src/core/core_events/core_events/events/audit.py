"""LOG-001 file audit log. Same EventMessage schema as the in-memory bus.

기록은 이벤트 버스의 구독자로 붙어 있고(`core/services.py`), 버스는 구독자를 **동기로**
부른다. 그래서 `record()` 가 무거우면 그 비용은 이벤트를 낸 스레드가 문다 — 그중
하나가 50 Hz cmd_vel 타이머다.

예전에는 이벤트 하나마다 파일 전체를 읽어 모든 줄을 파싱하고 다시 직렬화해
덮어썼다. 보존 기간이 30 일이라 파일은 계속 자라고, 비용은 줄 수에 비례한다:
800 줄에서 `record()` 한 번이 16 ms — 50 Hz 주기의 0.8 개 — 이고 파일을 채우는
전체 비용은 O(n²) 이다. 30 일치면 그보다 한참 크다.

보존은 "읽었을 때 30 일 넘은 것이 없다"는 약속이지 "매 쓰기마다 즉시 정리한다"는
약속이 아니다. 그래서:

* `record()` 는 **덧붙이기만** 한다. 정리 시각이 되었으면 정리를 전용 작업
  스레드에 넘기고 곧바로 돌아온다 — 10 만 줄(19 MB)이면 정리 한 번이 수백 ms
  이고, 그것을 이벤트를 낸 스레드가 물면 한 시간에 한 번 50 Hz 주기가 수십 개
  빠진다(2026-09-22 측정: 첫 기록 656 ms, 매시 788 ms).
* 정리는 락을 **두 번, 짧게** 잡는다. 크기·신원을 뜰 때와, 그 뒤에 덧붙은 꼬리를
  이어 붙여 바꿔 끼울 때. 읽기·디코드·파싱·임시 파일 쓰기는 모두 락 밖이다.
* `history()` 는 여는 순간만 락을 잡고, 파일 **끝에서부터** 읽어 필요한 만큼만
  파싱한다.
* 작업 스레드는 파싱하는 동안 주기적으로 잠깐 잠든다. 같은 프로세스의 CPU 일은
  GIL 을 통해 이벤트를 낸 스레드를 세우기 때문이다(`_YIELD_EVERY`).

이 구현이 **하지 않는** 것 두 가지 (알고 두는 것이지 잊은 것이 아니다):

* **덧붙이기는** `fsync` 하지 않는다. 정전이면 OS 버퍼에 있던 마지막 몇 줄이
  사라질 수 있다. 매 이벤트마다 `fsync` 하면 SD 카드에서 한 번에 수 ms 가 들고
  그 비용을 50 Hz 타이머가 문다 — 이 파일이 애초에 고치려던 문제로 되돌아간다.
  딥 방전 종료(D-27)는 정상 종료 경로라 버퍼가 비워지고, 갑작스러운 정전에서
  마지막 몇 줄을 잃는 것은 LOG-001 이 요구하는 30 일 보존과 다른 이야기다.
  **정리의 바꿔 끼우기는** 새 파일을 `fsync` 한 뒤에 한다 — 그것은 30 일치 전체를
  새 파일로 옮기는 일이라, 그 직후의 정전이 빈 파일을 남기면 잃는 것이 마지막
  몇 줄이 아니다. 그 비용은 작업 스레드가 락 밖에서 문다. 정리 도중에 덧붙은
  꼬리 몇 줄은 덧붙이기와 같은 규칙으로 fsync 하지 않는다.
* 여러 **프로세스** 가 같은 파일을 쓰는 것을 막지 않는다. `threading.Lock` 은
  프로세스 안에서만 유효하고, 정리의 읽기-쓰기 사이에 다른 프로세스가 덧붙인
  줄은 `os.replace` 에 지워진다. D-1 에 따라 이 파일을 쓰는 것은 `core`
  한 프로세스뿐이므로 지금은 성립한다 — 두 번째 쓰는 쪽이 생기면 파일 락이
  필요하고, 그것은 이 주석이 아니라 ADR 로 정해야 한다.

스키마로 읽을 수 없는 줄은 **지우지 않는다** (`_compact` 참고). JSON 으로 읽히고
`ts` 가 있으면 그 `ts` 로 보존 규칙을 따르고, JSON 조차 아니면 바이트 그대로
`<파일>.quarantine` 으로 옮긴다.
"""

from __future__ import annotations

import io
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, Optional

from core_common.protocol.schemas import EventMessage

DEFAULT_RETENTION_DAYS = 30

#: 쓰기 경로에서 정리를 다시 시도하기까지의 최소 간격.
#:
#: 30 일 보존에 한 시간의 여유를 두는 것이므로 정책은 그대로다. 대신 쓰기 한 번의
#: 비용이 줄 수와 무관해진다.
PRUNE_INTERVAL_S = 3600.0

#: `history()` 가 끝에서부터 한 번에 읽는 크기. 한 줄은 수백 바이트이므로
#: `limit=1` 조회는 한 조각으로 끝난다.
_READ_CHUNK = 64 * 1024

#: 정리가 앞에서부터 한 번에 읽는 크기. 19 MB 를 통째로 `split`·`join` 하면
#: 그 C 호출 하나가 GIL 을 20 ms 넘게 쥔다 — 작업 스레드로 옮겨도 그동안
#: `record()` 는 GIL 을 기다린다. 256 KB 조각이면 한 번에 1 ms 미만이다.
_COMPACT_BLOCK = 256 * 1024

#: 파싱 루프가 GIL 을 내어 주는 간격(줄)과 그때 쉬는 시간.
#:
#: 파싱은 순수 CPU 일이다. `record()` 는 open·write·close 마다 GIL 을 놓았다
#: 다시 잡아야 하는데, 작업 스레드가 쉬지 않으면 그때마다 전환 간격(5 ms)을
#: 기다린다 — 한 번의 기록이 수십 ms 가 된다(2026-09-22 측정, `sleep(0)` 만
#: 두었을 때 최대 37 ms). `sleep(0)` 은 GIL 을 놓자마자 같은 스레드가 다시
#: 잡는 일이 흔해서 넘겨준다는 보장이 없다. 짧게라도 **실제로 잠들어야**
#: 기다리던 스레드가 잡는다. 128 줄은 약 1 ms 의 파싱이므로 정리는 두 배쯤
#: 느려지고(10 만 줄에 약 1.5 초, 한 시간에 한 번, 작업 스레드에서), 대신
#: 이벤트를 낸 스레드의 대기는 1 ms 안팎으로 묶인다.
_YIELD_EVERY = 128
_YIELD_S = 0.001


def _yield_gil() -> None:
    """GIL 을 기다리는 스레드(= `record()` 를 부른 스레드)에 차례를 준다."""
    time.sleep(_YIELD_S)


def _lines_forward(handle: BinaryIO, size: int) -> Iterator[bytes]:
    """`[0, size)` 를 조각으로 읽어 줄을 **바이트 그대로** 돌려준다.

    개행 하나로만 나눈다(JSON Lines). `bytes.splitlines()` 를 쓰지 않는다 —
    그것은 홀로 있는 캐리지리턴에서도 자른다. 그러면 한 줄이었던 기록이 두
    줄로 보여 둘 다 깨진 JSON 이 되고, 조회에서 사라진 뒤 다음 정리에
    격리된다.

    (`str.splitlines()` 는 여기에 세로탭·폼피드·파일/그룹/레코드 구분자와
    U+2028·U+2029·U+0085 까지 더한다. 그래서 조회도 str 이 아니라 개행
    바이트로 나눈다(`_lines_backward`). 그 목록을 짧게 적어 두었더니
    세로탭·폼피드가 빠졌고, 하필 그 둘이 자르는 순서를 검사할 수 있는 유일한
    바이트였다.)

    마지막 개행 뒤는 줄이 아니다. 조각마다 GIL 을 내어 준다.
    """
    handle.seek(0)
    remaining = size
    carry = b""
    while remaining > 0:
        block = handle.read(min(_COMPACT_BLOCK, remaining))
        if not block:
            break
        remaining -= len(block)
        parts = (carry + block).split(b"\n")
        carry = parts.pop()
        yield from parts
        _yield_gil()
    if carry:
        yield carry


def _lines_backward(handle: BinaryIO, size: int) -> Iterator[bytes]:
    """`[0, size)` 를 **끝에서부터** 개행으로 나눠 돌려준다.

    `_lines_forward` 와 같은 규칙이다(개행 하나로만 나눈다). 다른 점은 마지막
    개행 뒤의 빈 조각과 파일 머리의 빈 조각을 돌려줄 수 있다는 것뿐이고,
    빈 줄은 어느 쪽에서도 기록이 아니다.
    """
    pos = size
    carry = b""
    while pos > 0:
        step = min(_READ_CHUNK, pos)
        pos -= step
        handle.seek(pos)
        block = handle.read(step) + carry
        parts = block.split(b"\n")
        carry = parts[0]
        for part in reversed(parts[1:]):
            yield part
    yield carry


def _fsync_directory(directory: Path) -> None:
    """`os.replace` 가 디렉터리 항목까지 디스크에 닿게 한다 (POSIX 만).

    Windows 에는 디렉터리를 열어 fsync 하는 방법이 없고, NTFS 는 이름 바꾸기를
    메타데이터 저널로 다룬다.
    """
    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class FileAuditLog:
    def __init__(
        self,
        path: Path,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        now: Optional[Callable[[], datetime]] = None,
        monotonic: Optional[Callable[[], float]] = None,
        prune_interval_s: float = PRUNE_INTERVAL_S,
    ) -> None:
        self._path = Path(path)
        self._retention_days = retention_days
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._prune_interval_s = prune_interval_s
        #: None = 아직 한 번도 정리하지 않았다. 첫 기록은 정리를 요청한다 — 지난
        #: 실행이 남긴 오래된 줄이 그대로 있을 수 있다.
        self._last_prune: Optional[float] = None
        #: 기록이 실패한 횟수와 마지막 사유. 버스는 구독자 예외를 삼키므로,
        #: 여기에 남기지 않으면 디스크가 찬 로봇은 감사 기록을 남기지 않으면서
        #: 아무 말도 하지 않는다 — LOG-001 이 조용히 꺼진 상태다.
        #:
        #: 둘로 나눠 센다. `_write_failures` 는 **연속** 실패라 지금 쓸 수 있는지를
        #: 말하고(gauge), `_write_failures_total` 은 누적이라 되돌아가지 않는다
        #: (counter). 성공 한 번이 카운터를 0 으로 되돌리면 Prometheus 는 그것을
        #: "카운터 리셋"으로 읽어 그 사이의 실패를 통째로 못 본 것으로 만든다.
        self._write_failures = 0
        self._write_failures_total = 0
        #: 정리 실패는 쓰기 실패가 아니다. 덧붙이기가 성공했으면 그 이벤트는
        #: 기록됐고, 파일이 30 일보다 길게 남아 있는 것은 다음 시각에 다시
        #: 시도할 일이지 감사 로그가 꺼졌다는 뜻이 아니다.
        self._prune_failures = 0
        #: 직렬화 실패도 따로 센다. 이벤트 `data` 에 JSON 이 될 수 없는 값이
        #: 실리면 `model_dump_json()` 이 던지고, 그것은 디스크 문제가 아니라
        #: 발행한 쪽의 결함이다. 그 이벤트는 `repr` 로 바꿔 **그래도 남긴다**.
        self._serialize_failures = 0
        #: 마지막 사유는 지우지 않는다. 성공 한 번에 지워 버리면 간헐적으로
        #: 실패하는 디스크는 운영자가 볼 때마다 늘 깨끗해 보인다.
        #:
        #: 채널마다 따로 남긴다. 하나로 두면 정리 실패 한 번이 디스크가 찼다는
        #: 사유를 덮어써, 운영자는 0 이 아닌 `write_failures_total` 과 전혀 다른
        #: 이야기를 하는 `last_error` 를 함께 보게 된다.
        self._last_write_error: Optional[str] = None
        self._last_prune_error: Optional[str] = None
        self._last_serialize_error: Optional[str] = None
        #: 이어 붙일 수 없어 정리를 거른 횟수. 실패가 아니라 "전제가 깨졌다"이고,
        #: 계속 오르면 이 파일을 우리 말고 누가 건드리고 있다는 뜻이다.
        self._prune_skipped = 0
        #: 거른 이유는 실패 사유 칸에 적지 않는다. 그러면 prune_failures 를
        #: 보고 온 운영자가 다른 채널의 이야기를 읽게 된다.
        self._last_skip_reason: Optional[str] = None
        #: 정리 작업 스레드. `None` 이면 요청도 진행 중인 정리도 없다 — 스레드는
        #: 할 일이 없으면 이 칸을 **락 안에서** 비우고 끝난다. 그래서 정리는
        #: 구조적으로 한 번에 하나이고(스레드가 하나뿐이다), 한 시간 내내 잠든
        #: 스레드를 들고 있지도 않는다.
        self._worker: Optional[threading.Thread] = None
        self._compaction_requested = False
        #: 지난 실행이 남긴 마지막 줄이 개행으로 끝나는가. 정전이 UTF-8 한 글자
        #: 가운데를 잘랐다면 그 개행은 애초에 쓰이지 못했다 — 그 뒤에 그냥
        #: 덧붙이면 새 이벤트가 그 망가진 줄의 일부가 되어 함께 버려진다.
        #: 한 프로세스가 시작할 때 한 번만 확인한다(D-1). 이후의 덧붙이기는
        #: 우리가 쓴 것이므로 반드시 개행으로 끝난다.
        self._tail_is_terminated: Optional[bool] = None
        self._lock = threading.Lock()
        #: 같은 락 위의 조건 변수. `settle()` 이 정리가 끝나기를 기다린다.
        self._idle = threading.Condition(self._lock)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def quarantine_path(self) -> Path:
        """스키마로도 JSON 으로도 읽을 수 없는 줄이 옮겨지는 곳."""
        return self._path.with_name(self._path.name + ".quarantine")

    def health(self) -> dict:
        """기록이 실제로 남고 있는가. 운영자가 감사 로그를 물을 때 함께 답한다."""
        with self._lock:
            return {
                "writable": self._write_failures == 0,
                "write_failures": self._write_failures,
                "write_failures_total": self._write_failures_total,
                "prune_failures": self._prune_failures,
                "prune_skipped": self._prune_skipped,
                "serialize_failures": self._serialize_failures,
                "last_skip_reason": self._last_skip_reason,
                "last_write_error": self._last_write_error,
                "last_prune_error": self._last_prune_error,
                "last_serialize_error": self._last_serialize_error,
            }

    def settle(self, timeout: Optional[float] = 10.0) -> bool:
        """요청된 정리가 끝날 때까지 기다린다. 끝났으면 `True`.

        `record()` 는 정리를 기다리지 않는다 — 그것이 이 설계의 요점이다. 이
        메서드는 종료 경로와 시험이 "정리가 반영된 파일"을 보고 싶을 때 쓴다.
        """
        with self._idle:
            return self._idle.wait_for(lambda: self._worker is None, timeout)

    def record(self, event: EventMessage) -> None:
        """덧붙이고 돌아온다. **예외를 밖으로 던지지 않는다.**

        EventBus 는 구독자 예외를 삼키므로 던져 봐야 아무도 받지 않는다. 대신
        세어 두고 `health()` 로 답한다.
        """
        # 직렬화는 락 밖에서 한다. 락 안에서 비용을 들일 이유가 없고, 실패해도
        # 락 상태를 신경 쓸 일이 없다.
        payload, serialize_error = self._serialize(event)
        with self._lock:
            if serialize_error is not None:
                self._serialize_failures += 1
                self._last_serialize_error = serialize_error
            if payload is None:
                # `repr` 로도 만들 수 없었다. 이 이벤트는 남지 못했다 — 쓰기
                # 채널이 그것을 말해야 한다.
                self._note_write_failure(serialize_error or "unserialisable event")
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                # newline='' 이 없으면 Windows 는 CRLF 로 쓴다. 이 파일은 다른
                # 모든 자리에서 LF 로 나뉜 JSON Lines 로 다뤄지고, 정리는
                # 캐리지리턴을 떼고 LF 로 다시 이어 붙인다 — 그러면 깨진 줄뿐
                # 아니라 **모든** 줄이 쓴 것과 다르게 저장된다.
                with self._path.open("a", encoding="utf-8", newline="") as handle:
                    if not self._terminated_locked():
                        # 지난 실행의 잘린 마지막 줄에 그냥 이어 쓰면, 이
                        # 이벤트가 그 줄의 일부가 되어 다음 정리에 함께
                        # 격리된다. 정전 직후 처음 기록되는 것이 하필
                        # `safety.estop` 일 수 있다.
                        handle.write("\n")
                    handle.write(payload + "\n")
                # 닫힌 **뒤에** 세운다. with 를 나가며 flush 하고 실제 쓰기 오류는
                # 거의 다 거기서 난다 — 한 줄은 버퍼보다 훨씬 작다. 안에서 세우면
                # 실패한 쓰기가 "개행으로 끝났다"를 남기고, 그 캐시가 바로 위의
                # 꼬리 확인이 막으려던 구멍을 다시 연다.
                self._tail_is_terminated = True
            except OSError as error:
                self._note_write_failure(f"{type(error).__name__}: {error}")
                # 실패한 쓰기는 꼬리에 대해 아무것도 말해 주지 않는다. 부분
                # 기록일 수도, 아무것도 안 나갔을 수도 있다. 다음 기록이 다시
                # 확인하게 둔다.
                #
                # 실패가 이어지는 동안은 **기록마다** 다시 확인한다. ENOSPC 는
                # open 을 통과하고 close 에서 나므로 캐시가 매번 여기로 온다.
                # 한 줄 크기의 메타데이터 읽기이고, 그 사이 감사 기록은 이미
                # 멈춰 있다 — 성공하는 경로에는 아무 비용도 없다.
                self._tail_is_terminated = None
                return
            self._write_failures = 0

            if self._prune_due_locked() and self._worker is None:
                # 시각을 먼저 태운다. 정리가 실패해도 매 기록마다 다시 요청하지
                # 않고 한 시간 뒤에 한 번 더 해 본다.
                self._last_prune = self._monotonic()
                self._compaction_requested = True
                # 스레드를 여는 것까지가 이 호출자의 몫이다. 스냅샷·파싱·쓰기는
                # 하나도 여기서 하지 않는다.
                self._worker = threading.Thread(
                    target=self._compaction_worker, name="audit-compactor", daemon=True)
                self._worker.start()

    @staticmethod
    def _serialize(event: EventMessage) -> tuple[Optional[str], Optional[str]]:
        """(줄, 직렬화 실패 사유). 줄이 `None` 이면 남길 수 없다.

        `model_dump_json()` 은 `data` 에 JSON 이 될 수 없는 값이 있으면
        `PydanticSerializationError`(= `ValueError`) 를 던진다. 그 값만 `repr`
        로 바꿔 다시 만든다 — 감사 로그에서 기록 하나를 통째로 잃는 것보다
        값 하나가 문자열로 남는 편이 낫다.
        """
        try:
            return event.model_dump_json(), None
        except (ValueError, TypeError) as error:
            reason = f"{type(error).__name__}: {error}"
        try:
            return event.model_dump_json(fallback=repr), reason
        except (ValueError, TypeError):
            # pydantic 2.11 미만에는 `fallback` 이 없다(TypeError).
            return None, reason

    def _note_write_failure(self, reason: str) -> None:
        """호출자가 락을 쥐고 있어야 한다."""
        self._write_failures += 1
        self._write_failures_total += 1
        self._last_write_error = reason

    def _note_prune_failure(self, error: BaseException) -> None:
        """호출자가 락을 쥐고 있어야 한다 — `health()` 가 같은 락으로 읽는다."""
        self._prune_failures += 1
        self._last_prune_error = f"{type(error).__name__}: {error}"

    def _terminated_locked(self) -> bool:
        """마지막 줄이 개행으로 끝나는가. 프로세스당 한 번만 실제로 확인한다."""
        if self._tail_is_terminated is None:
            try:
                size = self._path.stat().st_size
                if size == 0:
                    self._tail_is_terminated = True
                else:
                    with self._path.open("rb") as handle:
                        handle.seek(-1, os.SEEK_END)
                        self._tail_is_terminated = handle.read(1) == b"\n"
            except OSError:
                # 마지막 바이트를 **읽지 못했다** — 열린 핸들, ACL, 공유 위반.
                # 두 답의 비용이 다르다: 틀린 True 는 다음 이벤트를 망가진 줄에
                # 삼키게 하고(되돌릴 수 없다), 틀린 False 는 빈 줄 하나를 남기며
                # 그것은 다음 정리가 지운다. 싼 쪽으로 틀린다.
                #
                # 파일이 없는 경우는 여기 오지 않는다 — 이 함수는 `open("a")`
                # 안에서 불리고, 그것이 이미 파일을 만들어 두었다.
                self._tail_is_terminated = False
        return self._tail_is_terminated

    def _prune_due_locked(self) -> bool:
        if self._last_prune is None:
            return True
        return self._monotonic() - self._last_prune >= self._prune_interval_s

    def _compaction_worker(self) -> None:
        """요청이 남아 있는 동안 정리하고, 없으면 칸을 비우고 끝난다."""
        while True:
            with self._idle:
                if not self._compaction_requested:
                    self._worker = None
                    self._idle.notify_all()
                    return
                self._compaction_requested = False
            try:
                self._compact()
            except Exception as error:  # noqa: BLE001 — 받을 호출자가 없다
                # 이 스레드 밖으로 나가는 예외는 아무도 보지 못한다. 무엇이든
                # 세어 둔다 — 디코드 실패(`ValueError`)든 I/O 든.
                with self._lock:
                    self._note_prune_failure(error)

    def history(
        self,
        *,
        since_seq: Optional[int] = None,
        limit: int = 500,
    ) -> list[EventMessage]:
        """보존 기간 안의 기록, 오래된 것부터. **파일은 건드리지 않는다.**

        예전에는 읽을 때마다 정리를 돌렸다. 조회 한 번이 파일 전체를 다시
        쓰는 것이고, 대시보드가 5 초마다 폴링하면 5 초마다 감사 로그가 통째로
        재작성된다 — 버릴 줄이 하나도 없어도 그렇다.

        **읽기와 파싱에는 락을 잡지 않는다** (여는 순간만 잡는다). 이 파일에
        일어나는 일은 덧붙이기와 `os.replace` 뿐이다. 열린 핸들은 바꿔 끼우기
        뒤에도 옛 파일을 가리키고, 연 순간의 크기까지만 읽으므로 덧붙는 도중의
        줄은 보지 않는다. 락을 쥔 채 19 MB 를 읽으면 그동안 `record()` 가, 즉
        50 Hz 타이머가 멈춘다.

        **끝에서부터 필요한 만큼만** 파싱한다. 대시보드는 페이지를 열 때
        `limit=1` 로 묻는데, 30 일치를 전부 파싱해 하나를 돌려주면 10 만 줄에서
        1.4 초다.
        """
        if limit < 1:
            return []
        cutoff = self._now() - timedelta(days=self._retention_days)
        # 여는 것만 락 안에서 한다. 정리의 `os.replace` 도 락 안이므로 둘이
        # 겹치지 않는다 — Windows 에서 바꿔 끼우는 도중의 파일을 열면
        # `PermissionError` 이고, 그것은 `/logs/audit` 의 500 이다. 열기와 크기
        # 재기는 수 µs 이고, 읽기·파싱은 락 밖이다.
        with self._lock:
            try:
                handle = self._path.open("rb")
            except FileNotFoundError:
                return []
            size = os.fstat(handle.fileno()).st_size
        found: list[EventMessage] = []
        with handle:
            for index, raw_line in enumerate(_lines_backward(handle, size), 1):
                if index % _YIELD_EVERY == 0:
                    # `since_seq` 조회는 끝까지 읽을 수 있다. 그동안 GIL 을
                    # 쥐고 있으면 50 Hz 타이머가 기다린다.
                    _yield_gil()
                event = self._event_from(raw_line)
                if event is None or not self._is_fresh(event.ts, cutoff):
                    continue
                if since_seq is not None and event.seq <= since_seq:
                    continue
                found.append(event)
                if len(found) >= limit:
                    break
        found.reverse()
        return found

    def _open_snapshot_locked(self) -> Optional[tuple[BinaryIO, int, tuple]]:
        """정리할 파일의 핸들, 그 순간의 크기, **그 파일이 무엇이었는지**.

        락 안에서 부른다. 크기를 락 안에서 떠야 줄 경계에 선다 — `record()` 는
        한 줄을 락 안에서 쓰고 닫는다. 읽기는 호출자가 락 **밖에서** 이
        핸들로 한다.

        신원까지 함께 든다. 정리는 락을 놓고 파싱한 뒤 돌아와 이어 붙이는데,
        그때 "이 파일이 아직 그 파일인가"를 크기로만 묻는 것은 부족하다 —
        같은 길이거나 더 긴 것으로 갈아 끼워지면 크기 검사는 통과하고, 우리는
        남의 내용 한가운데에 우리 옛 스냅샷을 이어 붙인다.
        """
        if not self._path.is_file():
            return None
        handle = self._path.open("rb")
        info = os.fstat(handle.fileno())
        return handle, info.st_size, (info.st_dev, info.st_ino)

    @staticmethod
    def _decode(raw: bytes) -> str:
        """`errors="replace"` 로 읽는다.

        정전이 잘라 놓은 UTF-8 꼬리(이 파일은 덧붙이기를 fsync 하지 않는다)에
        `strict` 로 부딪히면 `UnicodeDecodeError` 다. 그것이 `history()` 에서
        나면 `/logs/audit` 은 그 뒤로 영원히 500 이고, 감사 로그를 읽으러 온
        사람은 30 일치를 통째로 못 보게 된다 — 바이트 몇 개 때문에. 깨진 줄은
        깨진 JSON 이 되어 조회가 건너뛰고, 다음 정리가 그 줄을 격리한다.
        """
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _event_from(raw_line: bytes) -> Optional[EventMessage]:
        """한 줄을 기록으로. 기록이 아니면 `None`.

        조회와 정리가 **같은 함수**로 판정한다. 둘이 어긋나면 조회가 돌려준
        기록을 정리가 지우거나, 디스크에 있는 기록을 조회가 부인한다.

        바이트를 먼저 자른다. `str.strip()` 의 공백에는 U+2028·U+00A0 이 들어
        있어 `bytes.strip()` 과 결과가 달라진다.
        """
        line = raw_line.strip()
        if not line:
            return None
        try:
            return EventMessage.model_validate_json(FileAuditLog._decode(line))
        except (ValueError, TypeError):
            return None

    def _compact(self) -> None:
        """보존 기간이 지난 줄을 파일에서 실제로 덜어낸다. 작업 스레드에서 돈다.

        락은 두 번만, 파싱 없이 잡는다: (1) 크기·신원을 뜰 때, (2) 그 뒤에
        덧붙은 꼬리를 이어 붙여 바꿔 끼울 때. 읽기·디코드·파싱과 앞부분을 임시
        파일에 쓰고 fsync 하는 일은 모두 락 밖이다 — 10 만 줄이면 수백 ms 이고,
        그 사이 `record()` 는 그대로 덧붙인다.

        스냅샷을 뜬 뒤에 덧붙은 줄은 잃지 않는다. 이 파일에 쓰는 것은 덧붙이기
        뿐이므로(D-1: 프로세스도 하나) 그 사이 자란 부분은 스냅샷 길이 뒤에
        그대로 있고, 그것을 잘라 새 내용 뒤에 붙인다.

        **스키마로 읽을 수 없는 줄은 지우지 않는다.** 롤백 뒤의 스키마 차이나
        비트 하나가 기록을 "읽을 수 없게" 만들 수 있고, 감사 로그에서 삭제는
        되돌릴 수 없다(`_is_fresh` 와 같은 fail-open). 규칙은 하나다:

        * JSON 으로 읽히고 문자열 `ts` 가 있으면, 그 `ts` 로 보존 규칙을 따른다 —
          보존 기간 안이면 원본 그대로 남기고, 지났으면 다른 기록처럼 덜어낸다.
        * 그렇지 않으면(잘린 꼬리, 깨진 바이트) 원본 바이트를 그대로
          `<파일>.quarantine` 에 덧붙이고 본 파일에서 뺀다. 격리 파일은 정리하지
          않는다 — 손상은 드물고, 그 바이트가 사고 조사의 증거일 수 있다.

        빈 줄은 기록이 아니므로 그냥 덜어낸다.
        """
        with self._lock:
            opened = self._open_snapshot_locked()
        if opened is None:
            return
        handle, size, identity = opened
        # 읽기는 한 번에, 락 밖에서 하고 곧바로 닫는다. 파싱 내내 핸들을 쥐고
        # 있으면 Windows 에서는 그동안 누구도 이 파일을 지우거나 바꿔 끼우지
        # 못한다. 읽기 시스템 호출은 GIL 을 놓는다.
        with handle:
            snapshot = io.BytesIO(handle.read(size))
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            dropped, quarantined = self._classify(snapshot, size)
            if not dropped:
                # 버릴 것이 없으면 쓰지 않는다. 같은 내용으로 파일을 갈아
                # 끼우는 것은 공짜가 아니다 — 30 일치를 매 시각 재작성하는
                # 것이고, 그때마다 원본이 잠깐 사라지는 창이 생긴다.
                return
            # 앞부분은 락 밖에서 임시 파일에 쓰고 디스크까지 내린다. 락
            # 안에서는 그 뒤에 덧붙은 꼬리(대개 몇 줄)만 더한다. 통째로
            # `join` 하지 않고 줄마다 흘려 쓴다 — 그 C 호출 하나가 GIL 을 쥔다.
            with tmp.open("wb") as out:
                for index, raw in enumerate(_lines_forward(snapshot, size)):
                    if index % _YIELD_EVERY == 0:
                        _yield_gil()
                    if index not in dropped:
                        # 원본 **바이트** 를 그대로 남긴다(앞뒤 공백만 뗀다).
                        # 다시 직렬화하면 감사 기록이 스키마 왕복에 따라
                        # 조용히 달라질 수 있다.
                        out.write(raw.strip() + b"\n")
                out.flush()
                os.fsync(out.fileno())
            with self._lock:
                tail = self._tail_after_locked(size, identity)
                if tail is None:
                    # 실패가 아니라 전제가 깨진 것이다. 그래도 세어 둔다 — 조용히
                    # 넘기면 파일을 계속 자르는 외부 도구 하나가 정리를 영원한
                    # 무동작으로 만들면서 건강 상태는 깨끗하다고 답한다.
                    self._prune_skipped += 1
                    self._last_skip_reason = "the file is no longer the one we read"
                    tmp.unlink(missing_ok=True)
                    return
                if quarantined:
                    # 본 파일에서 빼기 **전에** 격리 파일에 내려 둔다. 바꿔 끼우기가
                    # 실패하면 다음 정리에서 같은 줄이 한 번 더 격리되지만, 순서가
                    # 거꾸로면 그 사이의 정전이 그 바이트를 영영 지운다.
                    with self.quarantine_path.open("ab") as sink:
                        sink.write(b"\n".join(quarantined) + b"\n")
                        sink.flush()
                        os.fsync(sink.fileno())
                # 꼬리는 fsync 하지 않는다. 그것은 스냅샷 뒤에 덧붙은 몇 줄이고,
                # 덧붙이기는 원래 fsync 하지 않는다(모듈 설명). 30 일치 앞부분은
                # 위에서 락 밖에서 이미 디스크에 내렸다 — 락 안의 fsync 는 SD
                # 카드에서 수~수십 ms 이고, 그동안 `record()` 가 기다린다.
                with tmp.open("ab") as out:
                    out.write(tail)
                # Windows 에서 이것은 대상에 열린 핸들이 하나라도 있으면
                # `PermissionError` 다 (백신·인덱서·조회 중인 `history()`). 여기서
                # 자며 다시 시도하지 않는다. 재시도는 한 시간 뒤 다음 정리 시각이
                # 한다. 그 사이 원본은 그대로 남아 있으므로 잃는 것은 없다.
                os.replace(tmp, self._path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        _fsync_directory(self._path.parent)

    def _classify(self, handle: BinaryIO, size: int) -> tuple[set[int], list[bytes]]:
        """(본 파일에서 뺄 줄 번호, 그중 격리할 원본 바이트).

        **줄을 바이트로 다룬다** — 디코드해서 자르고 다시 인코드하면
        `errors="replace"` 가 바꿔 놓은 바이트가 그대로 디스크에 쓰여, "원본 줄을
        그대로 남긴다"는 약속이 깨진 줄에 대해서만 조용히 거짓이 된다.
        """
        cutoff = self._now() - timedelta(days=self._retention_days)
        dropped: set[int] = set()
        quarantined: list[bytes] = []
        for index, raw in enumerate(_lines_forward(handle, size)):
            if index % _YIELD_EVERY == 0:
                _yield_gil()
            stripped = raw.strip()
            if not stripped:
                # 빈 줄은 기록이 아니다. 빼지 않으면 파일이 사는 내내 남는다.
                dropped.add(index)
                continue
            event = self._event_from(stripped)
            if event is not None:
                ts: Optional[str] = event.ts
            else:
                ts = self._recover_ts(stripped)
                if ts is None:
                    dropped.add(index)
                    quarantined.append(stripped)
                    continue
            if not self._is_fresh(ts, cutoff):
                dropped.add(index)
        return dropped, quarantined

    @staticmethod
    def _recover_ts(stripped: bytes) -> Optional[str]:
        """스키마로는 못 읽은 줄에서 `ts` 만 건진다. 못 건지면 `None`."""
        try:
            obj = json.loads(FileAuditLog._decode(stripped))
        except ValueError:
            return None
        ts = obj.get("ts") if isinstance(obj, dict) else None
        return ts if isinstance(ts, str) else None

    def _tail_after_locked(self, offset: int,
                           identity: Optional[tuple]) -> Optional[bytes]:
        """스냅샷 이후에 덧붙은 바이트. 이어 붙일 수 없으면 `None`.

        이 자리가 성립하는 근거는 "그 사이 이 파일에는 덧붙이기만 일어난다"
        (D-1: 쓰는 것은 한 프로세스, 그리고 정리는 작업 스레드 하나가 한다)
        이다. 근거가 깨졌다면 우리가 든 스냅샷은 더 이상 이 파일의 앞부분이
        아니고, 그대로 이어 붙이면 남의 내용에 우리 옛 스냅샷을 덮어쓴다.

        **크기로만 묻지 않는다.** 크기는 줄어든 것만 잡는다 — 같은 길이거나 더
        긴 것으로 갈아 끼워지면 통과하고, 우리는 남의 파일 한가운데에 이어
        붙인다. 신원(`st_dev`, `st_ino`)을 함께 본다.

        검사와 읽기는 **같은 핸들** 위에서 한다. `stat()` 으로 묻고 나서 따로
        여는 것은 그 사이에 갈아 끼워질 수 있다는 뜻이다.
        """
        if not self._path.is_file():
            return None
        with self._path.open("rb") as handle:
            info = os.fstat(handle.fileno())
            if identity is not None and (info.st_dev, info.st_ino) != identity:
                return None
            if info.st_size < offset:
                return None
            handle.seek(offset)
            return handle.read()

    def _is_fresh(self, ts: str, cutoff: datetime) -> bool:
        """보존 기간 안인가. **읽을 수 없는 `ts` 는 남긴다.**

        열려 있는(fail-open) 쪽을 고른 것이다. 닫으면 `ts` 한 글자가 깨진
        기록이 정리에서 조용히 지워지는데, 감사 로그에서 삭제는 되돌릴 수 없고
        보관은 되돌릴 수 있다. 대신 그런 줄은 `history()` 에 영원히 남아
        30 일 보존을 **오래 남기는 쪽으로** 어긴다 — 알고 하는 거래다.
        """
        try:
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return True
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed >= cutoff
