# map_v2_fleet 길 찾기 실패의 단계별 진단

2026-10-12. 기준 소스 `1e2dc235576081c92014ee1d7465c8cd13905169`.
지도는 `map_v2_fleet` / `260919 MAP FILE.STL`의 curved 파생 자산을 유지한다.
이번 작업은 기존 D-676 실행과 D-708 관측 경로 기억의 후속 진단이다.

## 문제와 작업 경계

R29의 목표 소실, R31/R34의 관측 곡선 거절, R34/R35의 물리 정지 실패를 구분한다.
카메라에 보이는 곡선과 안전하게 채택할 수 있는 목표는 같은 증거가 아니다.
D-708은 독립 관측으로 확인한 형상을 짧은 공백 동안 유지하지만 최신
`drivable_closed` 거절을 덮지 않는다. 따라서 이를 완주 해결로 기록하지 않는다.

기존 helper와 topic을 재사용한다. 새 주행 API나 별도 최종 명령 publisher를 만들지 않는다.
CORE는 최종 명령을 소유하고 Fleet의 통행·회전 권한은 별도로 검증한다.

## 진단과 업데이트 구분

| 단계 | 입력과 직접 readback | 변경 대상 | 통과 기준 |
|---|---|---|---|
| 실행 환경 | source/map/model SHA, effective config, ROS domain, Gazebo partition, 자원 예약 | runner 또는 launch | 지정 소스·맵·모델이 실제 적재되고 타세션과 격리됨 |
| 관측 | RGB, class mask, ground, 원본 시각, source/current odom | Perception | 사용한 frame과 투영·기억의 시각을 함께 재현함 |
| 목표 채택 | centre polyline, 출구 후보, remembered edges, `exit_behind_line`, `ahead_m`, `target_now_m` | Drive 관측 추종 | 채택과 거절 모두 원래 경계 검사로 설명됨 |
| 경로 안내 | `line/lane_guide` publisher 수, 실제 메시지, Fleet route와 pose trust | 안내 배선 | subscriber 존재와 실제 publisher/message를 각각 확인함 |
| 최종 명령 | CORE mode/owner, body/scan/containment refusal, 최종 command와 실제 odom | CORE | 권한과 안전 게이트가 승인한 명령만 나감 |
| 물리 정지 | zero command, wheel/caster 속도, 연속 정지, reset와 cleanup | simulator actuator/contact | 기존 정지 기준을 그대로 만족함 |

수정은 실패한 단계의 경로에만 적용한다. mask replay, 원격 pytest, 실제 Gazebo,
Isaac SDK, CI, 장치·현장 수용은 별도 결과로 기록한다.

## 실행 순서

1. 저장된 frozen-model 실패 mask를 최신 소스에서 원격 재생한다. 기존 출구 원호와
   중심 목표 및 짧은 lookahead를 같은 `_crosses`로 비교한다. 새로운 추론 결과를
   과거 실시간 mask나 정답 라벨이라고 부르지 않는다.
2. 여유 있는 sim PC에서 최신 committed source의 별도 build/install/run을 만든다.
   먼저 정지 카메라·observer·CORE·Fleet를 연결하고 guide publisher와 관측을 수집한다.
   `--pick sim`은 자원 예약을 수행한다. 실행 전후 자신이 소유한 예약·PID를 확인한다.
3. 후보가 실제 관측 corridor와 기존 안전 검사에 적합하면 해당 반례를 회귀로 고정하고
   공유 알고리즘을 최소 변경한다. 경계 검사를 삭제하거나 닫힌 길을 기억으로 덮지 않는다.
4. 관련 원격 회귀와 독립 소스 리뷰 뒤 같은 source/model/map에서 제한된 주행을 비교한다.
   실패한 단계, 진행 거리, 목표 채택, 최종 정지·cleanup을 함께 기록한다.

## 최초 확인

- 기준 소스는 main에 착지·원격 push 완료. 추가 pre-push 원격 시험 291 PASS,
  착지 시험 6,130 PASS/359 SKIP/NEW 0이다. CI는 별도 확인한다.
- R34 저장 trace에는 `exit_behind_line=true`, `drivable_closed`, `ahead_m=0`,
  `target_now_m=null`이 있다. D-708은 이 최신 거절을 보존한다.
- 소스에서 `line/lane_guide` subscriber는 발견했으나 publisher를 발견하지 못했다.
  실행 graph 확인 전에는 publisher가 없다고 확정하지 않는다.
- AI PC의 기존 Gazebo 준비물은 과거 snapshot이다. 새 build와 관측 실행을 준비한다.
  준비 상태는 실제 실행·주행·완주 성공이 아니다.

## 후속 결과

- 최신 소스의 AI PC 단일 frame 재생에서 실패 66/77은 `drivable_closed`와
  `exit_behind_line=true`를 재현했다. 89는 이력 없이 `drivable_creep`이므로
  같은 실패를 재현했다고 기록하지 않는다. 세 mask의 SHA와 실제 imported source를 확인했다.
- 짧은 lookahead 일부가 `_crosses`를 통과했으나 그 검사는 목표 이전 중심 원호에 대한
  15mm 경계 교차 검사다. 몸체 폭 전체의 여유를 증명하지 않는다. 후보 일부는 최초
  관측 x보다 앞에 있고, 관측 범위의 후보도 보수적인 body+paint 여유 검사를 충족하지
  못했다. 따라서 짧은 목표를 바로 채택하는 fallback은 구현하지 않았다.
- AI PC Gazebo r2는 기준 소스 7,494 파일 hash를 확인하고 17 ROS package를 새로 빌드했다.
  두 CORE에서 각각 최종 명령 1,671/1,670개가 전부 zero, odom 정지,
  line/keep_debug 각각 268개를 관측했다. 현재 drivable centre와 live expected path가
  생성됐다. 두 `line/lane_guide`의 publisher 목록과 개수는 실제로 비어 있었다.
  현재 keep 모드에서 `lane_graph_path` 설정만으로 안내가 생성되지 않는다.
- r2 전체 runner는 Fleet의 `rosy.contracts.learning.incident_rule` import 실패로 exit 1이다.
  CORE 센서·정지 관측 성공과 Fleet 연결 실패를 구분한다. 종료 후 자기 partition의
  프로세스 부재, 세 포트의 연결 거절, 자기 lock 부재와 source hash 보존을 확인했다.
- 거절 trace가 admission 실패 전의 원인을 잃는 진단 누락을 보강했다. `camera_target`에
  reason·경계 거절·관측 중심 경로·near centre·벽 여유를 보존한다. 기존 zero 명령과
  admission은 유지한다. 원격 RED 3 FAIL 후 전체 Isaac 214 PASS/1 SKIP/NEW 0,
  독립 SOURCE APPROVE다. 최초 GREEN 전송의 SSH timeout은 시험 통과에 포함하지 않는다.

현재 길 찾기 해결·네 방향 완주·물리 정지 안정성은 미확인이다.
