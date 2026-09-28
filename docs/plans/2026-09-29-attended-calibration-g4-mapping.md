# 현장 보정·G4·빈 지도 맵핑을 한 흐름으로 연결하는 실행 계획

**결정:** [D-321](../adr/D-321-attended-calibration-g4-mapping.md) Accepted.
**현재 상태:** 설계 완료, 구현·서명 릴리스·장치 G4/G5 HOLD. 현장 장치는
전원이 차단되어 있다. 기존 실측의 장치 식별자와 원시 파일은
`X:\DevTemp\<session>`에만 보관한다.

## 확인한 출발점

| 경계 | 확인한 사실 | 다음 작업 |
|---|---|---|
| 장치 릴리스 | 설치본에는 `mapping_approval.py`가 없고 navigation unit은 두 마커의 존재만 검사한다 | 승인 도구와 `ExecCondition`이 같은 검증 릴리스에 들어가야 한다 |
| G4 수집 | 전진, 재시험 후진, 양방향 회전의 원시 수치 검사는 통과했다. 현장 확인은 전진·재시험 후진·시계 방향만 명시적으로 받았다 | 반시계 방향 현장 판정과 명령 소실 시험은 미완료로 둔다 |
| 연결 소실 | 마지막 명령 소실 시도는 명령·시각·odom 샘플이 0개다. PC Wi-Fi 드라이버가 연결을 해제했고 SSH/API/Fleet가 동시에 끊겼다 | 실패 기록을 유지하고 장치 독립 수집기를 만든다 |
| 보정 소스 | `RoundTrip`은 제한된 전후 왕복과 LiDAR/odom 비교, `RotationTrial`은 양방향 회전과 LiDAR/IMU/odom 비교를 수행한다 | ROS-free 판정만 재사용하고 CORE를 유일한 최종 구동 경로로 유지한다 |
| 지도 | 빈 지도에서 SLAM backend로 생성할 수 있지만 설치 장치에는 지도와 G4 승인 자료가 없다 | G4 봉인과 런타임 검증 뒤 SLAM을 시작한다 |
| 다음 부팅 | 현장 차단 전 runtime 파일은 `motor`/`drive=true`였고 I/O unit은 부팅 때 이 값을 읽어 torque를 켠다 | 카드의 no-drive 복구와 readback 전에는 정상 재전원을 금지한다 |

## 먼저: 전원이 꺼진 현 장치 복구

현재 설치본은 전원 차단 뒤에도 구동 설정을 유지한다. 전원을 다시 넣기 전에
승인된 오프라인 Linux media 절차로 장치 카드의 `/etc/rosy/runtime.env`를
`ROSY_RUNTIME_MODE=core` 및 drive flag 제거/no-drive로 복구하고, 카드
UID·번호·릴리스와 파일 바이트를 readback한다. 이 절차와 도구가 준비되지
않으면 장치는 전원 차단 상태를 유지한다. 복구 뒤 첫 부팅은 바퀴와 전원
차단 경로를 현장 관리하며 torque disabled, E-Stop, 구동 capability false를
확인한다. 연결 소실 시도는 G4 원시 자료로 재사용하지 않는다.
현재 Windows의 `read-card-diagnostics.py`는 ext4 **읽기 전용**이며
USB SD에 `wsl --mount`를 사용하는 경로는 지원되지 않는다. 따라서
승인된 Linux 쓰기·readback 절차 또는 검증된 카드 재기록 경로가
마련되기 전까지 복구 단계를 완료했다고 표시하지 않는다.

Linux 호스트용 [오프라인 no-drive 복구 절차](../deployment/pinky-offline-no-drive-recovery.md)와
`sd/recover-no-drive.py`를 소스에 추가했다. 실제 카드에 적용하거나 첫 부팅
readback을 수행한 기록은 아직 없으므로 현 장치 복구 상태는 계속 HOLD다.

## 단계 1. 끊겨도 정직한 PC 진행 도우미

현재 `deploy/robot/pinky_pro/sd/enable-motor-commissioning.ps1` 뒤에 한
명령으로 실행되는 현장 도우미를 둔다. 장치 UID·릴리스·CORE 응답·SSH
호스트 키·PC의 지정 네트워크 인터페이스·E-Stop·현재 모터 토크·fresh
odom·단일 최종 `cmd_vel`·설치 승인 도구와 unit 해시를 읽고, 표 형태의
`READY/HOLD`와 필요한 다음 조치 하나를 보여준다. 연결 불량 또는 서명
릴리스 불일치가 있으면 E-Stop을 해제하지 않는다.

도우미는 `PREFLIGHT → ATTENDED → MOTOR_READY → CALIBRATING →
G4_REVIEW → G4_SEALED → SLAM_READY → MAPPING → STOPPED`로 진행한다.
한 번 받은 현장 입회·전원 차단 준비는 세션 안에서 유지하고 화면마다 다시
묻지 않는다. 별도 시험마다 원시 결과와 중단 버튼을 보인다. 네트워크
인터페이스 다운, API timeout, identity/release 변경, stale sensor,
E-Stop, 재부팅은 `HOLD`로 전이하고 자동 재개하지 않는다.
네이티브 I/O의 구동 허용은 persistent runtime flag가 아니라 현재 boot ID에
묶인 일회성 lease와 명시적 현장 세션으로 묶는다. lease가 없거나 재부팅되면
I/O는 torque-disabled로 시작한다. 전원 차단 중에는 원격 롤백을 완료한
것처럼 표시하지 않고 `POWER_OFF_RECOVERY_REQUIRED`를 남긴다.

PC의 `finally`는 zero와 E-Stop을 최선으로 시도하고 응답 유무를 별도
기록한다. 샘플 0개이거나 stop 시각이 없는 시도는 디버깅 파일만 남기고
G4 번들에서 제외한다. 비어 있는 배열의 마지막 원소를 읽다가 원래 오류를
가리는 예외 처리도 없앤다. 테스트는 API 지연, PC Wi-Fi 해제, SSH만
끊김, 전원 차단, 재연결을 주입해 각 경우의 `HOLD`와 원시 보존을 확인한다.

## 단계 2. 보정과 원시 G4 수집 연결

`src/runtime/sensing/control/control/round_trip.py`,
`rotation_trial.py`, `commissioning_certificate.py`의 ROS-free 판정과
holdout 계약을 재사용한다. `startup_calibration_node.py`의 기존
`cmd_vel_raw` publisher는 운영 CORE와 함께 실행하지 않는다. 장치
측 수집기는 scan·odom·IMU·명령·안전 상태를 **관찰만** 하고 단조 시각,
장치/릴리스 identity, 원시 파일 SHA-256을 영속 기록한다. CORE가
인증·MANUAL·속도 제한·500ms watchdog·최종 발행을 소유한다.

보정 leg를 G4로 재사용할 때는 G4 schema v2의 실제 방향, 버튼 해제
시각, 요청/실측 속도, 연속 odom, 지속 0, 정지 지연을 같은 원시
타임라인에서 검증한다. 전진·후진·CW·CCW 중 자격을 충족하지 못한 leg만
재시험한다. 전진 명령 소실은 별도 한 회로 기록한다. 각 시험은 선속도
0.03m/s, 각속도 0.10rad/s, 누적 평면 이동 0.10m, 정지 지연 0.65초
한도를 유지한다. 보정 후보는 독립 holdout 전까지 적용하지 않는다.
센서 간 불일치와 미확인 바닥 이동은 속도 승격 사유가 아니다.

장치 수집기가 없거나 전원이 끊겨 원시 파일을 완결하지 못하면 해당
시도는 `UNOBSERVED`다. 링크가 복구돼도 그 시도의 끝을 추정하지 않는다.
현장 작업자는 실제 이동과 정지를 볼 수 있어야 하며, 이상 시 물리
전원을 차단한다.

## 단계 3. 승인 도구와 서명 릴리스

`deploy/robot/pinky_pro/native/mapping_approval.py`와
`rosy-navigation.service`의 `ExecCondition`을 네이티브 payload에
함께 넣는다. 릴리스 서명, manifest, ROS deb 버전, 장치 설치 경로의
파일 해시, systemd unit readback을 확인한다. 기존 릴리스에 임시
마커나 출처 다른 도구만 복사하지 않는다. G4 다섯 원시 파일과
preflight 파일을 작업자가 검토하고 `approve`가 장치/릴리스/해시를
봉인한다. `check`는 hardware 전환 전후와 매 navigation 기동 때
통과해야 한다.

## 단계 4. 빈 지도에서 SLAM 맵핑

G4가 봉인된 뒤 `hardware` + `ROSY_NAVIGATION_BACKEND=slam`으로
전환한다. `rosy-io`와 `rosy-navigation`은 동시에 실행하지 않는다.
SLAM Toolbox와 Nav2 lifecycle, scan·odom·TF freshness, costmap,
CORE의 한 최종 발행자, 제한 속도, 빈 지도 상태를 확인한다. 낮은 속도의
짧은 현장 이동으로 지도를 만들고 YAML/PGM·MCAP·원시 중지 자료의
해시를 보존한다. 마지막 0 속도, E-Stop, 모터 토크 해제 또는 no-drive
복귀를 읽어야 세션을 종료한다.

## 검증과 롤백

1. ROS-free 보정·G4 변환기와 PC 도우미의 실패 주입 시험: 각 방향,
   명령 소실, 재시작, 센서 불일치, 과속, Wi-Fi 해제, 샘플 0개,
   중복·변조 raw 파일을 거부한다.
2. 설치 후보 ARM64 이미지·unit·승인 도구의 동일 릴리스 closure와
   빈 마커 거부를 확인한다. 호스트 테스트만으로 장치 수용을 올리지 않는다.
3. 장치에서 단계별 readback, 현장 이동 방향·정지·물리 차단,
   G4 봉인, 실제 SLAM 지도와 마지막 정지까지 각각 기록한다.
4. 어느 단계에서든 이상이 있으면 navigation/IO를 중지하고 이전
   `runtime.env`로 복귀해 `core` no-drive, E-Stop, 두 모터의 torque
   disabled를 확인한다. 검증된 이전 서명 릴리스가 롤백 기준이다.
