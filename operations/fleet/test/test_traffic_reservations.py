"""D-426 Task 4 — 공유 구간 진입 허가·점유 계약. 실패 시험이 먼저다(규칙 5).

판정(계획 T4 항목 2·3·6·7):
- 구간 상태: FREE(행 없)→RESERVED→OCCUPIED→RELEASING→FREE, 불명 UNKNOWN
- Fleet만 기록 writer — 같은 Task DB 트랜잭션 안에서 돈다
- 동시 진입 거부, 빈/못난 식별자·다른 map revision 거부
- 위치 미확정 상태로는 진입 확정 불가
- 허가 만료(expiry)는 실제 footprint 진입 시한 — 만료 뒤 진입 시도는 경계에서 재검사
- 시간 만료·링크 상실만으로 구간이 FREE가 되지 않는다(UNKNOWN도 FREE 아님)
- RESERVED는 이전 실행이 구간 밖에서 비활성·정지했음을 확인하기 전 재할당 금지
- 해제(RELEASING→FREE)는 신선한 출구 이탈 관측 + 종단 실행 결과 대조
- grant는 Task/attempt·robot·구간·지도 revision·만료·dispatch generation에 결속,
  수락 측(verify_grant)에서도 일치·만료·세대를 검증
- 우선순위는 승인 순서·robot ID로 안정, 60 s 초과 대기는 운영자 대조 대상으로 남는다
"""

from __future__ import annotations

import pytest

from fleet.server.traffic_reservations import (
    GRANT_REFUSED,
    OK,
    begin_release,
    confirm_entry,
    confirm_exit,
    define_segments,
    mark_unknown,
    request,
    segment_state,
    verify_grant,
    waiting_seconds,
)

SEGMENT = {
    "segment_id": "corridor-north",
    "map_revision": "map-v3",
    "center": (0.0, 0.0),
    "radius_m": 0.5,
    "entry": (0.0, -0.6),
    "exit": (0.0, 0.6),
    "waiting_point": (0.0, -1.2),
}

INSIDE = (0.0, 0.0)
OUTSIDE = (0.0, 3.0)


@pytest.mark.parametrize('position,observed', [
    (OUTSIDE, '2026-01-01T01:02:00Z'),
    ((float('nan'), 0), '2026-01-01T00:02:00Z'),
    ((float('inf'), 0), '2026-01-01T00:02:00Z'),
])
def test_release_rejects_future_or_nonfinite_observation(store, position, observed):
    assert _grant(store) == OK
    assert confirm_entry(store,
                         robot_id="rosy_01", map_revision="map-v3", generation=7,
                         segment_id='corridor-north', task_id='task-1',
                         attempt_id='att-1', position=INSIDE, pose_trusted=True,
                         now='2026-01-01T00:00:10Z') == OK
    result = begin_release(store,
                           robot_id="rosy_01", map_revision="map-v3", generation=7,
                           segment_id='corridor-north', task_id='task-1',
                           attempt_id='att-1', exit_position=position, pose_trusted=True,
                           observed_at=observed, terminal_status='COMPLETED',
                           now='2026-01-01T00:02:00Z')
    assert result.startswith(GRANT_REFUSED)
    assert segment_state(store, 'corridor-north') == 'OCCUPIED'


def test_exit_rechecks_age_before_freeing(store):
    assert _grant(store) == OK
    assert confirm_entry(store,
                         robot_id="rosy_01", map_revision="map-v3", generation=7,
                         segment_id='corridor-north', task_id='task-1',
                         attempt_id='att-1', position=INSIDE, pose_trusted=True,
                         now='2026-01-01T00:00:10Z') == OK
    assert begin_release(store,
                         robot_id="rosy_01", map_revision="map-v3", generation=7,
                         segment_id='corridor-north', task_id='task-1',
                         attempt_id='att-1', exit_position=OUTSIDE, pose_trusted=True,
                         observed_at='2026-01-01T00:02:00Z', terminal_status='COMPLETED',
                         now='2026-01-01T00:02:00Z') == OK
    result = confirm_exit(store,
                          attempt_id="att-1", robot_id="rosy_01", map_revision="map-v3", generation=7,
                          segment_id='corridor-north', task_id='task-1',
                          now='2026-01-02T00:02:00Z')
    assert result.startswith(GRANT_REFUSED)
    assert segment_state(store, 'corridor-north') == 'RELEASING'


@pytest.mark.parametrize('write', [False, True])
def test_helpers_preserve_caller_task_transaction(store, write):
    store.execute('CREATE TABLE audit(value TEXT)')
    store.commit()
    store.execute("INSERT INTO audit VALUES ('pending')")
    if write:
        assert _grant(store) == OK
    else:
        assert segment_state(store, 'corridor-north') == 'FREE'
    assert store.in_transaction
    store.rollback()
    assert store.execute('SELECT COUNT(*) FROM audit').fetchone()[0] == 0
    assert segment_state(store, 'corridor-north') == 'FREE'


@pytest.mark.parametrize('stage', ['entry', 'release', 'exit'])
@pytest.mark.parametrize('field,value', [
    ('task_id', 'other-task'), ('attempt_id', 'other-attempt'),
    ('robot_id', 'other-robot'), ('map_revision', 'other-map'), ('generation', 8),
])
def test_state_transition_requires_the_complete_current_binding(store, stage, field, value):
    binding = dict(segment_id='corridor-north', task_id='task-1', attempt_id='att-1',
                   robot_id='rosy_01', map_revision='map-v3', generation=7)
    assert _grant(store) == OK
    if stage != 'entry':
        assert confirm_entry(store, **binding, position=INSIDE, pose_trusted=True,
                             now='2026-01-01T00:00:10Z') == OK
    if stage == 'exit':
        assert begin_release(store, **binding, exit_position=OUTSIDE, pose_trusted=True,
                             observed_at='2026-01-01T00:02:00Z', terminal_status='COMPLETED',
                             now='2026-01-01T00:02:00Z') == OK
    original = segment_state(store, 'corridor-north')
    binding[field] = value
    if stage == 'entry':
        result = confirm_entry(store, **binding, position=INSIDE, pose_trusted=True,
                               now='2026-01-01T00:00:10Z')
    elif stage == 'release':
        result = begin_release(store, **binding, exit_position=OUTSIDE, pose_trusted=True,
                               observed_at='2026-01-01T00:02:00Z', terminal_status='COMPLETED',
                               now='2026-01-01T00:02:00Z')
    else:
        result = confirm_exit(store, **binding, now='2026-01-01T00:02:01Z')
    assert result.startswith(GRANT_REFUSED)
    assert segment_state(store, 'corridor-north') == original


@pytest.mark.parametrize('observed,now', [
    ('not-a-time', '2026-01-01T00:02:00Z'),
    ('2026-01-01T00:02:00', '2026-01-01T00:02:00Z'),
    ('2026-01-01T00:00:09Z', '2026-01-01T00:00:10Z'),
    ('2026-01-01T00:02:00Z', 'invalid-now'),
])
def test_release_time_must_be_aware_and_after_entry(store, observed, now):
    binding = dict(segment_id='corridor-north', task_id='task-1', attempt_id='att-1',
                   robot_id='rosy_01', map_revision='map-v3', generation=7)
    assert _grant(store) == OK
    assert confirm_entry(store, **binding, position=INSIDE, pose_trusted=True,
                         now='2026-01-01T00:00:10Z') == OK
    result = begin_release(store, **binding, exit_position=OUTSIDE, pose_trusted=True,
                           observed_at=observed, terminal_status='COMPLETED', now=now)
    assert result.startswith(GRANT_REFUSED)
    assert segment_state(store, 'corridor-north') == 'OCCUPIED'


def test_active_segment_cannot_be_retargeted(store):
    assert _grant(store) == OK
    with pytest.raises(ValueError, match='immutable'):
        define_segments(store, [{**SEGMENT, 'center': (50, 50)}])
    row = store.execute('SELECT center_x,center_y FROM fleet_segments').fetchone()
    assert tuple(row) == (0, 0)
    assert segment_state(store, 'corridor-north') == 'RESERVED'


@pytest.mark.parametrize('field,value', [
    ('radius_m', float('nan')), ('radius_m', float('inf')),
    ('center', (float('nan'), 0)), ('exit', (0, float('inf'))),
])
def test_geometry_definition_must_be_finite(store, field, value):
    with pytest.raises(ValueError):
        define_segments(store, [{**SEGMENT, field: value}])
    row = store.execute('SELECT center_x,center_y,radius_m FROM fleet_segments').fetchone()
    assert tuple(row) == (0, 0, 0.5)


def test_failed_batch_rolls_back_only_its_owned_changes(store):
    store.execute('CREATE TABLE audit(value TEXT)')
    store.commit()
    store.execute("INSERT INTO audit VALUES ('pending')")
    with pytest.raises(ValueError):
        define_segments(store, [{**SEGMENT, 'segment_id': 'new'},
                                {**SEGMENT, 'radius_m': float('nan')}])
    assert store.in_transaction
    assert store.execute('SELECT COUNT(*) FROM audit').fetchone()[0] == 1
    assert store.execute("SELECT COUNT(*) FROM fleet_segments WHERE segment_id='new'").fetchone()[0] == 0
    store.rollback()
    assert store.execute('SELECT COUNT(*) FROM audit').fetchone()[0] == 0


@pytest.fixture
def store(tmp_path):
    import sqlite3

    from fleet.server.sqlite_policy import configure_connection, enable_wal

    path = tmp_path / "fleet.sqlite3"
    connection = sqlite3.connect(str(path), check_same_thread=False)
    configure_connection(connection)
    enable_wal(connection)
    define_segments(connection, [SEGMENT])
    yield connection
    connection.close()


def _grant(connection, robot="rosy_01", attempt="att-1", generation=7,
           deadline="2099-01-01T00:00:00Z", segment="corridor-north",
           revision="map-v3", task="task-1"):
    return request(connection, segment_id=segment, task_id=task, attempt_id=attempt,
                   robot_id=robot, map_revision=revision, generation=generation,
                   entry_deadline=deadline, now="2026-01-01T00:00:00Z")


def test_concurrent_entry_is_refused_until_release(store):
    assert _grant(store) == OK
    assert segment_state(store, "corridor-north") == "RESERVED"
    second = _grant(store, robot="rosy_02", attempt="att-2", task="task-2")
    assert second.startswith(GRANT_REFUSED)
    assert segment_state(store, "corridor-north") == "RESERVED"


def test_bad_identifiers_and_map_revisions_are_refused(store):
    for bad_segment in ("", "   ", "no-such-segment"):
        result = _grant(store, segment=bad_segment)
        assert result.startswith(GRANT_REFUSED), bad_segment
    assert _grant(store, revision="map-v2").startswith(GRANT_REFUSED)


def test_entry_needs_a_trusted_position_inside_the_segment(store):
    assert _grant(store) == OK
    untrusted = confirm_entry(store,
                              robot_id="rosy_01", map_revision="map-v3", generation=7,
                              segment_id="corridor-north", task_id="task-1",
                              attempt_id="att-1", position=INSIDE, pose_trusted=False,
                              now="2026-01-01T00:01:00Z")
    assert untrusted.startswith(GRANT_REFUSED)
    outside = confirm_entry(store,
                            robot_id="rosy_01", map_revision="map-v3", generation=7,
                            segment_id="corridor-north", task_id="task-1",
                            attempt_id="att-1", position=OUTSIDE, pose_trusted=True,
                            now="2026-01-01T00:01:00Z")
    assert outside.startswith(GRANT_REFUSED)
    assert segment_state(store, "corridor-north") == "RESERVED"


def test_entry_past_the_deadline_is_rejected_and_stays_outside(store):
    assert _grant(store, deadline="2026-01-01T00:00:30Z") == OK
    late = confirm_entry(store,
                         robot_id="rosy_01", map_revision="map-v3", generation=7,
                         segment_id="corridor-north", task_id="task-1",
                         attempt_id="att-1", position=INSIDE, pose_trusted=True,
                         now="2026-01-01T00:05:00Z")   # 진입 시한 4.5 분 초과
    assert late.startswith(GRANT_REFUSED)
    assert "expired" in late
    assert segment_state(store, "corridor-north") == "RESERVED"


def test_time_expiry_and_link_loss_never_free_a_segment(store):
    assert _grant(store) == OK
    mark_unknown(store, segment_id="corridor-north", reason="hub link lost")
    assert segment_state(store, "corridor-north") == "UNKNOWN"
    # 링크 상실 뒤에도 새 진입은 거부 — UNKNOWN은 FREE가 아니다.
    assert _grant(store, robot="rosy_02", attempt="att-2", task="task-2").startswith(GRANT_REFUSED)


def test_reserved_segment_is_not_reassigned_after_deadline_alone(store):
    assert _grant(store, deadline="2026-01-01T00:00:30Z") == OK
    # 시한이 훌쩍 지났다 — 이전 실행이 밖에서 비활성·정지했음을 확인하기 전 재할당 금지.
    later = _grant(store, robot="rosy_02", attempt="att-2", task="task-2")
    assert later.startswith(GRANT_REFUSED)


def test_release_needs_fresh_exit_observation_and_terminal_result(store):
    assert _grant(store) == OK
    assert confirm_entry(store,
                         robot_id="rosy_01", map_revision="map-v3", generation=7,
                         segment_id="corridor-north", task_id="task-1",
                         attempt_id="att-1", position=INSIDE, pose_trusted=True,
                         now="2026-01-01T00:00:10Z") == OK
    assert segment_state(store, "corridor-north") == "OCCUPIED"
    # 관측 없는 해제 요청 — 거부
    only_result = begin_release(store,
                                robot_id="rosy_01", map_revision="map-v3", generation=7,
                                segment_id="corridor-north", task_id="task-1",
                                attempt_id="att-1", exit_position=None, pose_trusted=False,
                                observed_at="2026-01-01T00:02:00Z",
                                terminal_status="COMPLETED", now="2026-01-01T00:02:00Z")
    assert only_result.startswith(GRANT_REFUSED)
    # 관측만 있고 실행 미종단 — 거부
    only_exit = begin_release(store,
                              robot_id="rosy_01", map_revision="map-v3", generation=7,
                              segment_id="corridor-north", task_id="task-1",
                              attempt_id="att-1", exit_position=OUTSIDE, pose_trusted=True,
                              observed_at="2026-01-01T00:02:00Z",
                              terminal_status="RUNNING", now="2026-01-01T00:02:00Z")
    assert only_exit.startswith(GRANT_REFUSED)
    # 낡은 관측(빈 구간) — 거부
    stale = begin_release(store,
                          robot_id="rosy_01", map_revision="map-v3", generation=7,
                          segment_id="corridor-north", task_id="task-1",
                          attempt_id="att-1", exit_position=OUTSIDE, pose_trusted=True,
                          observed_at="2026-01-01T00:00:05Z",
                          terminal_status="COMPLETED", now="2026-01-01T00:05:00Z")
    assert stale.startswith(GRANT_REFUSED)
    assert segment_state(store, "corridor-north") == "OCCUPIED"
    # 둘 다 신선 — RELEASING, 이어 출구 확인으로 FREE
    assert begin_release(store,
                         robot_id="rosy_01", map_revision="map-v3", generation=7,
                         segment_id="corridor-north", task_id="task-1",
                         attempt_id="att-1", exit_position=OUTSIDE, pose_trusted=True,
                         observed_at="2026-01-01T00:02:00Z",
                         terminal_status="COMPLETED", now="2026-01-01T00:02:00Z") == OK
    assert segment_state(store, "corridor-north") == "RELEASING"
    assert confirm_exit(store,
                        attempt_id="att-1", robot_id="rosy_01", map_revision="map-v3", generation=7,
                        segment_id="corridor-north", task_id="task-1",
                        now="2026-01-01T00:02:01Z") == OK
    assert segment_state(store, "corridor-north") == "FREE"
    assert _grant(store, robot="rosy_02", attempt="att-2", task="task-2") == OK


def test_verify_grant_checks_binding_and_expiry(store):
    assert _grant(store) == OK
    assert verify_grant(store, segment_id="corridor-north", task_id="task-1",
                        attempt_id="att-1", robot_id="rosy_01", map_revision="map-v3",
                        generation=7, now="2026-01-01T00:00:10Z") == OK
    assert verify_grant(store, segment_id="corridor-north", task_id="task-1",
                        attempt_id="att-OTHER", robot_id="rosy_01", map_revision="map-v3",
                        generation=7, now="2026-01-01T00:00:10Z").startswith(GRANT_REFUSED)
    assert verify_grant(store, segment_id="corridor-north", task_id="task-1",
                        attempt_id="att-1", robot_id="rosy_01", map_revision="map-v3",
                        generation=8, now="2026-01-01T00:00:10Z").startswith(GRANT_REFUSED)
    expired = verify_grant(store, segment_id="corridor-north", task_id="task-1",
                           attempt_id="att-1", robot_id="rosy_01", map_revision="map-v3",
                           generation=7, now="2100-01-01T00:00:00Z")  # 마감 2099 이후
    assert expired.startswith(GRANT_REFUSED) and "expired" in expired


def test_grants_survive_a_fleet_restart(tmp_path):
    import sqlite3

    from fleet.server.sqlite_policy import configure_connection, enable_wal
    from fleet.server.task_store import FleetTaskStore

    path = tmp_path / "fleet.sqlite3"
    FleetTaskStore(path)          # 같은 DB 에 Task store 스키마
    first = sqlite3.connect(str(path), check_same_thread=False)
    configure_connection(first)
    define_segments(first, [SEGMENT])
    assert _grant(first) == OK
    first.close()

    reopened = sqlite3.connect(str(path), check_same_thread=False)
    configure_connection(reopened)
    enable_wal(reopened)
    assert segment_state(reopened, "corridor-north") == "RESERVED"
    assert _grant(reopened, robot="rosy_02", attempt="att-2",
                  task="task-2").startswith(GRANT_REFUSED)
    reopened.close()


def test_waiting_time_is_stable_and_flags_operator_attention(store):
    assert _grant(store, robot="rosy_02", attempt="att-2", task="task-2") == OK
    assert _grant(store, robot="rosy_03", attempt="att-3", task="task-3").startswith(GRANT_REFUSED)
    # 2분째 RESERVED — 대기점에 붙잡혀 있으니 운영자 대조 대상으로 보고된다.
    waited = waiting_seconds(store, now="2026-01-01T00:02:00Z")
    assert [row["robot_id"] for row in waited] == ["rosy_02"]
    assert waited[0]["waited_s"] == 120.0
    assert waited[0]["action"] == "operator comparison required"
    # 짧은 대기는 보고하지 않는다.
    assert waiting_seconds(store, now="2026-01-01T00:00:30Z") == []
    # 소유자가 RELEASING 을 마치면 다음 대기자가 들어온다 — 승인 순서·robot ID 안정은
    # 호출자(스케줄러)가 request 재시도 순서로 지킨다.
    assert confirm_entry(store,
                         robot_id="rosy_02", map_revision="map-v3", generation=7,
                         segment_id="corridor-north", task_id="task-2",
                         attempt_id="att-2", position=INSIDE, pose_trusted=True,
                         now="2026-01-01T00:00:10Z") == OK
    assert begin_release(store,
                         robot_id="rosy_02", map_revision="map-v3", generation=7,
                         segment_id="corridor-north", task_id="task-2",
                         attempt_id="att-2", exit_position=OUTSIDE, pose_trusted=True,
                         observed_at="2026-01-01T00:01:00Z",
                         terminal_status="COMPLETED", now="2026-01-01T00:01:00Z") == OK
    assert confirm_exit(store,
                        attempt_id="att-2", robot_id="rosy_02", map_revision="map-v3", generation=7,
                        segment_id="corridor-north", task_id="task-2",
                        now="2026-01-01T00:01:01Z") == OK
    assert _grant(store, robot="rosy_03", attempt="att-3", task="task-3") == OK
