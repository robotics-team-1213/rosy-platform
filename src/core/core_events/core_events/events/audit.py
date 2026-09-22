"""LOG-001 file audit log. Same EventMessage schema as the in-memory bus.

기록은 이벤트 버스의 구독자로 붙어 있고(`core/services.py`), 버스는 구독자를 **동기로**
부른다. 그래서 `record()` 가 무거우면 그 비용은 이벤트를 낸 스레드가 문다 — 그중
하나가 50 Hz cmd_vel 타이머다.

예전에는 이벤트 하나마다 파일 전체를 읽어 모든 줄을 파싱하고 다시 직렬화해
덮어썼다. 보존 기간이 30 일이라 파일은 계속 자라고, 비용은 줄 수에 비례한다:
800 줄에서 `record()` 한 번이 16 ms — 50 Hz 주기의 0.8 개 — 이고 파일을 채우는
전체 비용은 O(n²) 이다. 30 일치면 그보다 한참 크다.

보존은 "읽었을 때 30 일 넘은 것이 없다"는 약속이지 "매 쓰기마다 즉시 정리한다"는
약속이 아니다. 그래서 쓰기는 덧붙이기만 하고, 조회는 메모리에서 걸러 답하며,
파일을 실제로 줄이는 것은 쓰기 경로가 한 시간에 한 번 한다.

이 구현이 **하지 않는** 것 두 가지 (알고 두는 것이지 잊은 것이 아니다):

* `fsync` 하지 않는다. 정전이면 OS 버퍼에 있던 마지막 몇 줄이 사라질 수 있다.
  매 이벤트마다 `fsync` 하면 SD 카드에서 한 번에 수 ms 가 들고 그 비용을 50 Hz
  타이머가 문다 — 이 파일이 애초에 고치려던 문제로 되돌아간다. 딥 방전 종료
  (D-27)는 정상 종료 경로라 버퍼가 비워지고, 갑작스러운 정전에서 마지막 몇 줄을
  잃는 것은 LOG-001 이 요구하는 30 일 보존과 다른 이야기다.
* 여러 **프로세스** 가 같은 파일을 쓰는 것을 막지 않는다. `threading.Lock` 은
  프로세스 안에서만 유효하고, 정리의 읽기-쓰기 사이에 다른 프로세스가 덧붙인
  줄은 `os.replace` 에 지워진다. D-1 에 따라 이 파일을 쓰는 것은 `core`
  한 프로세스뿐이므로 지금은 성립한다 — 두 번째 쓰는 쪽이 생기면 파일 락이
  필요하고, 그것은 이 주석이 아니라 ADR 로 정해야 한다.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from core_common.protocol.schemas import EventMessage

DEFAULT_RETENTION_DAYS = 30

#: 쓰기 경로에서 정리를 다시 시도하기까지의 최소 간격.
#:
#: 30 일 보존에 한 시간의 여유를 두는 것이므로 정책은 그대로다. 대신 쓰기 한 번의
#: 비용이 줄 수와 무관해진다.
PRUNE_INTERVAL_S = 3600.0


def _raw_lines(blob: bytes) -> list[bytes]:
    """줄을 **바이트 그대로** 자른다.

    `bytes.splitlines()` 를 쓰지 않는다 — 그것은 홀로 있는 캐리지리턴에서도
    자른다. 그러면 한 줄이었던 기록이 두 줄로 보여 둘 다 깨진 JSON 이 되고,
    조회에서 사라진 뒤 다음 정리에 지워진다. 이 파일의 줄 구분자는 개행
    하나다(JSON Lines).

    (`str.splitlines()` 는 여기에 세로탭·폼피드·파일/그룹/레코드 구분자와
    U+2028·U+2029·U+0085 까지 더한다. 그래서 `_parse` 도 str 이 아니라 이
    함수로 나눈다. 그 목록을 짧게 적어 두었더니 세로탭·폼피드가 빠졌고,
    하필 그 둘이 `_parse` 의 자르는 순서를 검사할 수 있는 유일한 바이트였다.)
    """
    lines = blob.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()          # 마지막 개행 뒤는 줄이 아니다
    return lines


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
        #: None = 아직 한 번도 정리하지 않았다. 첫 기록은 정리한다 — 지난
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
        #: 마지막 사유는 지우지 않는다. 성공 한 번에 지워 버리면 간헐적으로
        #: 실패하는 디스크는 운영자가 볼 때마다 늘 깨끗해 보인다.
        #:
        #: 채널마다 따로 남긴다. 하나로 두면 정리 실패 한 번이 디스크가 찼다는
        #: 사유를 덮어써, 운영자는 0 이 아닌 `write_failures_total` 과 전혀 다른
        #: 이야기를 하는 `last_error` 를 함께 보게 된다.
        self._last_write_error: Optional[str] = None
        self._last_prune_error: Optional[str] = None
        #: 이어 붙일 수 없어 정리를 거른 횟수. 실패가 아니라 "전제가 깨졌다"이고,
        #: 계속 오르면 이 파일을 우리 말고 누가 건드리고 있다는 뜻이다.
        self._prune_skipped = 0
        #: 거른 이유는 실패 사유 칸에 적지 않는다. 그러면 prune_failures 를
        #: 보고 온 운영자가 다른 채널의 이야기를 읽게 된다.
        self._last_skip_reason: Optional[str] = None
        #: 정리는 한 번에 하나만. `_last_prune` 이 사실상 그 역할을 해 왔지만,
        #: 그것은 `prune_interval_s` 가 0 보다 크다는 데 기대는 창발적 성질이라
        #: 생성자 인자 하나로 깨진다. 불변식은 창발이 아니라 명시로 둔다.
        self._compacting = False
        #: 지난 실행이 남긴 마지막 줄이 개행으로 끝나는가. 정전이 UTF-8 한 글자
        #: 가운데를 잘랐다면 그 개행은 애초에 쓰이지 못했다 — 그 뒤에 그냥
        #: 덧붙이면 새 이벤트가 그 망가진 줄의 일부가 되어 함께 버려진다.
        #: 한 프로세스가 시작할 때 한 번만 확인한다(D-1). 이후의 덧붙이기는
        #: 우리가 쓴 것이므로 반드시 개행으로 끝난다.
        self._tail_is_terminated: Optional[bool] = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def health(self) -> dict:
        """기록이 실제로 남고 있는가. 운영자가 감사 로그를 물을 때 함께 답한다."""
        with self._lock:
            return {
                "writable": self._write_failures == 0,
                "write_failures": self._write_failures,
                "write_failures_total": self._write_failures_total,
                "prune_failures": self._prune_failures,
                "prune_skipped": self._prune_skipped,
                "last_skip_reason": self._last_skip_reason,
                "last_write_error": self._last_write_error,
                "last_prune_error": self._last_prune_error,
            }

    def record(self, event: EventMessage) -> None:
        with self._lock:
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
                        # 지워진다. 정전 직후 처음 기록되는 것이 하필
                        # `safety.estop` 일 수 있다.
                        handle.write("\n")
                    handle.write(event.model_dump_json() + "\n")
                # 닫힌 **뒤에** 세운다. with 를 나가며 flush 하고 실제 쓰기 오류는
                # 거의 다 거기서 난다 — 한 줄은 버퍼보다 훨씬 작다. 안에서 세우면
                # 실패한 쓰기가 "개행으로 끝났다"를 남기고, 그 캐시가 바로 위의
                # 꼬리 확인이 막으려던 구멍을 다시 연다.
                self._tail_is_terminated = True
            except OSError as error:
                # EventBus 는 구독자 예외를 삼킨다. 그대로 두면 감사 기록이
                # 멈춘 사실이 어디에도 남지 않는다 — 디스크가 찬 로봇은 아무
                # 말 없이 LOG-001 을 지키지 않게 된다. 세어 두고, 물으면 답한다.
                self._write_failures += 1
                self._write_failures_total += 1
                self._last_write_error = f"{type(error).__name__}: {error}"
                # 실패한 쓰기는 꼬리에 대해 아무것도 말해 주지 않는다. 부분
                # 기록일 수도, 아무것도 안 나갔을 수도 있다. 다음 기록이 다시
                # 확인하게 둔다.
                #
                # 실패가 이어지는 동안은 **기록마다** 다시 확인한다. ENOSPC 는
                # open 을 통과하고 close 에서 나므로 캐시가 매번 여기로 온다.
                # 한 줄 크기의 메타데이터 읽기이고, 그 사이 감사 기록은 이미
                # 멈춰 있다 — 성공하는 경로에는 아무 비용도 없다.
                self._tail_is_terminated = None
                raise
            self._write_failures = 0

            snapshot: Optional[bytes] = None
            identity: Optional[tuple] = None
            if self._prune_due_locked() and not self._compacting:
                # 시각을 먼저 태운다. 아래에서 실패해도 매 기록마다 다시
                # 시도하지 않고 한 시간 뒤에 한 번 더 해 본다. 이 줄이 읽기
                # 뒤로 내려가면 50 Hz 스레드가 실패하는 읽기를 매 주기 재시도한다.
                self._last_prune = self._monotonic()
                try:
                    snapshot, identity = self._snapshot_locked()
                except OSError as error:
                    # 이 읽기도 세어야 한다. 가드 밖에 두면 열린 핸들 하나(백신·
                    # 인덱서)가 정리를 영원히 멈추면서 건강 상태는 깨끗하다고
                    # 답한다 — `health()` 가 없애려던 상태로 세 번째 문을 통해
                    # 돌아가는 것이다.
                    self._note_prune_failure(error)
                    snapshot = None
                else:
                    self._compacting = True

        # 이벤트는 이미 파일에 있다. 여기서부터 실패해도 그것은 되돌아가지
        # 않으므로, 정리 실패를 쓰기 실패로 세거나 밖으로 던지지 않는다 —
        # 그렇게 하면 감사 기록은 멀쩡한데 로그가 꺼졌다고 답하게 된다.
        #
        # `OSError` 만 잡으면 부족하다. `_compact` 가 하는 일 중에는 I/O 가 아닌
        # **디코드** 가 있고, 그 실패는 `UnicodeDecodeError`(= `ValueError`) 다 —
        # 그리고 fsync 하지 않는다는 이 파일의 결정이 바로 그 잘린 꼬리를 만든다.
        # 그것이 여기를 빠져나가면 EventBus 가 삼켜 아무 데도 남지 않고,
        # `/logs/audit` 은 그 뒤로 영원히 500 이 된다. 무엇을 던지든 센다.
        if snapshot is None:
            return
        try:
            self._compact(snapshot, identity)
        except (OSError, ValueError) as error:
            with self._lock:
                self._note_prune_failure(error)
        finally:
            with self._lock:
                self._compacting = False

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

    def history(
        self,
        *,
        since_seq: Optional[int] = None,
        limit: int = 500,
    ) -> list[EventMessage]:
        """보존 기간 안의 기록. **파일은 건드리지 않는다.**

        예전에는 읽을 때마다 정리를 돌렸다. 조회 한 번이 파일 전체를 다시
        쓰는 것이고, 대시보드가 5 초마다 폴링하면 5 초마다 감사 로그가 통째로
        재작성된다 — 버릴 줄이 하나도 없어도 그렇다. 게다가 그 파싱과 재작성이
        전부 `record()` 와 같은 락 안에 있어서, 조회 한 번이 50 Hz cmd_vel
        타이머를 그만큼 세운다.

        보존은 "읽었을 때 30 일 넘은 것이 보이지 않는다"는 약속이다. 그 약속은
        메모리에서 걸러도 똑같이 지켜진다. 파일을 실제로 줄이는 것은 쓰기
        경로가 한 시간에 한 번 한다.

        락은 원시 텍스트를 읽는 동안만 잡는다. 파싱은 밖에서 한다 — 비싼 쪽이
        그쪽이고, 그 사이 덧붙는 줄은 다음 조회에 보이면 된다.
        """
        with self._lock:
            raw = self._read_bytes_locked()
            cutoff = self._now() - timedelta(days=self._retention_days)
        events = [event for event in self._parse(raw)
                  if self._is_fresh(event.ts, cutoff)]
        if since_seq is not None:
            events = [item for item in events if item.seq > since_seq]
        if limit < 1:
            return []
        return events[-limit:]

    def _read_bytes_locked(self) -> bytes:
        return self._snapshot_locked()[0]

    def _snapshot_locked(self) -> tuple[bytes, Optional[tuple]]:
        """파일 내용과, **그 파일이 무엇이었는지**.

        신원까지 함께 든다. 정리는 락을 놓고 파싱한 뒤 돌아와 이어 붙이는데,
        그때 "이 파일이 아직 그 파일인가"를 크기로만 묻는 것은 부족하다 —
        같은 길이거나 더 긴 것으로 갈아 끼워지면 크기 검사는 통과하고, 우리는
        남의 내용 한가운데에 우리 옛 스냅샷을 이어 붙인다.
        """
        if not self._path.is_file():
            return b"", None
        with self._path.open("rb") as handle:
            raw = handle.read()
            info = os.fstat(handle.fileno())
        return raw, (info.st_dev, info.st_ino)

    @staticmethod
    def _decode(raw: bytes) -> str:
        """`errors="replace"` 로 읽는다.

        정전이 잘라 놓은 UTF-8 꼬리(이 파일은 fsync 하지 않는다)에 `strict` 로
        부딪히면 `UnicodeDecodeError` 다. 그것이 `history()` 에서 나면
        `/logs/audit` 은 그 뒤로 영원히 500 이고, 감사 로그를 읽으러 온 사람은
        30 일치를 통째로 못 보게 된다 — 바이트 몇 개 때문에. 깨진 줄은 깨진
        JSON 이 되어 `_parse` 가 건너뛰고, 다음 정리가 그 줄을 덜어낸다.
        """
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _parse(raw: bytes) -> list[EventMessage]:
        """`_raw_lines` 와 같은 규칙으로 나눈다.

        `str.splitlines()` 는 U+2028·U+2029·U+0085 에서도 자르는데 정리는
        개행에서만 자른다. 어긋나 있으면 payload 에 그 글자가 든 기록이
        디스크에는 남고 조회에는 영영 안 보인다 — 감사 로그가 자기가 가진
        것을 부인하는 상태다.
        """
        events: list[EventMessage] = []
        for raw_line in _raw_lines(raw):
            # 바이트를 먼저 자른다. `str.strip()` 의 공백에는 U+2028·U+00A0 이
            # 들어 있어 `_compact` 의 `bytes.strip()` 과 결과가 달라진다 —
            # 조회는 돌려주고 정리는 지우는 줄이 생긴다.
            line = FileAuditLog._decode(raw_line.strip())
            if not line:
                continue
            try:
                events.append(EventMessage.model_validate_json(line))
            except (ValueError, TypeError):
                continue
        return events

    def _compact(self, snapshot: bytes, identity: Optional[tuple]) -> None:
        """보존 기간이 지난 줄을 파일에서 실제로 덜어낸다.

        **파싱은 락 밖에서 한다.** 10 만 줄이면 파싱만 350 ms 이고, 그것을 락을
        쥔 채로 하면 그 한 시간에 처음 기록되는 이벤트가 값을 문다 — 한 시간
        조용하던 로봇에서 그 이벤트는 하필 SAF-002 정지일 수 있다. 락은 (1) 위에서
        스냅샷을 뜰 때와 (2) 아래에서 갈아 끼울 때만, 파싱 없이 잡는다.

        스냅샷을 뜬 뒤에 덧붙은 줄은 잃지 않는다. 이 파일에 쓰는 것은 덧붙이기
        뿐이므로(D-1: 프로세스도 하나) 그 사이 자란 부분은 스냅샷 길이 뒤에
        그대로 있고, 그것을 잘라 새 내용 뒤에 붙인다.
        """
        cutoff = self._now() - timedelta(days=self._retention_days)
        kept: list[bytes] = []
        seen = 0
        # 디코드도 파싱도 락 밖이다. **줄을 바이트로 다룬다** — 디코드해서
        # 자르고 다시 인코드하면 `errors="replace"` 가 바꿔 놓은 바이트가 그대로
        # 디스크에 쓰여, "원본 줄을 그대로 남긴다"는 아래 약속이 깨진 줄에
        # 대해서만 조용히 거짓이 된다. 감사 로그에서 그것은 훼손과 정상 기록을
        # 구분할 방법을 없애는 것이다.
        for raw in _raw_lines(snapshot):
            stripped = raw.strip()
            # 빈 줄도 센다. 건너뛰면 `len(kept) == seen` 이 되어 아래 조기 반환에
            # 걸리고, 빈 줄은 파일이 사는 내내 남는다.
            seen += 1
            if not stripped:
                continue
            try:
                # `_decode` 는 잘린 UTF-8 꼬리를 예외가 아니라 깨진 JSON 으로
                # 만들고, 그 줄은 여기서 버려진다.
                event = EventMessage.model_validate_json(self._decode(stripped))
            except (ValueError, TypeError):
                # 읽을 수 없는 줄은 `history()` 도 건너뛴다. 여기서 버린다.
                continue
            if self._is_fresh(event.ts, cutoff):
                # 원본 **바이트** 를 그대로 남긴다. 다시 직렬화하면 감사 기록이
                # 스키마 왕복에 따라 조용히 달라질 수 있다.
                kept.append(stripped)

        if len(kept) == seen:
            # 버릴 것이 없으면 쓰지 않는다. 같은 내용으로 파일을 갈아 끼우는
            # 것은 공짜가 아니다 — 30 일치를 매 시각 재작성하는 것이고, 그때마다
            # 원본이 잠깐 사라지는 창이 생긴다.
            return

        head = b"\n".join(kept) + b"\n" if kept else b""
        with self._lock:
            tail = self._tail_after_locked(len(snapshot), identity)
            if tail is None:
                # 실패가 아니라 전제가 깨진 것이다. 그래도 세어 둔다 — 조용히
                # 넘기면 파일을 계속 자르는 외부 도구 하나가 정리를 영원한
                # 무동작으로 만들면서 건강 상태는 깨끗하다고 답한다.
                self._prune_skipped += 1
                self._last_skip_reason = "the file is no longer the one we read"
                return
            # 감사 로그를 자르는 도중에 죽으면 기록이 사라진다. 설정 오버레이와
            # 같은 규칙으로 임시 파일에 쓰고 바꿔 끼운다.
            tmp = self._path.with_name(self._path.name + ".tmp")
            try:
                tmp.write_bytes(head + tail)
                # Windows 에서 이것은 대상에 열린 핸들이 하나라도 있으면
                # `PermissionError` 다 (백신·인덱서·다른 프로세스의 조회). 여기서
                # 자며 다시 시도하지 않는다 — 락을 쥔 채 50 Hz cmd_vel 스레드
                # 위이기 때문이다. 재시도는 한 시간 뒤 다음 정리 시각이 한다.
                # 그 사이 원본은 그대로 남아 있으므로 잃는 것은 없다.
                os.replace(tmp, self._path)
            except OSError:
                tmp.unlink(missing_ok=True)
                raise

    def _tail_after_locked(self, offset: int,
                           identity: Optional[tuple]) -> Optional[bytes]:
        """스냅샷 이후에 덧붙은 바이트. 이어 붙일 수 없으면 `None`.

        이 자리가 성립하는 근거는 "그 사이 이 파일에는 덧붙이기만 일어난다"
        (D-1: 쓰는 것은 한 프로세스, 그리고 정리는 `_compacting` 으로 직렬화된다)
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
