"""LOG-001 audit log framing, serialization, snapshot verification, and retention helpers."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Optional

from core_common.protocol.schemas import EventMessage

DEFAULT_RETENTION_DAYS = 30

#: 쓰기 경로에서 정리를 다시 시도하기까지의 최소 간격.
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
_YIELD_EVERY = 128
_YIELD_S = 0.001

#: "이 파일이 아직 그 파일인가"를 (장치, inode)만으로 묻지 않는다. 파일 앞과
#: 이어 붙일 경계 바로 앞의 바이트를 이만큼씩 맞춰 본다.
_FINGERPRINT_BYTES = 4096


def _yield_gil() -> None:
    """GIL 을 기다리는 스레드(= `record()` 를 부른 스레드)에 차례를 준다."""
    time.sleep(_YIELD_S)


class _AuditStoreMixin:
    """Serialization, snapshot identity, quarantine deduplication, and line classification."""

    _path: Path
    _retention_days: int
    _now: object
    _monotonic: object
    _prune_interval_s: float
    _last_prune: Optional[float]
    _write_failures: int
    _write_failures_total: int
    _prune_failures: int
    _last_write_error: Optional[str]
    _last_prune_error: Optional[str]
    _tail_is_terminated: Optional[bool]
    _quarantined: Optional[
        tuple[tuple[int, int], set[tuple[int, bytes]], tuple[int, int, int, bytes]]
    ]

    @property
    def path(self) -> Path:
        return self._path

    @property
    def quarantine_path(self) -> Path:
        """스키마로도 JSON 으로도 읽을 수 없는 줄이 옮겨지는 곳."""
        return self._path.with_name(self._path.name + ".quarantine")

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
                # 마지막 바이트를 읽지 못했다 — 열린 핸들, ACL, 공유 위반.
                # 틀린 False 는 빈 줄 하나를 남기며 다음 정리가 지운다.
                self._tail_is_terminated = False
        return self._tail_is_terminated

    def _prune_due_locked(self) -> bool:
        if self._last_prune is None:
            return True
        return self._monotonic() - self._last_prune >= self._prune_interval_s

    def _open_snapshot_locked(self) -> Optional[tuple[BinaryIO, int, tuple]]:
        """정리할 파일의 핸들, 그 순간의 크기, 그 파일이 무엇이었는지.

        락 안에서 부른다. 크기를 락 안에서 떠야 줄 경계에 선다. 읽기는 호출자가
        락 밖에서 이 핸들로 한다.
        """
        if not self._path.is_file():
            return None
        handle = self._path.open("rb")
        info = os.fstat(handle.fileno())
        return handle, info.st_size, (info.st_dev, info.st_ino)

    @staticmethod
    def _decode(raw: bytes) -> str:
        """`errors="replace"` 로 읽는다.

        정전이 잘라 놓은 UTF-8 꼬리에 `strict` 로 부딪히면 `UnicodeDecodeError` 다.
        깨진 줄은 깨진 JSON 이 되어 조회가 건너뛰고, 다음 정리가 그 줄을 격리한다.
        """
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _event_from(raw_line: bytes) -> Optional[EventMessage]:
        """한 줄을 기록으로. 기록이 아니면 `None`.

        조회와 정리가 같은 함수로 판정한다. 바이트를 먼저 자른다.
        """
        line = raw_line.strip()
        if not line:
            return None
        try:
            return EventMessage.model_validate_json(_AuditStoreMixin._decode(line))
        except (ValueError, TypeError):
            return None

    def _already_quarantined(self, identity: tuple) -> set[tuple[int, bytes]]:
        """이 본 파일에서 격리했고 지금도 격리 파일에 있는 줄. 모르면 빈 집합."""
        if self._quarantined is None or self._quarantined[0] != identity:
            return set()
        dev, ino, size, last = self._quarantined[2]
        try:
            with self.quarantine_path.open("rb") as handle:
                info = os.fstat(handle.fileno())
                if (info.st_dev, info.st_ino) != (dev, ino) or info.st_size < size:
                    return set()
                handle.seek(size - len(last))
                if handle.read(len(last)) != last:
                    return set()
        except OSError:
            return set()
        return self._quarantined[1]

    def _classify(
        self, handle: BinaryIO, size: int
    ) -> tuple[set[int], list[tuple[int, bytes]]]:
        """(본 파일에서 뺄 줄 번호, 그중 격리할 (오프셋, 원본 바이트))."""
        from . import audit

        cutoff = self._now() - timedelta(days=self._retention_days)
        dropped: set[int] = set()
        quarantined: list[tuple[int, bytes]] = []
        offset = 0
        for index, raw in enumerate(audit._lines_forward(handle, size)):
            if index % _YIELD_EVERY == 0:
                _yield_gil()
            start, offset = offset, offset + len(raw) + 1
            stripped = raw.strip()
            if not stripped:
                dropped.add(index)
                continue
            event = self._event_from(stripped)
            if event is not None:
                ts: Optional[str] = event.ts
            else:
                ts = self._recover_ts(stripped)
                if ts is None:
                    dropped.add(index)
                    quarantined.append((start, stripped))
                    continue
            if not self._is_fresh(ts, cutoff):
                dropped.add(index)
        return dropped, quarantined

    @staticmethod
    def _recover_ts(stripped: bytes) -> Optional[str]:
        """스키마로는 못 읽은 줄에서 `ts` 만 건진다. 못 건지면 `None`."""
        try:
            obj = json.loads(_AuditStoreMixin._decode(stripped))
        except ValueError:
            return None
        ts = obj.get("ts") if isinstance(obj, dict) else None
        return ts if isinstance(ts, str) else None

    def _tail_after_locked(
        self,
        offset: int,
        identity: Optional[tuple],
        fingerprint: tuple[bytes, bytes],
    ) -> Optional[bytes]:
        """스냅샷 이후에 덧붙은 바이트. 이어 붙일 수 없으면 `None`."""
        if not self._path.is_file():
            return None
        with self._path.open("rb") as handle:
            info = os.fstat(handle.fileno())
            if identity is not None and (info.st_dev, info.st_ino) != identity:
                return None
            if info.st_size < offset:
                return None
            head, boundary = fingerprint
            if head:
                handle.seek(0)
                if handle.read(len(head)) != head:
                    return None
            if boundary:
                handle.seek(offset - len(boundary))
                if handle.read(len(boundary)) != boundary:
                    return None
            handle.seek(offset)
            return handle.read()

    def _is_fresh(self, ts: str, cutoff: datetime) -> bool:
        """보존 기간 안인가. 읽을 수 없는 `ts` 는 남긴다 (fail-open)."""
        try:
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return True
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed >= cutoff
