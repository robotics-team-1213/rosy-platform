# Isaac 실제 맵 강화학습 진행 기록

## 목표와 통과 기준

현재 목표는 기존 CORE·Drive 로직으로 Pinky **한 대**의 회전 보정을 학습하고, 고정 정책의 독립 시드 두 개에서 실제 맵 경로를 순서대로 완주한 뒤 물리적으로 정지시키는 것이다. 사용자는 한 대의 odom·거리·경로 지시부터 시작하는 방식을 선택했다. 이후 두 대 Fleet와 횡단보도 신호 준수를 확장한다. 한 대의 성공으로 두 대 또는 실물 수용을 선언하지 않는다.

완주 판정은 출발점과의 거리만 보지 않는다. east→ring_e→ring_n→ring_w→west→ring_w→ring_s→ring_e를 순서대로 통과해야 한다. 실제 속도 `|v|<0.005 m/s`, `|w|<0.02 rad/s`가 0.3초 이어져야 종료한다. 벽 겹침·경로 이탈·pose jump·무효 관측·정책 envelope HOLD는 실패이며, 시간 제한만 truncation이다. 평가 중 reset과 Q 값 변경은 금한다.

학습 성공에는 Q 값의 실제 변화, 고정 산출물 해시, 학습한 상태에서의 실제 주행 후보 적용, 독립 평가 완주, cleanup 정지와 SDK exit 0이 모두 필요하다. 임시 규칙 제어기의 완주나 단순 업데이트 횟수는 학습 성공을 대신하지 않는다.

## 구현·증거 범위

- 기준 main 병합 commit `f821d27dc5de57c55c81c122d0303f6cff4dd7ae`; 착지 449 passed, 1 skipped, 0 NEW. push 없음.
- 실행 브랜치: `feat/isaac-map-rl`. 최신 main 포함 여부를 검사한다.
- 지도 원본: `map_v2_fleet/260919 MAP FILE.STL`, SHA-256 `cabf17a84175da8be1ef7562054ec598971bbb9378810acb8cee3f686fe1f92b`.
- 변형은 기존 `training_scene`과 `training-curved/lane_graph.yaml`을 함께 사용한다. S자 변형·흰색 0.30m 충돌 벽·시각 전용 차선을 보존한다.
- 기존 Drive `control.control.path_follow.PathFollower` → CPU residual Q-learning의 회전 보정 → private simulation owner의 POLICY 검사 → 기존 CORE NAVIGATION 슬롯 → `cmd_vel_cycle` 최종 port → Isaac wheel action.
- 실제 ROS publisher·로봇 API·운영 Fleet 연결 없음. CORE 운영 소스와 실물 20cm BoundedTrial은 수정하지 않았다. D-638 진단이며 D-606 Isaac Lab·운영 readiness는 HOLD다.
- 원시 파일은 관리된 X: 세션의 `logs/evidence`와 모델 PC의 이 작업 전용 scratch에 보존한다. 공개 문서에 장비 주소·토큰을 넣지 않는다.

## 1. 계약 검사와 독립 검토

처음에는 구현 없는 환경 검사를 먼저 커밋하고 원격으로 실행했다. `map_task` ImportError로 실패하는 RED를 확인한 다음 구현했다. 첫 GREEN은 20 passed였다.

독립 검토에서 POLICY 유효기간 0.1초와 기존 NAV 슬롯 0.5초의 차이를 발견했다. 최종 `select_output`에서도 POLICY 만료·관측 freshness·episode epoch를 검사하고 실패하면 슬롯 삭제와 0으로 처리했다. 음수·bool·비유한 시각도 기존 후보가 남지 않도록 거부한다. reset 전 실측 정지와 평가 중 정책 불변성은 runner에서 검사한다. cleanup 성공/실패와 SDK shutdown 결과도 최종 result에 기록한다.

관련 원격 회귀: 143 passed, 1 skipped, 0 NEW. 이후 ADR/harness를 포함한 회귀는 `51d77f23fb`에서 241 passed, 1 skipped, 0 NEW다. 이 검사들은 Isaac의 실제 완주 증거가 아니다.

## 2. 자원 검사에서 시작 거부

첫 native 실행은 SDK를 시작하기 전에 가용 RAM 5.7GB로 6GB 검사에 막혔다. Ollama는 inactive이고 GPU compute 작업은 없었다. ZFS ARC가 약 6.2GB를 사용하며 `zfs_arc_max=0`이었다. 즉 D-434의 4GB ARC 제한은 실제로 적용되지 않았다. 비대화식 sudo 권한이 없어 제한 변경은 적용하지 못했다.

ROS 서버·센서 없는 진단의 별도 실행은 MemoryMax 4GiB, MemorySwapMax 2GiB, 호스트 여유 1GiB의 시작 조건으로 제한했다. 이후 ZFS 캐시가 압력에 따라 회수되어 가용 RAM 약 9GB가 확인됐고 다음 실행부터 원래 6GB 검사를 사용했다. 이 현상은 RAM 증설이나 영구 ARC 설정 완료를 뜻하지 않는다. swap은 물리 RAM 최소 기준을 대신하지 않는다.

## 3. Isaac 5.1 바닥 API 불일치

실행 source commit `e8dba4892eb8b50dd10ab88e71274ab9ea38e750`의 6,993개 파일 해시를 실행 전후 확인했다. native SDK는 시작했지만 `Scene.add_default_ground_plane(color=...)`가 `TypeError`로 실패했고 SDK exit 1이었다. 학습·이동 성공은 없었다.

설치된 SDK의 정의를 읽어 `add_default_ground_plane`에는 color 인자가 없고 `add_ground_plane`에는 있음을 확인했다. 외부 기본 바닥 asset을 요구하지 않는 `add_ground_plane(size=10., color=...)`로 변경했다. 추정에 의한 SDK 버전 교체는 하지 않았다.

## 4. 기존 Drive 추종기 사용으로 수정

사용자가 '우리 로직으로 강화학습'을 다시 확인했다. CORE 최종 명령 처리는 이미 재사용했지만 초기 경로 후보 계산은 임시 추종식이었다. 기존 Drive는 heading error 0.3rad 초과에서 전진을 0으로 만들어 먼저 정렬한다. 새 RED 검사에서 임시 식은 0.04m/s를 유지해 실패했다.

임시 계산을 지우고 기존 `PathFollower.update`와 `pursuit_index`를 직접 사용했다. 닫힌 경로의 시작점에서 잘못 arrived가 되지 않도록 지도 진행 순서에 따른 국소 경로를 공급한다. CORE와 Drive 운영 구현은 변경하지 않았다. `6bc91f8e36` 원격 검사: 50 passed, 8 subtests passed, 0 NEW.

## 5. 첫 물리 정지 실패 — 조사 중

commit `6bc91f8e36caabe43ec2bb603530d79d760d3740`에서 실제 지도·차선·벽·로봇을 불러왔지만 최초 2초 정지 확인이 실패했다. stop을 확인하지 못했으므로 reset과 학습은 시작하지 않았고 exit 1로 끝났다.

원인을 찾기 위해 commit `253e60bfa8279d3d0f5ccb960c4351975eb136e6`에서 매 물리 step의 차체 pose/속도, 높이, joint 속도를 저장했다. 최초 실패 마지막 관측은 sim time 2.0333초, v=0.0049663m/s, w=0.0696117rad/s, z=0.00000249m다. joint 속도는 약 `[0.731, -0.795, -0.230, 0.439] rad/s`로 0 명령에도 접촉 진동이 남았다. 값 하나만 보고 정지 기준을 넓히지 않는다.

현재 가설: 새 바닥 API의 기본 restitution 0.8과 초기 접촉·solver가 기존 바닥 runner와 다른 진동을 만들 수 있다. 아직 확인된 원인이 아니다. 다음 검사는 전체 정지 trace의 실제 pose 변화·차체 속도·wheel targets를 비교하고, 기존 바닥의 material/physics 설정을 확인한 뒤 한 변수씩 수정한다.

R3 종료 확인: 최초와 cleanup 정지 모두 실패했고 SDK exit 1이다. 마지막 30step의 평균 절대 angular velocity는 약 0.071rad/s지만 pose 차분의 평균 절대 yaw rate는 약 0.0093rad/s였다. pose 이동이 작다고 정지 판정을 통과시키지 않는다. 초기 접촉에 따른 solver 속도와 pose 변화가 다르게 나타나는 이유를 조사한다. 기존 default restitution 0.8 대신 0으로 한 변수만 바꾼 R4를 실행해 비교한다. 형상·질량·휠 gain·정지 기준은 그대로 유지한다.

## 다음 단계

1. 최초 정지 실패 원인을 확인하고 동일 기준으로 재시험한다.
2. 기존 Drive의 전체 지도 baseline을 실제 궤적으로 검사한다.
3. 짧은 지도 구간에서 CPU Q-learning을 수행하고 Q 변화·학습 궤적을 보존한다.
4. 정책을 고정한 독립 시드 두 개에서 전체 경로·벽·정지를 검사한다.
5. exit·cleanup·소스 해시·자원과 함께 결과를 판정한다. 두 대 Fleet와 신호·카메라·실물 수용은 별도다.

## 2026-10-11 최종 판정

이 문서는 초기 R1~R3 진행 스냅샷이다. 이후 날짜별 문제·원인/가설·수정·재시험의 정본은 Git 제외 경로 `private/isaac/journal/2026-10-11-map-rl.md`다. 계획·결과·다음 일지 양식도 `private/isaac/`로 분리했다. 공개 검증 요약은 [최종 결과](result.md)를 따른다.

R6 한 대 native CPU 학습과 고정 정책 두 시드의 ordered-map 완주·물리 정지는 통과했다. R6의 비동기 GUI 종료 traceback은 R7의 공통 headless-close 수리와 별도 SDK 생명주기 검사로 확인했다. 두 실행의 source SHA와 증거를 혼합하지 않는다. 운영 ROS-SIM·두 대 Fleet·신호·실물은 이 진단으로 수용하지 않는다.
