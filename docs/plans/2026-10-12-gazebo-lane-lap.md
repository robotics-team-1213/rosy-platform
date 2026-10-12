# Gazebo CORE 차선추종 지도 완주

2026-10-12. 작업 브랜치 `fix/gazebo-map-lap`.

## 목표와 범위

`map_v2_fleet` / `260919 MAP FILE.STL` 계보를 보존하고 실제 CORE 차선추종과
Fleet 유한 trip으로 지도 경로를 완주한다. 사용자는 Gazebo부터 진행하고 실물 감독은
추후 확정하기로 했다. 실물 주행은 현재 실행 범위에서 제외한다.

이전 R8은 0.179107m 전진·취소·권한 해제·정지를 확인했지만 목표 소실과 기억 경로를
사용하지 않았다. 완주 증거로 대체하지 않는다. 시작 기준 소스는 commit `2e29bd118`이며
후속 후보마다 전체 source·model·map·effective profile과 실제 import/install 경로를 고정한다.
수정 전 CORE와 새 helper를 섞은 이전 구성 대신 하나의 committed snapshot을 빌드한다.

## 완료 기준

1. 선택한 로봇 한 대가 실제 Fleet 계획의 유한 경로를 실행한다. 먼저 목적지 한 구간을
   완료한 뒤 서쪽·동쪽 도로를 포함해 출발 장소로 복귀하는 1회 경로를 검증한다.
   기존 이름 있는 장소와 `via`·`repeat:false` 계약을 사용하고 생성 그래프를 손으로 고치지 않는다.
2. 카메라 관측·현재 목표·기억 경로·CORE cue·typed route context·Fleet 통행권과 실제
   최종 명령 및 odom을 같은 실행에서 기록한다. 경로 진행과 도착을 독립 Gazebo 자세와
   대조하고 실제 차체의 차선 경계·충돌 여부를 검증한다. 관측 없는 구간은 정상으로 채우지 않는다.
3. trip terminal `arrived`, 실제 출발 장소 복귀, lease 해제, CORE OFF와 마지막 명령 zero,
   기존 기준의 실제 연속 정지를 확인한다. API 성공이나 누적 거리만으로 완주를 선언하지 않는다.
4. 같은 후보의 새 초기화 실행에서 재확인한다. 실패한 실행과 변경 전 결과를 보존하고
   후보의 회귀·독립 리뷰·착지·push·CI를 구분해 기록한다.

## 반복 순서와 중단 조건

- 정규 sim 자원 gate를 통과한 격리 host/domain/partition/port에서 실행한다.
  다른 세션의 프로세스·예약·소스를 변경하지 않는다.
- 첫 구간은 실제 계획 길이를 기록하고 sim 180s·wall 300s·계획 길이와 명시한 거리 여유로
  실행을 제한한다. 거절·센서 소실·권한 소실·충돌·실제 경계 이탈에서는 즉시 정지를 요청한다.
  odom 기반 watchdog은 HTTP 응답을 기다리지 않는다. 정지 요청 거리와 최종 총거리를 나눠 기록한다.
- 실패 단계별로 runner, Perception, 목표 추출, 경로 안내, Fleet, CORE, actuator를 구분한다.
  단일 원인 가설을 재생과 실패 회귀로 고정하고 공유 로직에서 최소 수정한다.
- 현재 유효한 센서·몸체·차선·통행권 검사를 유지한다. 통과를 위해 가짜 floor 값,
  현장 walker 선언, 능력 강제 광고, E-Stop 해제 또는 별도 최종 명령 publisher를 만들지 않는다.
- 목표 소실은 직선·곡선의 current/source odom 변환과 시간·거리 예산, 새 충돌 관측의
  중단을 비교한다. 지속 전진을 위해 오래된 명령을 재사용하지 않는다.
- `speed_cap`은 현행 Fleet 계획 비용·ETA에만 쓰인다. 실행 속도는 실제 CORE profile과
  최종 명령으로 검증한다. 계획값을 실행 한도라고 주장하지 않는다.

## 증거 상태

최신 전체 소스의 첫 목적지 실행은 실패했고 안전 종료를 확인했다. commit `2e29bd118`의
7,503개 파일과 17개 ROS 패키지를 새로 빌드한 뒤 CORE02→SW 2.8649m 구간을 실행했다.
최종 이동은 0.210783m, 중심 옆거리 약 10mm, 차로 접선 대비 방향 오차는 약 +47.45°였다.
Fleet은 초기 operator pin의 `anchor_age_s=10.244`가 기존 10초 상한을 넘어 정지했다.
처음 원인으로 읽었던 `out_of_order=1`은 부수 진단이며 직접 DEGRADED 원인이 아니었다.
native odom 922개 시각은 증가했고 기억 경로가 3프레임 사용됐다. 이후 pivot·off_line·
drivable_closed를 관측했다. trip은 stopped, arrived=false다. lease 해제·OFF·실제 연속
정지·자기 프로세스/포트/lock 종료와 원래 source hash 보존을 확인했다.

독립 리뷰에서 관측의 기본 역산법칙(.08m/s, gain .8)과 실제 Pinky CORE 법칙(.10m/s,
gain 2.0)을 조합하면 명령 곡률이 목표의 두 배가 됨을 확인했다. 현재·creep·기억 경로와
Isaac 소비자가 실제 CORE 설정으로 같은 역산법칙을 사용하도록 수정 중이다. commit
`45e92d326`의 원격 수학·기억 경로·잘못된 설정 회귀 28 PASS, 기존 관측 회귀 83 PASS,
Isaac camera 회귀 82 PASS다. 각 known_failures 결과는 NEW 0이다. native camera와
CORE의 HOME 차이에 따른 운영자 설정 전달은 안전한 기존 status-inputs handover로
별도 구현·검토하며, 이 전달이 끝나기 전에 제품 전체 수정 완료로 선언하지 않는다.

긴 Fleet trip에는 지속적으로 유효한 지도 자세가 필요하다. 실제 overhead 영상·로봇 식별·
accepted Vision 공급은 현재 Gazebo 구성에 없다. 기존 `map_pose_port` 주입을 이용하는
명시적 SIM-only native-Gazebo 위치 adapter를 검토한다. 원본 좌표·sim stamp·wall receipt,
map/run/source/domain/partition/frame 결속과 epoch·freshness를 검증하며, authority에는
실제 CORE snapshot의 UTC odom stamp를 유지한다. trip·차로 감시·지도 자세 조회·교차로
판단은 같은 위치 provider를 사용하고 camera ingest·operator pin·teach·formation에는
SIM 위치를 자동 확장하지 않는다. 새 공개 pose 입력 API나 주기 pin, TTL 확대는 사용하지 않는다.

지도 완주와 새 후보의 실물 수용은 미확인이다.
