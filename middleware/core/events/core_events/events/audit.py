"""LOG-001 file audit log. Same EventMessage schema as the in-memory bus.

기록은 이벤트 버스의 구독자로 붙어 있고(`core/services.py`), 버스는 구독자를 **동기로**
부른다. 그래서 `record()` 가 무거우면 그 비용은 이벤트를 낸 스레드가 문다 — 그중
하나가 50 Hz cmd_vel 타이머다.

보존은 "읽었을 때 30 일 넘은 것이 없다"는 약속이지 "매 쓰기마다 즉시 정리한다"는
약속이 아니다. 그래서:

* `record()` 는 **덧붙이기만** 한다. 정리 시각이 되었으면 정리를 전용 작업
  스레드에 넘기고 곧바로 돌아온다.
* 정리는 락을 **두 번, 짧게** 잡는다. 크기·신원을 뜰 때와, 그 뒤에 덧붙은 꼬리를
  이어 붙여 바꿔 끼울 때. 읽기·디코드·파싱·임시 파일 쓰기는 모두 락 밖이다.
* `history()` 는 여는 순간만 락을 잡고, 파일 **끝에서부터** 읽어 필요한 만큼만
  파싱한다.
* 작업 스레드는 파싱하는 동안 주기적으로 잠깐 잠든다(`_YIELD_EVERY`).

이 구현이 **하지 않는** 것 두 가지 (알고 두는 것이지 잊은 것이 아니다):

* **덧붙이기는** `fsync` 하지 않는다. **정리의 바꿔 끼우기는** 새 파일을 `fsync`
  한 뒤에 한다. 정리 도중에 덧붙은 꼬리 몇 줄은 덧붙이기와 같은 규칙으로 fsync
  하지 않는다.
* 여러 **프로세스** 가 같은 파일을 쓰는 것을 막지 않는다(D-1 에 따라 `core` 한
  프로세스만 쓴다).

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

from .audit_helpers import (
    DEFAULT_RETENTION_DAYS,
    PRUNE_INTERVAL_S,
    _COMPACT_BLOCK,
    _FINGERPRINT_BYTES,
    _READ_CHUNK,
    _YIELD_EVERY,
    _YIELD_S,
    _AuditStoreMixin,
    _yield_gil,
)


def _lines_forward(handle: BinaryIO, size: int) -> Iterator[bytes]:
    """`[0, size)` 를 조각으로 읽어 줄을 **바이트 그대로** 돌려준다.

    개행 하나로만 나눈다(JSON Lines). `bytes.splitlines()` 를 쓰지 않는다 —
    그것은 홀로 있는 캐리지리턴에서도 자른다. 마지막 개행 뒤는 줄이 아니다.
    조각마다 GIL 을 내어 준다.
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


class FileAuditLog(_AuditStoreMixin):
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
        #: None = 아직 한 번도 정리하지 않았다. 첫 기록은 정리를 요청한다.
        self._last_prune: Optional[float] = None
        #: 기록이 실패한 횟수와 마지막 사유 (`_write_failures` 는 연속 gauge,
        #: `_write_failures_total` 은 누적 counter).
        self._write_failures = 0
        self._write_failures_total = 0
        self._prune_failures = 0
        self._serialize_failures = 0
        self._last_write_error: Optional[str] = None
        self._last_prune_error: Optional[str] = None
        self._last_serialize_error: Optional[str] = None
        self._prune_skipped = 0
        self._last_skip_reason: Optional[str] = None
        self._dir_sync_failures = 0
        self._last_dir_sync_error: Optional[str] = None
        self._quarantined: Optional[
            tuple[tuple[int, int], set[tuple[int, bytes]], tuple[int, int, int, bytes]]
        ] = None
        self._worker: Optional[threading.Thread] = None
        self._compaction_requested = False
        self._tail_is_terminated: Optional[bool] = None
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)

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
                "dir_sync_failures": self._dir_sync_failures,
                "last_skip_reason": self._last_skip_reason,
                "last_write_error": self._last_write_error,
                "last_prune_error": self._last_prune_error,
                "last_serialize_error": self._last_serialize_error,
                "last_dir_sync_error": self._last_dir_sync_error,
            }

    def settle(self, timeout: Optional[float] = 10.0) -> bool:
        """요청된 정리가 끝날 때까지 기다린다. 끝났으면 `True`."""
        with self._idle:
            return self._idle.wait_for(lambda: self._worker is None, timeout)

    def record(self, event: EventMessage) -> None:
        """덧붙이고 돌아온다. **예외를 밖으로 던지지 않는다.**"""
        payload, serialize_error = self._serialize(event)
        with self._lock:
            if serialize_error is not None:
                self._serialize_failures += 1
                self._last_serialize_error = serialize_error
            if payload is None:
                self._note_write_failure(serialize_error or "unserialisable event")
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8", newline="") as handle:
                    if not self._terminated_locked():
                        handle.write("\n")
                    handle.write(payload + "\n")
                self._tail_is_terminated = True
            except OSError as error:
                self._note_write_failure(f"{type(error).__name__}: {error}")
                self._tail_is_terminated = None
                return
            self._write_failures = 0

            if self._prune_due_locked() and self._worker is None:
                self._last_prune = self._monotonic()
                self._compaction_requested = True
                self._worker = threading.Thread(
                    target=self._compaction_worker, name="audit-compactor", daemon=True
                )
                try:
                    self._worker.start()
                except RuntimeError as error:
                    self._worker = None
                    self._compaction_requested = False
                    self._prune_failures += 1
                    self._last_prune_error = (
                        f"worker start: {type(error).__name__}: {error}"
                    )

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
                with self._lock:
                    self._note_prune_failure(error)

    def history(
        self,
        *,
        since_seq: Optional[int] = None,
        limit: int = 500,
    ) -> list[EventMessage]:
        """보존 기간 안의 기록, 오래된 것부터. **파일은 건드리지 않는다.**"""
        if limit < 1:
            return []
        cutoff = self._now() - timedelta(days=self._retention_days)
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

    def _compact(self) -> None:
        """보존 기간이 지난 줄을 파일에서 실제로 덜어낸다. 작업 스레드에서 돈다."""
        with self._lock:
            opened = self._open_snapshot_locked()
        if opened is None:
            return
        handle, size, identity = opened
        with handle:
            data = handle.read(size)
        snapshot = io.BytesIO(data)
        fingerprint = (data[:_FINGERPRINT_BYTES], data[-_FINGERPRINT_BYTES:])
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            dropped, quarantined = self._classify(snapshot, size)
            if not dropped:
                return
            with tmp.open("wb") as out:
                for index, raw in enumerate(_lines_forward(snapshot, size)):
                    if index % _YIELD_EVERY == 0:
                        _yield_gil()
                    if index not in dropped:
                        out.write(raw.strip() + b"\n")
                out.flush()
                os.fsync(out.fileno())
            done = self._already_quarantined(identity)
            fresh = [item for item in quarantined if item not in done]
            if fresh:
                payload = b"".join(line + b"\n" for _, line in fresh)
                with self.quarantine_path.open("ab") as sink:
                    sink.write(payload)
                    sink.flush()
                    end = sink.tell()
                    os.fsync(sink.fileno())
                    info = os.fstat(sink.fileno())
                self._quarantined = (
                    identity,
                    done | set(fresh),
                    (
                        info.st_dev,
                        info.st_ino,
                        end,
                        payload[-_FINGERPRINT_BYTES:],
                    ),
                )
            with self._lock:
                tail = self._tail_after_locked(size, identity, fingerprint)
                if tail is None:
                    self._prune_skipped += 1
                    self._last_skip_reason = "the file is no longer the one we read"
                    tmp.unlink(missing_ok=True)
                    return
                with tmp.open("ab") as out:
                    out.write(tail)
                os.replace(tmp, self._path)
                self._quarantined = None
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        try:
            _fsync_directory(self._path.parent)
        except OSError as error:
            with self._lock:
                self._dir_sync_failures += 1
                self._last_dir_sync_error = f"{type(error).__name__}: {error}"


__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "FileAuditLog",
    "PRUNE_INTERVAL_S",
    "_AuditStoreMixin",
    "_COMPACT_BLOCK",
    "_FINGERPRINT_BYTES",
    "_READ_CHUNK",
    "_YIELD_EVERY",
    "_YIELD_S",
    "_fsync_directory",
    "_lines_backward",
    "_lines_forward",
    "_yield_gil",
]
