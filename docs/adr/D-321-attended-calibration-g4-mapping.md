## D-321 현장 보정과 G4 실측을 한 세션으로 모으고 지도 생성은 승인 뒤에 시작한다

**Status:** Accepted (2026-09-29, 설계 결정). 구현·서명 릴리스·장치 G4/G5
수용은 별도 HOLD.

## Context

D-314는 지면 G4를 한 작업자와 다섯 원시 시험으로 간소화했다. 현재 장치의
설치 릴리스에는 네이티브 `mapping_approval.py`와 원시 자료를 재검증하는
`rosy-navigation.service` 조건이 없다. PC의 임시 G4 스크립트는 연결이
끊긴 시도에서 명령 시각과 오도메트리 샘플을 얻지 못했고, 같은 PC의 원격
정지 확인도 불가능했다. 현장 전원 차단으로 세션을 중단했다. 세부 장치
주소와 원시 자료는 `X:\DevTemp`에만 둔다.

현 설치의 attended helper는 `/etc/rosy/runtime.env`에 `motor`와
`ROSY_IO_DRIVE_ENABLED=true`를 지속 저장한다. I/O unit은 다음 부팅에도
이 파일을 읽고 motor bringup이 torque를 켠다. 전원 차단만으로 다음 부팅이
no-drive로 돌아간다고 볼 수 없다.

Control에는 `RoundTrip`, `RotationTrial`, 보정 후보·독립 holdout,
적응형 속도 제한 계산이 이미 있다. 그러나
`StartupCalibrationNode`는 `calibration_sensing_only=false`일 때
`cmd_vel_raw` 발행자를 만들고, 네이티브 G4 schema v2의 다섯 정지 시험과
원시 파일을 생성하지 않는다. 보정 준비 상태를 곧바로 모터 또는 navigation
승인으로 해석할 수 없다.

## Decision

1. 하나의 **현장 입회 세션**에서 보정과 G4를 수집한다. 설치된 장치 UID·번호,
   릴리스 revision, 원시 파일 digest와 단조 시각을 세션 시작에 고정한다.
   재부팅·전원 차단·릴리스 전환·PC 링크 상실은 세션을 중단하며 자동 재개하지
   않는다. 진행 UI는 한 번의 현장 조건 확인과 단계별 결과를 보여준다.
   새 구현의 모터 구동 허용은 boot ID에 묶인 일회성 세션 lease로 하고,
   재부팅 시 I/O는 무조건 no-drive로 시작한다. 현재처럼 persistent
   `drive=true`인 장치는 정상 재전원 전에 오프라인에서 no-drive 설정으로
   복구하고 readback해야 한다.
2. 기존 보정 알고리즘의 ROS-free 계산과 센서 일치성 검사를 재사용한다.
   실제 구동 명령은 CORE의 기존 인증·안전·최종 `cmd_vel` 경로로만 보낸다.
   운영 CORE 옆에서 보정 노드의 `cmd_vel_raw` 발행 경로를 켜지 않는다.
   보정 후보는 독립 holdout을 통과하기 전까지 적용하지 않는다.
3. 왕복·회전 보정 중 D-314의 속도·방향·누적 이동·정지 원인·지연 조건을
   **동일 원시 시간축**으로 만족한 leg만 해당 G4 시험에 재사용한다. 보정
   결과의 요약값을 원시 odom 대신 합성하지 않는다. 전진 명령 소실 시험은
   별도로 실행한다. 다섯 시험의 각 `stop_requested_at`, 전후 velocity·pose,
   지속 0, 파일 SHA-256을 네이티브 schema v2에 그대로 연결한다.
4. 시험 중 오도메트리·명령·정지와 네트워크 상태를 장치 쪽 독립 수집기로
   기록한다. PC API 연결이 끊기면 원격 zero/E-Stop은 최선으로 시도하되
   결과를 `UNOBSERVED/HOLD`로 남기고 현장 물리 차단을 우선한다. 원시 파일이
   없거나 불연속이면 G4 승인 입력으로 쓰지 않는다.
5. `mapping_approval.py`와 기동 때마다 봉인 자료를 다시 확인하는
   `rosy-navigation.service`를 동일한 검증 릴리스로 설치·해시 확인한다.
   누락된 도구 대신 빈 승인 마커를 만들거나 이전 unit의 파일 존재 검사만
   통과시키지 않는다. G4 승인 뒤 `hardware`/SLAM backend로 전환해 **빈
   지도에서** 맵핑하고, scan·odom·TF·SLAM/Nav2 readiness, 한 최종 발행자,
   지도·MCAP 해시, 마지막 0 속도와 E-Stop을 기록한다.
6. 보정은 거리 scale·회전 응답·센서 품질 판단에 사용한다. 물리 차단 접근성,
   실제 방향·정지 관찰, 명령 소실 시험, G4 봉인, G5 지도/주행 증거를
   대체하지 않는다. 검증되지 않은 보정값으로 주행 속도를 올리지 않는다.

## Consequences and rollout

PC 반복 질문과 수동 파일 편집은 한 번의 세션 안내와 자동 수집·검증으로
줄어든다. 장치 수집기는 CORE의 발행 권한을 얻지 않으며 관찰과 파일 기록만
한다. 구현 순서와 검증 게이트는
[현장 보정·G4·맵핑 실행 계획](../plans/2026-09-29-attended-calibration-g4-mapping.md)에
기록한다. 연결 소실·센서 불일치·과속·정지 실패·승인 실패 시 navigation을
시작하지 않고 E-Stop 및 no-drive 복귀를 확인한다. 전원 차단 때문에
복귀 readback이 불가능하면 장치를 `POWER_OFF_RECOVERY_REQUIRED`로
표시하고 재전원을 보류한다.

**Related:** [D-192](D-192-hardware-runtime-in-the-image.md),
[D-311](D-311-native-g4-evidence-gates-navigation.md),
[D-314](D-314-measured-g4-and-direct-teleop.md),
[D-319](D-319-post-setup-motor-commissioning.md).

## Addendum (2026-10-01): 보정 세션은 모든 화면에 보이고 다른 행위자를 막는다

**Status:** Accepted (2026-10-01, `feat/calibration-session-mode`). 소스·호스트
시험까지. 장치 위 확인은 별도 HOLD.

**Context.** 결정 1은 "릴리스 전환·PC 링크 상실은 세션을 중단한다"고 적었지만,
세션이 어디에도 보이지 않았다. 2026-10-01 한 세션의 보정 주행이 다른 세션의
릴리스 push(`rosy-release-push.ps1`)와 CORE 재시작에 끊겼다. Pilot 을 든
사람도 대시보드를 보는 사람도 보정 중인 줄 몰랐고, 막을 방법도 없었다.

**Decision.**

1. CORE 가 보정 세션 **lease** 를 가진다: `POST /api/v1/calibration/session`
   `{kind, label, ttl_s}`(Operator) → 세션 id 와 owner(호출 토큰 id).
   owner 는 `ttl_s`(기본 30 s, 5–300) 안에 `POST …/{id}/heartbeat` 로 갱신한다.
   갱신이 끊기면 세션은 만료된다 — 보정 도구가 죽거나 링크가 끊겨도 로봇이
   영원히 잠기지 않는다. `DELETE …/{id}` 는 owner 또는 Administrator(걸린
   lease 강제 해제). 로봇당 세션 하나. 모양은 API Ref v1.67 이 고정한다.
2. 살아 있는 동안 상태 스냅샷(`/robot/state`, `/ws/state`)이
   `activity: {kind: CALIBRATING, session_id, calibration_kind, label, owner,
   started_at, remaining_s}` 를 싣는다. Pilot 은 "보정 중 — <label>" 판과 HUD
   칩, 대시보드는 로봇 카드·모드 옆 칩, 로봇 LCD 는 MODE 행에 `CALIBRATING`
   (LCD 글꼴이 ASCII 뿐이라 D-221 대로 기계어)을 보인다.
3. 다른 토큰의 구동 쓰기 — `POST /teleop`, `POST /mode`(IDLE 제외),
   `PUT /line-follow/mode`(OFF 제외), `POST /line-follow/hold`,
   `POST /navigation/goal`·`/home`, `POST /docking/dock`·`/undock`,
   `POST /swarm/follow` — 는 409 `CALIBRATION_ACTIVE`. Fleet 도 같은 HTTP
   경로로 명령하므로 같이 막힌다. owner 의 teleop 은
   D-342 수동 한도 안에서 그대로 동작한다. **E-Stop 은 누구에게나 열려 있다**
   (`POST /safety/stop` 은 이 lease 를 보지 않는다). 멈추기만 하는 `/mode` IDLE,
   line-follow OFF, 각종 cancel 도 막지 않는다. Pilot 은 owner 가 아니면 주행 조작을 사유와 함께 끄고
   명령을 보내지 않지만, 최종 판정은 CORE 의 409 다.
4. 이 lease 는 아무것도 구동하지 않는다. 모드 전이도 `cmd_vel` 도 만들지 않는다
   — [D-2](D-2-cmd-vel.md) 그대로 CORE 가 유일한 최종 발행자이고, 보정
   구동은 결정 2 대로 CORE 의 기존 인증·안전 경로를 탄다.
5. CORE 를 재시작하는 운영 도구(`rosy-release-push.ps1`, `dev/sync-core-dev.ps1`)는
   원격 단계 전에 `rosy-calibration-guard.ps1` 로 세션을 묻고, 살아 있으면
   거부한다(`-Force` 로만 넘김). 토큰이 없거나 CORE 가 답하지 않으면 크게
   경고만 한다 — 고장 난 CORE 를 고치는 push 를 이 검사가 막으면 안 된다.
6. 이벤트 `calibration.session_started` / `_ended` / `_expired`(warning)를
   낸다. 만료 이벤트는 읽기마다와 CORE 전원 정책 타이머에서 한 번 난다.

**Consequences.** 보정 도구(`tools/calibration/run_calibration.py`,
`feat/camera-extrinsic-autocalib`)는 플래그 뒤에서 세션을 열고 heartbeat 한다.
재부팅·CORE 재시작은 메모리의 lease 를 지운다 — 결정 1 대로 세션은 자동 재개되지
않고, 도구의 다음 heartbeat 가 404 를 받아 중단을 알게 된다. 장치의 systemd 수동
재시작은 막지 못하며 SKILL 절차가 guard 실행을 요구한다.

**Related:** [D-2](D-2-cmd-vel.md),
[D-342](D-342-manual-limit-commissioning-ladder.md),
[D-344](D-344-pilot-assisted-autonomy.md),
[D-378](D-378-real-drive-errors-and-autonomy-gates.md).
