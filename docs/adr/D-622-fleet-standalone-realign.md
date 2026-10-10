## D-622 Fleet 독립 주행 REALIGN은 명시한 지도 복구 영역 안에서만 고른다

**Status:** Accepted (2026-10-10, 사용자 병렬 구현 요청; SOURCE·원격 시험·설치·FIELD 별도)

### Decision

- D-607 CORE PIVOT/KTURN을 기존 막힘 답 경로로 연결한다. 새 명령 writer나 ROS 경로는 만들지 않는다.
- `fleet.stuck_resolver.realign_robots` 기본 빈 목록, `realign_areas` 기본 빈 목록이다. 각 영역은 `{map_revision, polygon:[[x,y],...]}`이며 유한 좌표의 엄격한 볼록 다각형이다. 실제 활성 지도 revision과 정확히 일치해야 한다. 운영자가 검증하지 않은 지도 빈 공간을 자동 영역으로 만들지 않는다.
- 활성 trip은 D-517 M4 그대로 정지 답만 받는다. 이 구현은 D-607 P5가 아니다. P5는 조작 전체 몸체+불확실성이 점유 블록 안에 머무는 증명, Gazebo, 별도 안전 검토가 필요하다.
- 기존 방향 재판단의 신선한 LOCALIZED 자세·anchor·동일 odom stamp/지도 표본을 재사용한다. 차로 방향 차이는 ±90도 이내의 유한 각이어야 한다. 지도 turn_spot이 확인되면 PIVOT, 그렇지 않으면 KTURN을 검토한다. 회전 방향은 검증된 도로 방향이 정하며 임의 좌우 순환을 만들지 않는다.
- 후보 전체 중심 궤적을 실제 CORE KTURN의 후진 호와 전진 호로 계산한다. nominal 몸체 회전 반경, SWEEP_PAD_M, 0.018m+odom 이동 드리프트 불확실성으로 넓힌 원을 복구 영역의 모든 변 안에 포함시킨다. 표본 사이 이동량의 보수적 여유를 더하여 연속 궤적을 제한한다. CORE 실제 매 tick 장애물·IR·뒤 공간·횡단보도 재확인은 유지한다.
- 오래된 열림 사건을 현재 공간으로 취급하지 않는다. inquiry의 scan 나이에 사건 후 경과를 더해 0.3초 이내여야 한다. KTURN은 해당 증거의 rear_state clear와 rear_clearance_m>0.06을 함께 요구한다. 앞 초음파는 뒤 공간 근거가 아니다.
- 온라인 동료의 신선한 동일 지도 자세가 없거나 전체 후보 궤적+동료 몸체+0.30m 안에 있으면 정지/사람이다. 횡단보도·AI 정지 사실·권한·상한을 유지한다.
- 같은 막힘 조작은 최대 두 번, 모호한 이동 응답은 재전송하지 않고 사람에게 넘긴다. CORE의 실제 허용 결정에 REALIGN이 있어야 한다.

### Verification

원격 TDD로 selector→Answer→loop→HTTP payload를 검증한다. 기본 꺼짐, 지도/표본 불일치, stale/NaN, trip, 동료 미확인, 경계 침범, 후진 미확인, ±90도 초과, 응답 유실을 확인한다. 소스 통과는 설치·실제 탈출·한 바퀴 완주 증거가 아니다.

**Related:** D-607, D-453, D-620, D-517, D-430.
