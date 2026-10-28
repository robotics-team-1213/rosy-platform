"""D-426 Task 4 — 공유 구간 진입 허가와 점유 (Fleet 단일 writer).

구간 상태는 FREE(행 없)→RESERVED→OCCUPIED→RELEASING→FREE, 불명은 UNKNOWN이다.
Fleet만 기록 writer다 — 같은 Task DB 트랜잭션 안에서 돌며 competing dispatcher를
만들지 않는다(기존 dispatch_admission의 자원 claim과 별개 표).

불변식(D-426 결정 3·4, 계획 T4 항목 3·6):
- 진입 후 시간 만료·링크 상실만으로 구간이 FREE가 되지 않는다.
- RESERVED는 이전 실행이 구간 밖에서 비활성·정지했음을 확인하기 전 재할당하지 않는다.
- 해제(RELEASING→FREE)는 신선한 출구 이탈 관측과 종단 실행 결과를 대조해야 한다.
- grant 만료는 실제 footprint 진입 시한이다. 만료된 grant의 진입은 경계에서
  재검사되어 거부된다(로봇은 밖에서 정지).
"""

from __future__ import annotations

import math
import re
import sqlite3

from fleet.server.segment_store import atomic, prepare as _prepare

OK = "OK"
GRANT_REFUSED = "REFUSED"
#: 출구 관측·종단 결과의 신선 한계 — 이보다 오래된 관측은 해제 근거가 아니다.
OBSERVATION_MAX_AGE_S = 2.0
#: RESERVED 진입 없이 이 시간을 넘기면 운영자 대조 대상이다(자동 후진은 하지 않는다).
OPERATOR_ATTENTION_AFTER_S = 60.0

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TERMINAL = frozenset({"COMPLETED", "FAILED", "HOLD"})


def _now(value: str):
    from datetime import datetime

    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError('timezone-aware timestamp required')
    return result


def _age_s(later: str, earlier: str) -> float:
    return (_now(later) - _now(earlier)).total_seconds()


def _inside(segment, position) -> bool:
    return math.hypot(position[0] - segment["center_x"],
                      position[1] - segment["center_y"]) <= float(segment["radius_m"])


def _finite_point(point) -> bool:
    return (isinstance(point, (list, tuple)) and len(point) == 2
            and all(type(value) in (int, float) and math.isfinite(value) for value in point))


def _bound(row, task_id, attempt_id, robot_id, map_revision, generation) -> bool:
    return (row is not None and type(generation) is int
            and (row['task_id'], row['attempt_id'], row['robot_id'],
                 row['map_revision'], row['generation']) ==
            (task_id, attempt_id, robot_id, map_revision, generation))


def _fresh_exit(row, observed_at, now) -> bool:
    try:
        return (0 <= _age_s(now, observed_at) <= OBSERVATION_MAX_AGE_S
                and _age_s(observed_at, row['entry_confirmed_at']) >= 0)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return False


@atomic
def define_segments(connection: sqlite3.Connection, segments: list[dict]) -> None:
    """구간 ID·지도 revision·진입/출구·안전 대기점·반경을 명시한다."""
    _prepare(connection)
    for segment in segments:
        for key in ("segment_id", "map_revision"):
            if not _IDENTIFIER.fullmatch(str(segment.get(key, ""))):
                raise ValueError(f"segment {key} is invalid")
        radius = segment['radius_m']
        if type(radius) not in (int, float) or not math.isfinite(radius) or radius <= 0:
            raise ValueError("segment radius must be positive")
        if not all(_finite_point(segment.get(key)) for key in ('center', 'entry', 'exit', 'waiting_point')):
            raise ValueError('segment coordinates must be finite pairs')
        if _grant_row(connection, segment['segment_id']) is not None:
            raise ValueError('active segment geometry is immutable')
        connection.execute(
            """INSERT OR REPLACE INTO fleet_segments
               (segment_id, map_revision, center_x, center_y, radius_m,
                entry_x, entry_y, exit_x, exit_y, wait_x, wait_y)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (segment["segment_id"], segment["map_revision"],
             segment["center"][0], segment["center"][1], segment["radius_m"],
             segment["entry"][0], segment["entry"][1],
             segment["exit"][0], segment["exit"][1],
             segment["waiting_point"][0], segment["waiting_point"][1]),
        )


def _segment_row(connection, segment_id: str):
    return connection.execute(
        "SELECT * FROM fleet_segments WHERE segment_id=?", (segment_id,)).fetchone()


def _grant_row(connection, segment_id: str):
    return connection.execute(
        "SELECT * FROM fleet_segment_grants WHERE segment_id=?", (segment_id,)).fetchone()


def segment_state(connection: sqlite3.Connection, segment_id: str) -> str:
    """FREE(행 없) 또는 RESERVED/OCCUPIED/RELEASING/UNKNOWN."""
    _prepare(connection)
    row = _grant_row(connection, segment_id)
    return row["state"] if row is not None else "FREE"


@atomic
def request(connection: sqlite3.Connection, *, segment_id: str, task_id: str,
            attempt_id: str, robot_id: str, map_revision: str, generation: int,
            entry_deadline: str, now: str) -> str:
    """구간 진입 허가. 활성 상태(RESERVED/OCCUPIED/RELEASING/UNKNOWN)면 거부한다."""
    _prepare(connection)
    if not _IDENTIFIER.fullmatch(segment_id or ""):
        return f"{GRANT_REFUSED}: invalid segment id"
    segment = _segment_row(connection, segment_id)
    if segment is None:
        return f"{GRANT_REFUSED}: unknown segment"
    if segment["map_revision"] != map_revision:
        return f"{GRANT_REFUSED}: map revision {map_revision} is not the segment revision"
    existing = _grant_row(connection, segment_id)
    if existing is not None:
        # RESERVED 포함 — 이전 실행이 밖에서 비활성·정지했음을 확인하기 전 재할당 금지.
        return (f"{GRANT_REFUSED}: segment is {existing['state']} "
                f"(task {existing['task_id']}); confirm release before regranting")
    connection.execute(
        """INSERT INTO fleet_segment_grants
           (segment_id, state, task_id, attempt_id, robot_id, map_revision,
            generation, entry_deadline, granted_at)
           VALUES (?, 'RESERVED', ?, ?, ?, ?, ?, ?, ?)""",
        (segment_id, task_id, attempt_id, robot_id, map_revision,
         int(generation), entry_deadline, now),
    )
    return OK


def verify_grant(connection: sqlite3.Connection, *, segment_id: str, task_id: str,
                 attempt_id: str, robot_id: str, map_revision: str, generation: int,
                 now: str) -> str:
    """수락 측 검증 — 일치·만료·세대를 여기서도 검사한다(계획 T4 항목 5)."""
    _prepare(connection)
    row = _grant_row(connection, segment_id)
    if row is None:
        return f"{GRANT_REFUSED}: segment is FREE"
    if (row["task_id"] != task_id or row["attempt_id"] != attempt_id
            or row["robot_id"] != robot_id or row["map_revision"] != map_revision):
        return f"{GRANT_REFUSED}: grant binding mismatch"
    if row["generation"] != int(generation):
        return f"{GRANT_REFUSED}: dispatch generation changed"
    if _age_s(now, row["entry_deadline"]) > 0:
        return f"{GRANT_REFUSED}: grant expired (entry deadline was {row['entry_deadline']})"
    return OK


@atomic
def confirm_entry(connection: sqlite3.Connection, *, segment_id: str, task_id: str,
                  attempt_id: str, robot_id: str, map_revision: str, generation: int,
                  position, pose_trusted: bool, now: str) -> str:
    """RESERVED→OCCUPIED. 신뢰 위치가 구간 안일 때만, 만료는 경계에서 재검사."""
    _prepare(connection)
    row = _grant_row(connection, segment_id)
    if not _bound(row, task_id, attempt_id, robot_id, map_revision, generation):
        return f"{GRANT_REFUSED}: no matching grant"
    if row["state"] != "RESERVED":
        return f"{GRANT_REFUSED}: segment is {row['state']}, not RESERVED"
    if _age_s(now, row["entry_deadline"]) > 0:
        # 만료된 grant — 진입 경계에서 다시 검사해 밖에서 정지한다.
        return f"{GRANT_REFUSED}: grant expired before entry; stop outside the segment"
    if pose_trusted is not True or not _finite_point(position):
        return f"{GRANT_REFUSED}: position is not trusted (unconfirmed localization)"
    segment = _segment_row(connection, segment_id)
    if not _inside(segment, position):
        return f"{GRANT_REFUSED}: robot is not inside the segment footprint"
    connection.execute(
        "UPDATE fleet_segment_grants SET state='OCCUPIED', entry_confirmed_at=? "
        "WHERE segment_id=?",
        (now, segment_id))
    return OK


@atomic
def begin_release(connection: sqlite3.Connection, *, segment_id: str, task_id: str,
                  attempt_id: str, robot_id: str, map_revision: str, generation: int,
                  exit_position, pose_trusted: bool,
                  observed_at: str, terminal_status: str, now: str) -> str:
    """OCCUPIED→RELEASING. 신선한 출구 이탈 관측 + 종단 실행 결과 둘 다 필요."""
    _prepare(connection)
    row = _grant_row(connection, segment_id)
    if not _bound(row, task_id, attempt_id, robot_id, map_revision, generation):
        return f"{GRANT_REFUSED}: no matching grant"
    if row["state"] != "OCCUPIED":
        return f"{GRANT_REFUSED}: segment is {row['state']}, not OCCUPIED"
    if terminal_status not in _TERMINAL:
        return f"{GRANT_REFUSED}: execution is not terminal ({terminal_status})"
    if pose_trusted is not True or not _finite_point(exit_position):
        return f"{GRANT_REFUSED}: release needs a fresh trusted exit observation"
    if not _fresh_exit(row, observed_at, now):
        return f"{GRANT_REFUSED}: exit observation is stale or invalid"
    segment = _segment_row(connection, segment_id)
    if _inside(segment, exit_position):
        return f"{GRANT_REFUSED}: robot is still inside the segment"
    connection.execute(
        "UPDATE fleet_segment_grants SET state='RELEASING', exit_observed_at=?, "
        "terminal_status=? WHERE segment_id=?",
        (observed_at, terminal_status, segment_id))
    return OK


@atomic
def confirm_exit(connection: sqlite3.Connection, *, segment_id: str, task_id: str,
                 attempt_id: str, robot_id: str, map_revision: str, generation: int,
                 now: str) -> str:
    """RELEASING→FREE. 관측·종단 대조가 끝난 해제만 확인한다."""
    _prepare(connection)
    row = _grant_row(connection, segment_id)
    if not _bound(row, task_id, attempt_id, robot_id, map_revision, generation):
        return f"{GRANT_REFUSED}: no matching grant"
    if row["state"] != "RELEASING":
        return f"{GRANT_REFUSED}: segment is {row['state']}, not RELEASING"
    if row['terminal_status'] not in _TERMINAL or not _fresh_exit(row, row['exit_observed_at'], now):
        return f"{GRANT_REFUSED}: release evidence is stale or invalid"
    connection.execute("DELETE FROM fleet_segment_grants WHERE segment_id=?",
                       (segment_id,))
    return OK


@atomic
def mark_unknown(connection: sqlite3.Connection, *, segment_id: str, reason: str) -> str:
    """링크 상실 등 불명 — UNKNOWN은 FREE가 아니며 자동 해제도 하지 않는다."""
    _prepare(connection)
    row = _grant_row(connection, segment_id)
    if row is None:
        return f"{GRANT_REFUSED}: segment is FREE"
    connection.execute(
        "UPDATE fleet_segment_grants SET state='UNKNOWN' WHERE segment_id=?",
        (segment_id,))
    return OK


def waiting_seconds(connection: sqlite3.Connection, *, now: str) -> list[dict]:
    """RESERVED가 60 s 이상 진입하지 못하면 운영자 대조 대상으로 남긴다.

    대기자 목록을 따로 만들지 않는다 — 거부된 요청은 호출자(스케줄러)가 승인
    순서·robot ID로 다시 시도하고, 여기는 '누가 얼마나 대기점에 붙잡혀 있는가'만
    보고한다(자동 후반전·자동 양보 없음).
    """
    _prepare(connection)
    rows = connection.execute(
        "SELECT segment_id, task_id, robot_id, granted_at, entry_deadline "
        "FROM fleet_segment_grants WHERE state='RESERVED'").fetchall()
    flagged = []
    for row in rows:
        waited = _age_s(now, row["granted_at"])
        if waited > OPERATOR_ATTENTION_AFTER_S:
            flagged.append({"segment_id": row["segment_id"], "task_id": row["task_id"],
                            "robot_id": row["robot_id"], "waited_s": round(waited, 1),
                            "action": "operator comparison required"})
    return flagged
